""" Health of the zigbee2mqtt-like networks a Z2MProxy listens to """
from zzmw_lib.logs import build_logger
log = build_logger("Z2M")

from datetime import datetime, timedelta

import functools
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
    * After that, a network that hasn't sent any message in ping_timeout_minutes is pinged with send_ping(z2m_topic),
      and reported as possibly dead if it still hasn't sent anything ping_reply_timeout_secs later. Sparse networks
      can be quiet for a while, the ping tells a quiet network from a dead one. Without send_ping, a quiet network is
      reported right away.

    The check runs with up to jitter_secs of random delay, so that services sharing a network don't all ping it at
    the same time: the first ping's reply counts as a message for everyone.

    The owner reports messages with on_message() and device lists with on_devices_published().
    """
    def __init__(self, z2m_topics, scheduler, startup_timeout_secs=3, ping_timeout_minutes=5,
                 send_ping=None, ping_reply_timeout_secs=30, jitter_secs=60):
        self._z2m_topics = list(z2m_topics)
        self._scheduler = scheduler
        # Unique (APScheduler rejects duplicate job IDs) and readable, for debugging scheduler problems
        self.health_check_job_id = f"z2m_health_check_{next(_instance_ids)}[{','.join(self._z2m_topics)}]"
        self._ping_timeout_minutes = ping_timeout_minutes
        self._send_ping = send_ping
        self._ping_reply_timeout_secs = ping_reply_timeout_secs
        self._jitter_secs = jitter_secs
        # Networks that published their device list
        self._discovered = set()
        # Last time each network sent anything, by topic. A network that never sent anything has no entry.
        self._last_msg_t = {}
        self._scheduler.add_job(
            self._startup_check,
            'date',
            run_date=datetime.now() + timedelta(seconds=startup_timeout_secs)
        )

    def on_message(self, z2m_topic, subtopic=None):
        """ A message arrived on the network on z2m_topic. Requests to the network (subtopic) are sent by its clients,
        including our own pings, so they don't mean the network is alive. """
        if subtopic is not None and _is_request(subtopic):
            return
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
            jitter=self._jitter_secs,
            id=self.health_check_job_id
        )

    def _stale_check(self):
        """ Single job for all networks: ping (or, without send_ping, complain about) each one that has gone quiet """
        now = datetime.now()
        # Every network sent at least bridge/devices, or the startup check would have killed the service
        quiet = [t for t in self._z2m_topics
                 if now - self._last_msg_t[t] > timedelta(minutes=self._ping_timeout_minutes)]
        if not quiet:
            return

        if self._send_ping is None:
            self._report_dead(quiet, pinged=False)
            return

        for z2m_topic in quiet:
            log.debug("Z2M network on '%s' is quiet, pinging it", z2m_topic)
            self._send_ping(z2m_topic)
        self._scheduler.add_job(
            functools.partial(self._ping_reply_check, quiet, now),
            'date',
            run_date=now + timedelta(seconds=self._ping_reply_timeout_secs)
        )

    def _ping_reply_check(self, pinged, ping_t):
        """ Complain about the pinged networks that haven't sent anything since the ping """
        dead = [t for t in pinged if self._last_msg_t[t] <= ping_t]
        if dead:
            self._report_dead(dead, pinged=True)

    def _report_dead(self, z2m_topics, pinged):
        for z2m_topic in z2m_topics:
            if pinged:
                log.error("Z2M network on '%s' hasn't sent a message in more than %d minutes and didn't answer a "
                          "ping, is it alive?", z2m_topic, self._ping_timeout_minutes)
            else:
                log.error("Z2M network on '%s' hasn't sent a message in more than %d minutes, is it alive?",
                          z2m_topic, self._ping_timeout_minutes)


def _is_request(subtopic):
    """ True for messages that clients send to a network: bridge requests, matter2mqtt's ping, and set/get for
    a device """
    return subtopic.startswith('bridge/request/') or subtopic == 'ping' or \
        subtopic.endswith('/set') or subtopic.endswith('/get')
