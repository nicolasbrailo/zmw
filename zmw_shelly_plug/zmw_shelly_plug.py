"""MQTT service for monitoring Shelly smart plugs."""
import os
import pathlib
import threading

from zzmw_lib.service_runner import service_runner
from zzmw_lib.zmw_mqtt_service import ZmwMqttService
from zzmw_lib.logs import build_logger

from shelly import ShellyPlug

log = build_logger("ZmwShellyPlug")

class ZmwShellyPlug(ZmwMqttService):
    """Service that monitors Shelly plugs and broadcasts stats via MQTT."""

    def __init__(self, cfg, www, _sched):
        super().__init__(cfg, svc_topic="zmw_shelly_plug", scheduler=_sched)
        # Set up www directory and endpoints
        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        self._public_url_base = www.register_www_dir(www_path)

        self._devices = [ShellyPlug(host) for host in cfg["devices_to_monitor"]]
        self._bcast_period_secs = cfg["bcast_period_secs"]
        self._timer = None

        www.serve_url('/ls_devs', lambda: [d.get_name() for d in self._devices])
        www.serve_url('/all_stats', lambda: {d.get_name(): d.get_stats_bg() for d in self._devices})
        self._bcast()

    def get_mqtt_description(self):
        return {
            "description": "Monitors Shelly smart plugs, broadcast on MQTT power/energy stats.",
            "meta": self.get_service_meta(),
            "commands": {
                "ls_devs": {
                    "description": "List of devices. Response on ls_devs_reply",
                    "params": {}
                },
                "all_stats": {
                    "description": "Last stats for all devices. Response on all_stats_reply",
                    "params": {}
                },
                "get_mqtt_description": {
                    "description": "Service description",
                    "params": {}
                },
            },
            "announcements": {
                "<device_name>/stats": {
                    "description": "Periodically published stats for each online Shelly plug",
                    "payload": {
                        "device_name": "Name",
                        "powered_on": "Switch is on",
                        "active_power_watts": "Power draw in watts",
                        "voltage_volts": "Voltage",
                        "current_amps": "Amperage",
                        "temperature_c": "Device temperature",
                        "lifetime_energy_use_watt_hour": "Total energy usage in Wh",
                        "last_minute_energy_use_watt_hour": "Energy used in the last minute in Wh",
                        "device_current_time": "Device local time",
                        "device_uptime": "Device uptime in seconds",
                        "device_ip": "Device WiFi IP address",
                        "online": "Whether the device is reachable"
                    }
                },
                "ls_devs_reply": {
                    "description": "List of devices",
                    "payload": ["device_name_1", "device_name_2"]
                },
                "all_stats_reply": {
                    "description": "Map of device name to stats object",
                    "payload": "See `<device_name>/stats`",
                },
                "get_mqtt_description_reply": {
                    "description": "Service description",
                    "payload": {"commands": {}, "announcements": {}}
                },
            }
        }

    def _bcast(self):
        self._timer = threading.Timer(self._bcast_period_secs, self._bcast)
        self._timer.start()
        for dev in self._devices:
            stats = dev.get_stats_bg()
            if stats and stats["online"]:
                self.publish_own_svc_message(f'{stats["device_name"]}/stats', stats)

    def stop(self):
        """Stop the broadcast timer and clean up."""
        if self._timer:
            self._timer.cancel()
            self._timer = None
        super().stop()

    def on_service_received_message(self, subtopic, _payload):
        """Handle incoming service messages."""
        if subtopic.endswith('_reply'):
            return

        match subtopic:
            case "ls_devs":
                self.publish_own_svc_message("ls_devs_reply",
                    [d.get_name() for d in self._devices])
            case "all_stats":
                self.publish_own_svc_message("all_stats_reply",
                    {d.get_name(): d.get_stats_bg() for d in self._devices})
            case "get_mqtt_description":
                self.publish_own_svc_message("get_mqtt_description_reply",
                    self.get_mqtt_description())
            case _:
                # Ignore all echo messages
                pass

    def on_dep_published_message(self, svc_name, subtopic, payload):
        """Handle messages from dependencies (unexpected)."""
        log.error("Unexpected dep %s message %s %s", svc_name, subtopic, payload)


service_runner(ZmwShellyPlug)
