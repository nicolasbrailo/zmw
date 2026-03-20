"""Tracks per-user presence based on device join/leave events.

Deduplicates at the user level: a user with multiple devices is "home" if any
device is connected, and "away" only when all devices have left. A cooldown
delays the "away" event so that flaky WiFi (brief disconnect then reconnect)
does not cause a spurious away/home cycle.
"""

import threading

from zzmw_lib.logs import build_logger

log = build_logger("UserDevicePresenceMon")


class UserDevicePresenceMon:
    def __init__(self, device_owners, on_state_change, leave_cooldown_secs=60):
        """
        device_owners: dict of {user: [device1, device2, ...]}
            where devices are hostnames or MAC addresses.
        leave_cooldown_secs: delay before emitting "away" after all devices
            disconnect. If a device reconnects within this window the "away"
            is cancelled. 0 to disable (emit immediately).
        on_state_change: callback(user, new_state, device_id) called on
            state transitions. new_state is "home" or "away".
        """
        # device -> user reverse map
        self._device_to_user = {}
        for user, devices in device_owners.items():
            for device in devices:
                self._device_to_user[device] = user

        self._leave_cooldown_secs = leave_cooldown_secs
        self._on_state_change = on_state_change

        # user -> set of currently connected device identifiers
        self._user_devices = {}
        # user -> True (home) / False (away); None = unknown
        self._user_state = {}
        # user -> pending away Timer
        self._pending_away_timers = {}

    def seed_connected_device(self, hostname, mac):
        """Record a device as connected without firing the state change callback.

        Used at startup to rebuild presence state from currently connected clients.
        """
        user = self._device_to_user.get(hostname) or self._device_to_user.get(mac)
        if user is None:
            return
        device_id = hostname or mac
        self._user_devices.setdefault(user, set()).add(device_id)
        self._user_state[user] = True

    def on_device_event(self, event_type, hostname, mac):
        """Process a device join/leave event.

        State changes are delivered via the on_state_change callback.
        """
        user = self._device_to_user.get(hostname) or self._device_to_user.get(mac)
        if user is None:
            return

        device_id = hostname or mac

        if event_type == "joined":
            self._on_device_joined(user, device_id)
        elif event_type == "left":
            self._on_device_left(user, device_id)

    def _on_device_joined(self, user, device_id):
        self._user_devices.setdefault(user, set()).add(device_id)

        # Cancel any pending away — the device came back
        timer = self._pending_away_timers.pop(user, None)
        if timer is not None:
            timer.cancel()
            log.info("%s reconnected during cooldown (%s), cancelling away", user, device_id)

        if self._user_state.get(user) is True:
            return

        self._user_state[user] = True
        log.info("%s is home (%s)", user, device_id)
        self._on_state_change(user, "home", device_id)

    def _on_device_left(self, user, device_id):
        devices = self._user_devices.get(user, set())
        devices.discard(device_id)

        if devices:
            # User still has other devices connected
            return

        # Only emit away if user is currently home — skip if already away or never seen
        if self._user_state.get(user) is not True:
            return

        # Already have a pending away timer for this user
        if user in self._pending_away_timers:
            return

        if self._leave_cooldown_secs > 0:
            log.info("All devices gone for %s, starting %ds cooldown", user, self._leave_cooldown_secs)
            timer = threading.Timer(self._leave_cooldown_secs, self._emit_away, args=(user, device_id))
            timer.daemon = True
            timer.start()
            self._pending_away_timers[user] = timer
        else:
            self._emit_away(user, device_id)

    def _emit_away(self, user, device_id):
        self._pending_away_timers.pop(user, None)
        self._user_state[user] = False
        log.info("%s is leaving (%s)", user, device_id)
        self._on_state_change(user, "away", device_id)

    @property
    def user_states(self):
        """Return a copy of {user: True/False/None} state map."""
        return dict(self._user_state)
