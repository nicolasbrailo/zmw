"""Deletes the retained records of homeboards that are gone for good.

A homeboard that goes away leaves its retained records on the broker, and the
board would stay listed forever. Once a night, the janitor deletes them for
boards that are gone, and for prefixes whose availability record can't be parsed:
those can never become a usable homeboard.
"""

import time

from zzmw_lib.logs import build_logger

log = build_logger("HomeboardJanitor")

# A homeboard that's been offline (last boot older than this) is presumed gone:
# overlays stop being pushed to it, and the janitor deletes its retained records.
_OFFLINE_GRACE_SECS = 3 * 24 * 3600


def is_gone(hb, now):
    """Whether a homeboard is offline and last booted over the grace period ago."""
    if hb.get('state') != 'offline':
        return False
    host_info = hb.get('host_info') or {}
    started_at = host_info.get('started_at')
    if not isinstance(started_at, (int, float)):
        started_at = 0
    return now - started_at > _OFFLINE_GRACE_SECS


class HomeboardJanitor:
    """Runs every night on `sched`, clearing records through a HomeboardMqtt."""

    _RUN_HOUR = 3

    def __init__(self, hb_mqtt, sched):
        self._hb_mqtt = hb_mqtt
        sched.add_job(self.run, trigger='cron', hour=self._RUN_HOUR, minute=0)

    def run(self):
        cleared = 0
        for hb_id in self._hb_mqtt.list_bad_availability():
            log.info("Clearing unparseable retained records of '%s'", hb_id)
            self._hb_mqtt.clear_retained_state(hb_id)
            cleared += 1
        now = time.time()
        for hb in self._hb_mqtt.list_homeboards():
            if not is_gone(hb, now):
                continue
            log.info("Clearing retained records of '%s', offline since %s",
                     hb['id'], (hb.get('host_info') or {}).get('started_at'))
            self._hb_mqtt.clear_retained_state(hb['id'])
            cleared += 1
        log.info("Cleared %d homeboard(s)", cleared)
