from .zmw_mqtt_base import ZmwMqttBase
from abc import abstractmethod
from .logs import build_logger

import json
import logging
import random

from datetime import datetime, timedelta

log = build_logger("ZmwMqttService", logging.INFO)
#log = build_logger("ZmwMqttService")

class ZmwMqttService(ZmwMqttBase):
    """ An ZmwMqttService listens for commands and will send replies over mqtt. It may have dependencies to other services. """

    def __init__(self, cfg, svc_topic, scheduler, svc_deps=[]):
        super().__init__(cfg)
        self._svc_topic = svc_topic
        if self._svc_topic is not None:
            self.subscribe_with_cb(self._svc_topic, self.on_service_received_message)

        if not all(isinstance(d, str) for d in svc_deps):
            raise TypeError("Unknown service dependency format '%s'", str(svc_deps))
        self._svc_deps = svc_deps

        self._known_services = {}
        self._first_start_ran = False
        self._all_deps_alive = False
        # Add a random (prime) delay to pings, to minimize chances we're syncing pings with other services
        random_delay = random.choice([2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59])
        self._deps_ping = 3 * 60 + random_delay
        # Number of missed pings before marking a dep as down
        self._dep_stale_timeout = self._deps_ping * 3
        self.subscribe_with_cb(self._global_svc_discovery_announce_topic,
                               lambda _t, payload: self._on_service_updown(True, payload))
        self.subscribe_with_cb(self._global_svc_discovery_leaving_topic,
                               lambda _t, payload: self._on_service_updown(False, payload))

        self._svc_sched = scheduler

        self._start_monitoring_deps()

    def _start_monitoring_deps(self):
        # Give things time to settle and connect, then ping all services
        self._svc_sched.add_job(
                lambda: self.broadcast(self._global_svc_discovery_ping_topic, {}),
                trigger='date',
                run_date=datetime.now() + timedelta(seconds=1))

        # Run periodically a check for alive deps, after the first ping
        def _check_deps_alive_first_run():
            deps = self.get_missing_deps()
            if len(deps) != 0:
                self.on_startup_fail_missing_deps(deps)
            self._check_deps_job = self._svc_sched.add_job(
                func=self._check_deps_alive,
                trigger="interval",
                seconds=self._deps_ping)
        self._svc_sched.add_job(
                _check_deps_alive_first_run,
                trigger='date',
                run_date=datetime.now() + timedelta(seconds=5))

    def _check_deps_alive(self):
        """
        Check if service dependencies are still responding.

        Marks services as stale if they haven't sent pings within the timeout period.
        Called periodically by the scheduler. Also broadcasts a ping request to
        trigger responses from all services.
        """
        # Mark deps without pings for a long time as stale
        stales = []
        now = datetime.now()
        oldest_dep = datetime.now()
        for name, info in self._known_services.items():
            last_seen = info.get('last_seen')
            if not last_seen or ((now - last_seen) > timedelta(seconds=self._dep_stale_timeout)):
                stales.append(name)
            if last_seen is not None and oldest_dep > last_seen:
                oldest_dep = last_seen
        for name in stales:
            self.on_dep_became_stale(name)
            self._known_services.pop(name, None)

        # If there is a dep we haven't seen for one ping time, ping the registry
        if (now - oldest_dep) > timedelta(seconds=self._deps_ping):
            log.debug("Pinging global service discovery")
            self.broadcast(self._global_svc_discovery_ping_topic, {})

    def _on_service_updown(self, up, svc_meta):
        if svc_meta is None:
            log.error("A service is responding to pings, but doesn't broadcast metadata")
            return
        if 'name' not in svc_meta:
            log.error('Ignoring service up notification with bad format, missing service name. Message: %s', str(svc_meta))
            return
        if svc_meta['name'] not in self._svc_deps:
            # We don't care about this service
            log.debug('Uninteresting service "%s" is %s', svc_meta['name'], "up" if up else "down")
            return
        if up:
            name = svc_meta['name']
            if 'mqtt_topic' not in svc_meta:
                # Returning here will also mark the dependency as down
                log.error('Required service "%s" is up, but it doesn\'t have an MQTT topic. Won\'t receive messages from this service.', name)
                return

            if name in self._known_services and self._known_services[name]['mqtt_topic'] == svc_meta['mqtt_topic']:
                self._known_services[name]['last_seen'] = datetime.now()
                log.debug('Ping from service dep %s, mark as not stale', name)
                self.on_service_announced_meta(name, svc_meta)
                return

            if name in self._known_services and self._known_services[name]['mqtt_topic'] != svc_meta['mqtt_topic']:
                log.warning("Service %s changed it's mqtt_topic from '%s' to '%s'. Will resubscribe, but weird things may happen",
                            name, self._known_services[name]['mqtt_topic'], svc_meta['mqtt_topic'])
                # Fallthrough: follow the normal subscription logic

            if svc_meta['mqtt_topic'] is None:
                log.debug('Dependency "%s" is now running, but doesn\'t publish to MQTT.', name)
            else:
                topic = f"{svc_meta['mqtt_topic']}/#"
                log.info('Dependency "%s" is now running, subscribing to "%s"', name, topic)
                self.subscribe_with_cb(topic,
                                       lambda subtopic, payload: self.on_dep_published_message(name, subtopic, payload))

            svc_just_came_up = name not in self._known_services
            self._known_services[name] = svc_meta
            self._known_services[name]['last_seen'] = datetime.now()
            if svc_just_came_up:
                self.on_service_came_up(name)
            else:
                self.on_service_announced_meta(name, svc_meta)
        else:
            log.info('Dependency "%s" is now down', svc_meta['name'])
            self._known_services.pop(svc_meta['name'], None)

        missing_svcs = self.get_missing_deps()
        now_healthy = (len(missing_svcs) == 0)
        healthy_changed = (now_healthy != self._all_deps_alive)
        if not healthy_changed:
            return
        self._all_deps_alive = now_healthy
        if self._all_deps_alive:
            if not self._first_start_ran:
                self._first_start_ran = True
                self.on_all_service_deps_running()
        else:
            self.on_service_deps_missing(missing_svcs)

    def on_dep_became_stale(self, name):
        """
        Called when a service dependency hasn't been seen for too long.

        Override this method to handle stale dependencies. Default implementation
        logs an error.

        Args:
            name: Name of the service that became stale
        """
        log.error("No pings from %s in over %d seconds, marking dep as down", name, self._dep_stale_timeout)

    def on_startup_fail_missing_deps(self, deps):
        """
        Called during startup if required dependencies are not running.

        Override this method to handle startup failures. Default implementation
        logs an error.

        Args:
            deps: List of missing service names
        """
        log.error("Service missing deps %s", deps)

    def on_all_service_deps_running(self):
        """
        Called when all required service dependencies are running.

        Override this method to perform initialization that requires all
        dependencies. Default implementation logs a debug message.
        """
        log.debug("All monitored deps are alive, service healthy")

    def on_service_deps_missing(self, deps):
        """
        Called when some required dependencies go missing after startup.

        Override this method to handle dependency failures. Default implementation
        logs a warning.

        Args:
            deps: List of missing service names
        """
        log.warning("Some monitored deps are missing, service unhealthy %s", str(deps))

    def on_service_came_up(self, service_name):
        """ Let user take an action on level up, but replies may not work yet. Replies rely on
        subscriptions being setup, and when a service cames up we're only guaranteed to have started
        the subscription process, but the subscription is not guaranteed to have completed """
        log.info("Service dep %s is now running", service_name)

    def on_service_announced_meta(self, name, svc_meta):
        """ Called any time a service announces metadata. May or may not contain a change to metadata. """
        pass

    def get_service_mqtt_topic(self):
        return self._svc_topic

    def get_known_services(self):
        """ List of known and alive services """
        return self._known_services

    def get_missing_deps(self):
        """
        Get list of required dependencies that are not currently running.
        """
        return [dep for dep in self._svc_deps if not dep in self._known_services]

    def publish_own_svc_message(self, topic, msg):
        """ This service is replying to a request, by publishing to its own channel. """
        if self._svc_topic is None:
            raise ValueError("This service has no mqtt topic, it can't publish messages")
        self.broadcast(f'{self._svc_topic}/{topic}', msg)

    @abstractmethod
    def on_service_received_message(self, subtopic, payload):
        """ User must implement. This service received a message """
        pass

    def on_dep_published_message(self, svc_name, subtopic, payload):
        log.error("Service received an unexpected message from %s: %s", svc_name, subtopic)

    def message_svc(self, service, subtopic, payload):
        """
        Send a message to a known service via MQTT.

        Args:
            service: Name of the service to message (must be in dependencies)
            subtopic: Subtopic to append to service's base topic (e.g., "command")
            payload: Python object to JSON-encode and send

        Raises:
            RuntimeError: If service is unknown or doesn't have an mqtt_topic

        Example:
            self.message_svc("ZmwTelegram", "send_text", {"msg": "Hello"})
            # Publishes to: mqtt_telegram/send_text
        """
        if service not in self._known_services:
            raise RuntimeError(f"Unknown service {service}")
        topic = self._known_services[service]['mqtt_topic']
        if topic is None:
            raise RuntimeError(f"Service {service} doesn't have an mqtt_topic, it can't be messaged")
        self.broadcast(f"{topic}/{subtopic}", payload)


class ZmwMqttServiceNoCommands(ZmwMqttService):
    def __init__(self, cfg, scheduler, svc_deps=[]):
        super().__init__(cfg, svc_topic=None, scheduler=scheduler, svc_deps=svc_deps)

    def on_service_received_message(self, subtopic, payload):
        log.error("Unexpected message %s %s", subtopic, payload)
        raise AttributeError(f"Unexpected message {subtopic}")

    def on_dep_published_message(self, svc_name, subtopic, msg):
        if svc_name in self._known_services:
            # Responses from a dep, ignore
            return
        log.error("Unexpected message %s %s", subtopic, msg)
        raise AttributeError(f"Unexpected message {subtopic}")


