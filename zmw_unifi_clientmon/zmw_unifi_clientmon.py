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
from user_device_presence_mon import UserDevicePresenceMon
from unknown_device_mon import UnknownDeviceMon

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
        self._presence_mon = UserDevicePresenceMon(
            cfg.get('device_owners', {}),
            self._on_presence_state_change,
            leave_cooldown_secs=cfg.get('leave_cooldown_secs', 60),
        )
        self._unknown_device_mon = UnknownDeviceMon()
        self._consecutive_failures = 0
        self._MAX_CONSECUTIVE_FAILURES = 3

        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        self._public_url_base = www.register_www_dir(www_path)
        www.serve_url('/clients', lambda: json.dumps(list(self._unifi.current_clients.values()), default=str))
        www.serve_url('/events', lambda: json.dumps(list(self._event_history), default=str))
        www.serve_url('/presence', lambda: json.dumps(self._presence_mon.user_states, default=str))
        www.serve_url('/all_devices', lambda: json.dumps(self._get_all_devices(), default=str))

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
                "user_home": {
                    "description": "A known user arrived home (at least one device connected)",
                    "payload": {"time": "ISO timestamp", "user": "User name", "device_hostname": "Device hostname or MAC"}
                },
                "user_away": {
                    "description": "A known user left (all devices disconnected, after cooldown)",
                    "payload": {"time": "ISO timestamp", "user": "User name", "device_hostname": "Device hostname or MAC"}
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
        self._unknown_device_mon.on_poll(self._unifi.all_clients)

        if joined is None and left is None:
            # First poll — seed presence state from currently connected clients
            for mac, info in self._unifi.current_clients.items():
                self._presence_mon.seed_connected_device(info["hostname"], mac)
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
                self._presence_mon.on_device_event(event_type, info["hostname"], mac)

    def _get_all_devices(self):
        online_macs = set(self._unifi.all_clients.keys())
        known_macs = self._unknown_device_mon.known_macs
        all_macs = online_macs | known_macs
        result = []
        for mac in sorted(all_macs):
            online_info = self._unifi.all_clients.get(mac)
            result.append({
                "hostname": online_info["hostname"] if online_info else mac,
                "mac": mac,
                "ip": online_info["ip"] if online_info else None,
                "online": online_info is not None,
                "known": mac in known_macs,
            })
        return result

    def _on_presence_state_change(self, user, new_state, device_id):
        topic = "user_home" if new_state == "home" else "user_away"
        self.publish_own_svc_message(topic, {
            "time": datetime.now().isoformat(),
            "user": user,
            "device_hostname": device_id,
        })

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
