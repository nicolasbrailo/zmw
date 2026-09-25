""" Health of the zigbee2mqtt-like networks a Z2MProxy listens to """
from zzmw_lib.logs import build_logger
log = build_logger("Z2M")

from datetime import datetime, timedelta

import itertools
import os
import signal

# Makes each instance's scheduler job IDs unique, so several instances can share a scheduler
_instance_ids = itertools.count(1)


class Z2MNetworksHealth:
    """
    Tracks whether each network is up:
    * On startup, every network must publish its device list (bridge/devices) within startup_timeout_secs, or the
      process is killed so that it's restarted and tries again.
    * After that, a network that hasn't sent any message in ping_timeout_minutes is reported as possibly dead.

    The owner reports messages with on_message() and device lists with on_devices_published().
    """
    def __init__(self, z2m_topics, scheduler, startup_timeout_secs=3, ping_timeout_minutes=5):
        self._z2m_topics = list(z2m_topics)
        self._scheduler = scheduler
        # Unique (APScheduler rejects duplicate job IDs) and readable, for debugging scheduler problems
        self.health_check_job_id = f"z2m_health_check_{next(_instance_ids)}[{','.join(self._z2m_topics)}]"
        self._ping_timeout_minutes = ping_timeout_minutes
        # Networks that published their device list
        self._discovered = set()
        # Last time each network sent anything, by topic. A network that never sent anything has no entry.
        self._last_msg_t = {}
        self._scheduler.add_job(
            self._startup_check,
            'date',
            run_date=datetime.now() + timedelta(seconds=startup_timeout_secs)
        )

    def on_message(self, z2m_topic):
        """ The network on z2m_topic sent a message (any message) """
        self._last_msg_t[z2m_topic] = datetime.now()

    def on_devices_published(self, z2m_topic):
        """ The network on z2m_topic published its device list """
        self._discovered.add(z2m_topic)

    def missing_networks(self):
        """ Networks that haven't published their device list yet """
        return [t for t in self._z2m_topics if t not in self._discovered]

    def _startup_check(self):
        missing = self.missing_networks()
        if missing:
            # If a network didn't publish its devices, crash so that we try again. This also means the service never
            # got its first discovery callback, since that waits for all networks.
            # We could unsubscribe and subscribe to z2m/bridge/devices, but since this
            # hasn't ever happend it's probably safe to kill and restart instead of retrying
            log.critical("Z2M didn't publish a network on %s. Is Z2M down? "
                         "This can happen if an mqtt message is lost, "
                         "and it's typically benign if a restart of the service fixes the problem.", missing)
            os.kill(os.getpid(), signal.SIGTERM)
            return

        self._scheduler.add_job(
            self._stale_check,
            'interval',
            minutes=self._ping_timeout_minutes,
            id=self.health_check_job_id
        )

    def _stale_check(self):
        """ Single job for all networks: complain about each one that has gone quiet """
        now = datetime.now()
        for z2m_topic in self._z2m_topics:
            # Every network sent at least bridge/devices, or the startup check would have killed the service
            last_msg_t = self._last_msg_t[z2m_topic]
            if now - last_msg_t > timedelta(minutes=self._ping_timeout_minutes):
                log.error("Z2M network on '%s' hasn't sent a message in more than %d minutes, is it alive?",
                          z2m_topic, self._ping_timeout_minutes)
