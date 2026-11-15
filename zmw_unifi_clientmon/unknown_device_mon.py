"""Detects unknown devices joining the network.

Maintains a persistent dict of device metadata keyed by MAC. On first startup,
all currently connected devices are assumed known/trusted. After that, any
connected MAC not in the dict is flagged as unknown (and added to it, untrusted).

Each device entry: {"trusted": bool, "alias": str|None, "trust_reason": str|None}
The alias defaults to the device's hostname, the first time one is seen.
"""

from flask import request
from zzmw_lib.logs import build_logger
from zzmw_lib.runtime_state_cache import runtime_state_cache_get, runtime_state_cache_set

log = build_logger("UnknownDeviceMon")

STATE_KEY = "unknown_device_mon_known_macs"
DEVICE_META_KEY = "unknown_device_mon_device_meta"


class UnknownDeviceMon:
    def __init__(self, on_unknown_device_joined=None):
        self._device_meta = {}  # {mac: {"trusted": bool, "alias": str|None, "trust_reason": str|None}}
        self._initialized = False
        self._on_unknown_device_joined = on_unknown_device_joined
        self._last_unknown_mac = None

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
        dirty = self._process_joins(all_clients)
        dirty = self._default_aliases_to_hostname(all_clients) or dirty
        if dirty:
            self._save()

    def _default_aliases_to_hostname(self, all_clients):
        dirty = False
        for mac, info in all_clients.items():
            meta = self._device_meta.get(mac)
            if meta is not None and not meta.get("alias") and info["hostname"] != "(unknown)":
                meta["alias"] = info["hostname"]
                dirty = True
        return dirty

    def _process_joins(self, all_clients):
        """Flag connected devices we haven't seen before. Returns True if device metadata changed."""
        current_macs = set(all_clients.keys())

        if not self._initialized:
            for mac in current_macs:
                self._device_meta[mac] = {"trusted": True, "alias": None}
            self._initialized = True
            log.info("First startup, seeding %d devices as known", len(self._device_meta))
            return True

        # Compare against known devices, not the previous poll: this also catches devices that joined while the
        # service was down, and forgotten devices that are still connected (UniFi may keep listing a client for a
        # while after it disconnects, so a short disconnect won't show up as a leave + join)
        unknown = current_macs - self._device_meta.keys()
        for mac in unknown:
            info = all_clients[mac]
            log.warning("Unknown device joined: %s (%s) %s", info["hostname"], mac, info["ip"])
            self._device_meta[mac] = {"trusted": False, "alias": None}
            self._last_unknown_mac = mac
            if self._on_unknown_device_joined is not None:
                self._on_unknown_device_joined(mac, info)

        return len(unknown) > 0

    @property
    def last_unknown_mac(self):
        """MAC of the most recent unknown device seen joining, or None (not persisted across restarts)."""
        return self._last_unknown_mac

    @property
    def known_macs(self):
        """Return the set of all tracked MACs."""
        return set(self._device_meta.keys())

    def get_device_meta(self, mac):
        """Return metadata for a device, or default untrusted entry."""
        return self._device_meta.get(mac, {"trusted": False, "alias": None})

    def set_trusted(self, mac, trusted, reason=None):
        if mac not in self._device_meta:
            self._device_meta[mac] = {"trusted": trusted, "alias": None}
        else:
            self._device_meta[mac]["trusted"] = trusted
        self._device_meta[mac]["trust_reason"] = reason if trusted else None
        self._save()

    def set_alias(self, mac, alias):
        if mac not in self._device_meta:
            self._device_meta[mac] = {"trusted": False, "alias": alias}
        else:
            self._device_meta[mac]["alias"] = alias or None
        self._save()

    def forget(self, mac):
        """Drop all metadata for a device: it'll be reported as unknown on the next poll where it's connected."""
        if self._device_meta.pop(mac, None) is None:
            return
        if self._last_unknown_mac == mac:
            self._last_unknown_mac = None
        log.info("Forgot device %s", mac)
        self._save()

    def http_set_trusted(self):
        data = request.get_json()
        self.set_trusted(data["mac"], data["trusted"], data.get("reason"))
        return {"ok": True}

    def http_set_alias(self):
        data = request.get_json()
        self.set_alias(data["mac"], data.get("alias", ""))
        return {"ok": True}

    def http_forget(self):
        data = request.get_json()
        self.forget(data["mac"])
        return {"ok": True}

    def _save(self):
        runtime_state_cache_set(DEVICE_META_KEY, self._device_meta)
