"""
ThingExtras: Per-thing storage for non zigbee2mqtt values.

Each Thing has an `extras` attribute that stores virtual/computed metrics.
Values are stored locally and broadcast via z2mproxy.broadcast_thing().

Usage:
    # Set a value locally
    thing.extras.set('feels_like_temp', 22.5)

    # Broadcast all pending changes (both regular values and extras)
    z2mproxy.broadcast_thing(thing)

    # Get a value
    feels_like = thing.extras.get('feels_like_temp')
"""

import threading
from zzmw_lib.logs import build_logger

log = build_logger("Z2MThingExtras")

THING_EXTRAS_TOPIC = 'zmw_thing_extras'


class ThingExtras:
    """Per-thing storage for extra/virtual metrics."""

    def __init__(self, thing_name):
        """Initialize ThingExtras.

        Args:
            thing_name: Name of the thing these extras belong to
        """
        self._thing_name = thing_name
        self._lock = threading.Lock()
        self._values = {}
        self._needs_broadcast = False

    def get_mqtt_topic(self):
        return f"{THING_EXTRAS_TOPIC}/{self._thing_name}"

    def set(self, metric, value):
        """Set a metric value locally. """
        with self._lock:
            self._values[metric] = value
            self._needs_broadcast = True

    def get(self, metric):
        """Get a specific metric value. Unlike non-extra things, there is no schema for extra values, so
        trying to retrieve a key that doesn't exist isn't an error."""
        with self._lock:
            return self._values.get(metric)

    def get_all(self):
        """ Get all metric values. """
        with self._lock:
            return self._values.copy()

    def make_mqtt_status_update(self):
        """ Get values to broadcast (if any) and clear the needs_broadcast flag. """
        with self._lock:
            if not self._needs_broadcast:
                return {}
            self._needs_broadcast = False
            return self._values.copy()

    def on_mqtt_update(self, _topic, payload):
        """Update values from an incoming MQTT message. """
        if not isinstance(payload, dict):
            log.warning("Ignoring non-dict payload for %s: %s", self._thing_name, payload)
            return

        with self._lock:
            self._values.update(payload)
        # log.debug("Updated extras for %s: %s", self._thing_name, payload)

    def __contains__(self, metric):
        """Check if a metric exists."""
        with self._lock:
            return metric in self._values
