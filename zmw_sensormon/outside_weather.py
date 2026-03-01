"""Outside weather sensor using Open-Meteo API."""

import json
import threading
import urllib.request
import urllib.error

from zzmw_lib.logs import build_logger
from zzmw_lib.z2m.thing import create_virtual_thing
from virtual_metrics import get_virtual_metrics, compute_virtual_metrics

log = build_logger("OutsideWeather")


class OutsideWeatherSensor:
    """Fetches outside weather data from Open-Meteo and records to sensor history."""

    METRICS = ['temperature', 'humidity']
    SENSOR_NAME = 'Weather'

    def __init__(self, sensors_history, z2m, scheduler, latitude, longitude, update_interval_seconds=300):
        """Initialize the outside weather sensor.

        Args:
            sensors_history: SensorsHistory instance to save readings
            z2m: Z2MProxy instance for thing management
            scheduler: Scheduler for periodic updates
            latitude: Location latitude
            longitude: Location longitude
            update_interval_seconds: How often to fetch new data (default: 5 minutes)
        """
        self._sensors = sensors_history
        self._z2m = z2m
        self._scheduler = scheduler

        self._api_url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}"
            "&current=temperature_2m,relative_humidity_2m"
        )

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
        log.info("Registered outside weather sensor at (%.4f, %.4f), updating every %ds (virtual: %s)",
                 latitude, longitude, update_interval_seconds, virtual_metrics)

        # Schedule periodic updates
        self._scheduler.add_job(
            func=self._trigger_async_update,
            trigger="interval",
            seconds=update_interval_seconds,
        )
        # Fetch immediately on startup
        self._trigger_async_update()

    def get_thing(self):
        """Return the virtual thing for this sensor."""
        return self._thing

    def _trigger_async_update(self):
        """Trigger an async fetch in a background thread."""
        thread = threading.Thread(target=self._fetch_and_save, daemon=True)
        thread.start()

    def _fetch_and_save(self):
        """Fetch data from API and save to database. Runs in a background thread."""
        try:
            with urllib.request.urlopen(self._api_url, timeout=30) as response:
                raw_response = response.read().decode()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            log.warning("Can't reach Open-Meteo service: %s", e)
            values = {metric: None for metric in self.METRICS}
            self._sensors.save_reading(self.SENSOR_NAME, values)
            return

        try:
            data = json.loads(raw_response)
            current = data['current']
            values = {
                'temperature': current['temperature_2m'],
                'humidity': current['relative_humidity_2m'],
            }
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            log.error("Failed to parse Open-Meteo response: %s (response: %s)", e, raw_response)
            values = {metric: None for metric in self.METRICS}
            self._sensors.save_reading(self.SENSOR_NAME, values)
            return

        # Set values on thing.extras
        for metric, value in values.items():
            self._thing.extras.set(metric, value)

        # Compute and set virtual metrics
        virtual_values = compute_virtual_metrics(values, self._thing)

        # Save to history and broadcast
        self._sensors.save_reading(self.SENSOR_NAME, {**values, **virtual_values})
        self._z2m.broadcast_thing(self._thing)
