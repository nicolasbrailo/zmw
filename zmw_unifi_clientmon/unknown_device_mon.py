"""Detects unknown devices joining the network.

Maintains a persistent set of known device MACs. On first startup, all
currently connected devices are assumed known. Subsequent joins by MACs
not in the known set are flagged as unknown.
"""

from zzmw_lib.logs import build_logger
from zzmw_lib.runtime_state_cache import runtime_state_cache_get, runtime_state_cache_set

log = build_logger("UnknownDeviceMon")

STATE_KEY = "unknown_device_mon_known_macs"


class UnknownDeviceMon:
    def __init__(self):
        cached = runtime_state_cache_get(STATE_KEY)
        if cached is not None:
            self._known_macs = set(cached)
            log.info("Loaded %d known devices from cache", len(self._known_macs))
        else:
            self._known_macs = None  # Not yet initialized
        self._previous_macs = None

    def on_poll(self, all_clients):
        """Process the full client list from a poll cycle.

        all_clients: dict of {mac: {hostname, mac, ip}} — all connected clients.
        On first call, seeds known MACs (no alerts). On subsequent calls, detects
        new devices joining and flags unknown ones.
        """
        current_macs = set(all_clients.keys())

        if self._known_macs is None:
            # First startup ever — assume all current devices are known
            self._known_macs = set(current_macs)
            self._previous_macs = current_macs
            self._save()
            log.info("First startup, seeding %d devices as known", len(self._known_macs))
            return

        if self._previous_macs is None:
            # Service restarted with existing cache — no diff yet
            self._previous_macs = current_macs
            return

        newly_joined = current_macs - self._previous_macs
        self._previous_macs = current_macs

        dirty = False
        for mac in newly_joined:
            if mac not in self._known_macs:
                info = all_clients[mac]
                # TODO do something smarter
                log.error("Unknown device joined: %s (%s) %s", info["hostname"], mac, info["ip"])
                self._known_macs.add(mac)
                dirty = True

        if dirty:
            self._save()

    @property
    def known_macs(self):
        """Return the set of known MACs, or empty set if not yet initialized."""
        return self._known_macs or set()

    def _save(self):
        runtime_state_cache_set(STATE_KEY, list(self._known_macs))
