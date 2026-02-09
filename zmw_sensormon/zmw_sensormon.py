"""Sensor monitoring and history service."""
from zzmw_lib.zmw_mqtt_service import ZmwMqttService
from zzmw_lib.logs import build_logger
from zzmw_lib.service_runner import service_runner

from zz2m.z2mproxy import Z2MProxy
from zz2m.www import Z2Mwebservice

from sensors import SensorsHistory
from virtual_metrics import get_virtual_metrics, compute_virtual_metrics
from outside_weather import OutsideWeatherSensor

import os
import pathlib

log = build_logger("ZmwSensormon")

# 'linkquality' can be monitored too, but that means we're monitoring a lot more than sensors
INTERESTING_ACTIONS = [
    'ac_frequency', 'battery', 'contact', 'current_a', 'current_b', 'device_temperature',
    'energy_a', 'energy_b', 'energy_flow_a', 'energy_flow_b', 'energy_produced_a', 'energy_produced_b',
    'humidity', 'occupancy', 'pm25', 'power_a', 'power_ab', 'power_b', 'power_factor_a',
    'power_factor_b', 'temperature', 'voc_index', 'voltage']

def interesting_actions(thing):
    """Filter actions to return only those that are interesting sensors to monitor."""
    acts = []
    for action_name in thing.actions:
        if action_name in INTERESTING_ACTIONS:
            acts.append(action_name)
    return acts

class ShellyAdapter:
    """Adapts Shelly plug MQTT payloads to the thing interface expected by SensorsHistory."""
    METRICS = [
        'active_power_watts', 'voltage_volts', 'current_amps', 'device_temperature',
        'lifetime_energy_use_watt_hour', 'last_minute_energy_use_watt_hour'
    ]
    # Map payload keys to metric names (for renaming)
    PAYLOAD_TO_METRIC = {
        'temperature_c': 'device_temperature',
    }

    def __init__(self, name, sensors_history):
        self.name = name
        self._sensors = sensors_history
        self._values = {}

    def get(self, metric_name):
        """Return the current value for a metric."""
        return self._values.get(metric_name)

    def update(self, payload):
        """Update internal values from a Shelly MQTT payload and save to DB."""
        for metric in self.METRICS:
            payload_key = next((k for k, v in self.PAYLOAD_TO_METRIC.items() if v == metric), metric)
            if payload_key in payload:
                self._values[metric] = payload[payload_key]
        self._sensors.save_reading(self.name, {m: self.get(m) for m in self.METRICS})


class ShellyPlugMonitor:
    """Monitors Shelly plug devices and records their stats to sensor history."""

    def __init__(self, sensors):
        self._sensors = sensors
        self._known_shellies = {}

    def get_current_values(self, name):
        """Returns current values for a Shelly device, or None if not known."""
        if name not in self._known_shellies:
            return None
        adapter = self._known_shellies[name]
        return {metric: adapter.get(metric) for metric in ShellyAdapter.METRICS}

    def on_message(self, topic, payload):
        """Handle incoming Shelly MQTT messages and update sensor history."""
        if "get_mqtt_description" in topic:
            # Ignore MQTT self-description from Shelly service
            return
        parts = topic.split('/')
        if len(parts) != 2:
            log.warning("Unexpected shelly topic format '%s': %s", topic, payload)
            return
        sensor_name, action = parts

        if action != 'stats':
            log.warning("Unhandled action '%s': %s", topic, payload)
            return

        if sensor_name not in self._known_shellies:
            try:
                self._sensors.register_sensor(sensor_name, ShellyAdapter.METRICS)
                self._known_shellies[sensor_name] = ShellyAdapter(sensor_name, self._sensors)
                log.info("New shelly plug discovered: %s", sensor_name)
            except ValueError:
                log.error("New sensor '%s' can't be registered. This may be normal if a Shelly plug has no known name yet",
                          sensor_name, exc_info=True)
                return

        self._known_shellies[sensor_name].update(payload)


class ZmwSensormon(ZmwMqttService):
    """MQTT service for monitoring sensor data and maintaining history."""
    def __init__(self, cfg, www, sched):
        super().__init__(cfg, "zmw_sensormon", scheduler=sched)
        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        self._public_url_base = www.register_www_dir(www_path)

        self._sensors = SensorsHistory(dbpath=cfg['db_path'], scheduler=sched, retention_days=cfg['retention_days'])
        self._sensors.register_to_webserver(www)

        self._z2m = Z2MProxy(cfg, self, sched,
                             cb_on_z2m_network_discovery=self._on_z2m_network_discovery,
                             cb_is_device_interesting=lambda t: len(interesting_actions(t)) > 0)
        self._z2mw = Z2Mwebservice(www, self._z2m)

        self._shelly_monitor = ShellyPlugMonitor(self._sensors)
        self.subscribe_with_cb('zmw_shelly_plug', self._shelly_monitor.on_message)

        self._outside_weather = OutsideWeatherSensor(
            self._sensors, self._z2m, sched,
            latitude=cfg['outside_latitude'], longitude=cfg['outside_longitude'],
            update_interval_seconds=300)

        www.serve_url('/sensors/get/<name>', self._get_sensor_values)
        www.serve_url('/sensors/get_all/<metric>', self._get_all_sensor_values)

    def get_mqtt_description(self):
        return {
            "description": "Sensor monitoring and history. Supports Zigbee, Shelly, and outside weather. "\
                           "Exposes current values and timeseries for temperature, humidity, power, battery, etc.",
            "meta": self.get_service_meta(),
            "commands": {
                "get_sensor_values": {
                    "description": "Current values for sensor. Response on get_sensor_values_reply",
                    "params": {"name": "Sensor (eg 'Living_Room', 'Weather')"}
                },
                "get_all_sensor_values": {
                    "description": "Current value of a metric in all sensors that have it. Response on get_all_sensor_values_reply",
                    "params": {"metric": "Metric (eg 'temperature', 'humidity'...)"}
                },
                "get_known_sensors": {
                    "description": "List sensors. Response on get_known_sensors_reply",
                    "params": {}
                },
                "get_known_metrics": {
                    "description": "List all known metrics in all sensors. Response on get_known_metrics_reply",
                    "params": {}
                },
                "get_sensors_measuring": {
                    "description": "List sensors measuring this metric. Response on get_sensors_measuring_reply",
                    "params": {"metric": "Metric name"}
                },
                "get_mqtt_description": {
                    "description": "Service description",
                    "params": {}
                },
            },
            "announcements": {
                "get_sensor_values_reply": {
                    "description": "Dict of metric name to current value",
                    "payload": {"<metric>": "<value>"}
                },
                "get_all_sensor_values_reply": {
                    "description": "Dict of sensor name to metric value",
                    "payload": {"<sensor_name>": "<value>"}
                },
                "get_known_sensors_reply": {
                    "description": "List of sensor name strings",
                    "payload": ["<sensor_name>"]
                },
                "get_known_metrics_reply": {
                    "description": "List of metric name strings",
                    "payload": ["<metric_name>"]
                },
                "get_sensors_measuring_reply": {
                    "description": "List of sensor name strings",
                    "payload": ["<sensor_name>"]
                },
                "get_mqtt_description_reply": {
                    "description": "Service description",
                    "payload": {}
                },
            }
        }

    def on_service_received_message(self, subtopic, payload):
        if subtopic.endswith('_reply'):
            return

        match subtopic:
            case "get_sensor_values":
                if 'name' not in payload:
                    log.error("get_sensor_values: missing 'name' in payload: '%s'", payload)
                    return
                self.publish_own_svc_message("get_sensor_values_reply",
                    self._get_sensor_values(payload['name']))
            case "get_all_sensor_values":
                if 'metric' not in payload:
                    log.error("get_all_sensor_values: missing 'metric' in payload: '%s'", payload)
                    return
                self.publish_own_svc_message("get_all_sensor_values_reply",
                    self._get_all_sensor_values(payload['metric']))
            case "get_known_sensors":
                self.publish_own_svc_message("get_known_sensors_reply",
                    self._sensors.get_known_sensors())
            case "get_known_metrics":
                self.publish_own_svc_message("get_known_metrics_reply",
                    self._sensors.get_known_metrics())
            case "get_sensors_measuring":
                if 'metric' not in payload:
                    log.error("get_sensors_measuring: missing 'metric' in payload: '%s'", payload)
                    return
                self.publish_own_svc_message("get_sensors_measuring_reply",
                    self._sensors.get_known_sensors_measuring(payload['metric']))
            case "get_mqtt_description":
                self.publish_own_svc_message("get_mqtt_description_reply",
                    self.get_mqtt_description())
            case _:
                log.warning("Ignoring unknown message '%s'", subtopic)

    def _get_sensor_values(self, name):
        """Unified endpoint to get current sensor values from any backend."""
        # Check Shelly devices first (they're not in z2m)
        shelly_data = self._shelly_monitor.get_current_values(name)
        if shelly_data is not None:
            return {**shelly_data, **compute_virtual_metrics(shelly_data)}

        # Try z2m (includes both zigbee things and virtual things like OutsideWeather)
        try:
            vals = self._z2m.get_thing(name).get_json_state()
            # Some values may come as extras; flatten them
            vals.update(vals['extras'])
            return vals
        except KeyError:
            return {}

    def _get_all_sensor_values(self, metric):
        """Get current values for all sensors measuring a specific metric."""
        sensors = self._sensors.get_known_sensors_measuring(metric)
        result = {}
        for sensor_name in sensors:
            values = self._get_sensor_values(sensor_name)
            if metric in values:
                result[sensor_name] = values[metric]
        return result

    def _on_sensor_update(self, thing):
        """Handle sensor update: save to DB with virtual metrics."""
        metrics = interesting_actions(thing)
        values = {m: thing.get(m) for m in metrics}
        virtual_values = compute_virtual_metrics(values, thing)
        self._sensors.save_reading(thing.name, {**values, **virtual_values})
        if virtual_values:
            self._z2m.broadcast_thing(thing)

    def _on_z2m_network_discovery(self, _is_first_discovery, known_things):
        for thing_name, thing in known_things.items():
            acts = interesting_actions(thing)
            if len(acts) > 0:
                virtual_metrics = get_virtual_metrics(acts)
                all_metrics = acts + virtual_metrics
                log.info('Will monitor %s, publishes %s (virtual: %s)', thing_name, str(acts), str(virtual_metrics))
                try:
                    self._sensors.register_sensor(thing.name, all_metrics)
                    thing.on_any_change_from_mqtt = self._on_sensor_update
                except ValueError as ex:
                    # This will happen if a sensor has a name we don't like. Usually will happen when a new device
                    # is added to the network, before it gets a friendly name
                    log.error("Can't register sensor %s: %s", thing.name, ex)

service_runner(ZmwSensormon)
