"""Detects unknown devices joining the network.

Maintains a persistent dict of device metadata keyed by MAC. On first startup,
all currently connected devices are assumed known/trusted. Subsequent joins by
MACs not in the dict are flagged as unknown.

Each device entry: {"trusted": bool, "alias": str|None}
"""

from flask import request
from zzmw_lib.logs import build_logger
from zzmw_lib.runtime_state_cache import runtime_state_cache_get, runtime_state_cache_set

log = build_logger("UnknownDeviceMon")

STATE_KEY = "unknown_device_mon_known_macs"
DEVICE_META_KEY = "unknown_device_mon_device_meta"


class UnknownDeviceMon:
    def __init__(self):
        self._device_meta = {}  # {mac: {"trusted": bool, "alias": str|None}}
        self._initialized = False
        self._previous_macs = None

        # Migrate from old format (list of MACs) or load new format
        meta = runtime_state_cache_get(DEVICE_META_KEY)
        if meta is not None:
            self._device_meta = meta
            self._initialized = True
            log.info("Loaded %d devices from cache", len(self._device_meta))
        else:
            # Try migrating old format
            old = runtime_state_cache_get(STATE_KEY)
            if old is not None:
                for mac in old:
                    self._device_meta[mac] = {"trusted": True, "alias": None}
                self._initialized = True
                self._save()
                log.info("Migrated %d devices from old cache format", len(self._device_meta))

    def on_poll(self, all_clients):
        """Process the full client list from a poll cycle."""
        current_macs = set(all_clients.keys())

        if not self._initialized:
            for mac in current_macs:
                self._device_meta[mac] = {"trusted": True, "alias": None}
            self._initialized = True
            self._previous_macs = current_macs
            self._save()
            log.info("First startup, seeding %d devices as known", len(self._device_meta))
            return

        if self._previous_macs is None:
            self._previous_macs = current_macs
            return

        newly_joined = current_macs - self._previous_macs
        self._previous_macs = current_macs

        dirty = False
        for mac in newly_joined:
            if mac not in self._device_meta:
                info = all_clients[mac]
                log.error("Unknown device joined: %s (%s) %s", info["hostname"], mac, info["ip"])
                self._device_meta[mac] = {"trusted": False, "alias": None}
                dirty = True

        if dirty:
            self._save()

    @property
    def known_macs(self):
        """Return the set of all tracked MACs."""
        return set(self._device_meta.keys())

    def get_device_meta(self, mac):
        """Return metadata for a device, or default untrusted entry."""
        return self._device_meta.get(mac, {"trusted": False, "alias": None})

    def set_trusted(self, mac, trusted):
        if mac not in self._device_meta:
            self._device_meta[mac] = {"trusted": trusted, "alias": None}
        else:
            self._device_meta[mac]["trusted"] = trusted
        self._save()

    def set_alias(self, mac, alias):
        if mac not in self._device_meta:
            self._device_meta[mac] = {"trusted": False, "alias": alias}
        else:
            self._device_meta[mac]["alias"] = alias or None
        self._save()

    def http_set_trusted(self):
        data = request.get_json()
        self.set_trusted(data["mac"], data["trusted"])
        return {"ok": True}

    def http_set_alias(self):
        data = request.get_json()
        self.set_alias(data["mac"], data.get("alias", ""))
        return {"ok": True}

    def _save(self):
        runtime_state_cache_set(DEVICE_META_KEY, self._device_meta)
