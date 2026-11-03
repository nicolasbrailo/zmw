"""Outside weather sensor, from Open-Meteo via ZmwMeteoRelay."""

import threading

from zzmw_lib.logs import build_logger
from zzmw_lib.z2m.thing import create_virtual_thing
from virtual_metrics import get_virtual_metrics, compute_virtual_metrics

log = build_logger("OutsideWeather")


class OutsideWeatherSensor:
    """Records Open-Meteo reports (pushed by ZmwMeteoRelay) to sensor history.

    Doesn't fetch anything itself: the service feeds it every report the relay announces, plus one it asks for
    when the relay comes up.
    """

    METRICS = ['temperature', 'humidity']
    SENSOR_NAME = 'Weather'

    def __init__(self, sensors_history, z2m):
        """
        Args:
            sensors_history: SensorsHistory instance to save readings
            z2m: Z2MProxy instance for thing management
        """
        self._sensors = sensors_history
        self._z2m = z2m
        # Reports arrive from the MQTT thread (announcements) and from the startup fetch thread
        self._lock = threading.Lock()
        # Open-Meteo's `current.time` of the last saved reading. The startup fetch and an announcement (or a relay
        # restart) can deliver the same report twice; record it once.
        self._last_report_time = None

        # Create and register virtual thing
        self._thing = create_virtual_thing(
            name=self.SENSOR_NAME,
            description="Outside weather from Open-Meteo",
            thing_type="sensor",
            manufacturer="Open-Meteo"
        )
        z2m.register_virtual_thing(self._thing)

        # Register with sensors history
        virtual_metrics = get_virtual_metrics(self.METRICS)
        all_metrics = self.METRICS + virtual_metrics
        self._sensors.register_sensor(self.SENSOR_NAME, all_metrics)
        log.info("Registered outside weather sensor (virtual: %s)", virtual_metrics)

    def get_thing(self):
        """Return the virtual thing for this sensor."""
        return self._thing

    def on_weather_report(self, data):
        """Record an Open-Meteo forecast response (needs temperature_2m and relative_humidity_2m in `current`)."""
        try:
            current = data['current']
            report_time = current.get('time')
            values = {
                'temperature': current['temperature_2m'],
                'humidity': current['relative_humidity_2m'],
            }
        except (KeyError, TypeError, AttributeError) as e:
            log.error("Failed to parse Open-Meteo response: %s (response: %s)", e, data)
            return

        with self._lock:
            if report_time is not None and report_time == self._last_report_time:
                log.debug("Already recorded outside weather for %s, skipping", report_time)
                return
            self._last_report_time = report_time

            # Set values on thing.extras
            for metric, value in values.items():
                self._thing.extras.set(metric, value)

            # Compute and set virtual metrics
            virtual_values = compute_virtual_metrics(values, self._thing)

            # Save to history and broadcast
            self._sensors.save_reading(self.SENSOR_NAME, {**values, **virtual_values})
        self._z2m.broadcast_thing(self._thing)
