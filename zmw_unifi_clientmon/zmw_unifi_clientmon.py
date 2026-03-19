""" UniFi client monitor: detects when interesting devices join/leave the LAN. """

import json
import os
import pathlib
import signal
import time
from datetime import datetime
from collections import deque

from zzmw_lib.logs import build_logger
from zzmw_lib.service_runner import service_runner
from zzmw_lib.zmw_mqtt_service import ZmwMqttService

import requests.exceptions

from unifi_client import UnifiClient, UnsupportedUnifi, AuthError

log = build_logger("ZmwUnifiClientmon")


class ZmwUnifiClientmon(ZmwMqttService):
    """ Monitor UniFi network for interesting device presence changes. """

    def __init__(self, cfg, www, _sched):
        super().__init__(cfg, "zmw_unifi_clientmon", scheduler=_sched)
        self._unifi = UnifiClient(
            controller=cfg['unifi_controller'],
            username=cfg['unifi_username'],
            password=cfg['unifi_password'],
        )
        self._interesting = set(cfg['interesting_devices'])
        self._poll_interval = cfg['poll_interval_secs']
        self._event_history = deque(maxlen=cfg.get('event_history_len', 100))
        self._consecutive_failures = 0
        self._MAX_CONSECUTIVE_FAILURES = 3

        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        self._public_url_base = www.register_www_dir(www_path)
        www.serve_url('/clients', lambda: json.dumps(list(self._unifi.current_clients.values()), default=str))
        www.serve_url('/events', lambda: json.dumps(list(self._event_history), default=str))

        _sched.add_job(self._poll_clients, 'interval', seconds=self._poll_interval,
                       next_run_time=datetime.now())

    def get_mqtt_description(self):
        return {
            "description": "Monitors UniFi network, announces when devices join/leave.",
            "meta": self.get_service_meta(),
            "commands": {
                "ls": {
                    "description": "List currently connected interesting clients",
                    "params": {}
                },
                "get_history": {
                    "description": "Event history (joins/leaves)",
                    "params": {}
                },
            },
            "announcements": {
                "client_joined": {
                    "description": "An interesting device connected to the network",
                    "params": {
                        "time": "ISO timestamp",
                        "event": "joined",
                        "hostname": "Device hostname",
                        "mac": "MAC address",
                        "ip": "IP address",
                    }
                },
                "client_left": {
                    "description": "An interesting device disconnected from the network",
                    "params": {
                        "time": "ISO timestamp",
                        "event": "left",
                        "hostname": "Device hostname",
                        "mac": "MAC address",
                        "ip": "Last known IP address",
                    }
                },
                "ls_reply": {
                    "description": "List of connected interesting clients",
                    "payload": [{"hostname": "str", "mac": "str", "ip": "str"}]
                },
                "get_history_reply": {
                    "description": "Event history",
                    "payload": [{"time": "ISO timestamp", "event": "joined|left", "hostname": "str", "mac": "str", "ip": "str"}]
                },
                "get_mqtt_description_reply": {
                    "description": "Service description",
                },
            }
        }

    def _poll_clients(self):
        try:
            joined, left, _current = self._unifi.poll_changes(self._interesting)
        except (UnsupportedUnifi, AuthError, ConnectionError,
                requests.exceptions.RequestException, json.JSONDecodeError):
            self._consecutive_failures += 1
            log.error("Failed to poll UniFi controller (%d/%d)",
                      self._consecutive_failures, self._MAX_CONSECUTIVE_FAILURES, exc_info=True)
            if self._consecutive_failures >= self._MAX_CONSECUTIVE_FAILURES:
                log.error("Too many consecutive failures, terminating service.")
                os.kill(os.getpid(), signal.SIGTERM)
                time.sleep(3)
            return

        self._consecutive_failures = 0

        if joined is None and left is None:
            # No changes
            return

        for event_type, clients in (("joined", joined), ("left", left)):
            for mac, info in clients.items():
                event = {
                    "time": datetime.now().isoformat(),
                    "event": event_type,
                    "hostname": info["hostname"],
                    "mac": mac,
                    "ip": info["ip"],
                }
                self._event_history.append(event)
                log.info("%s: %s (%s) %s", event_type.upper(), info["hostname"], mac, info["ip"])
                self.publish_own_svc_message(f"client_{event_type}", event)

    def on_service_received_message(self, subtopic, payload):
        if subtopic.endswith('_reply'):
            return

        match subtopic:
            case "ls":
                self.publish_own_svc_message("ls_reply",
                    list(self._unifi.current_clients.values()))
            case "get_history":
                self.publish_own_svc_message("get_history_reply",
                    list(self._event_history))
            case "get_mqtt_description":
                self.publish_own_svc_message("get_mqtt_description_reply",
                    self.get_mqtt_description())
            case _:
                pass


service_runner(ZmwUnifiClientmon)
