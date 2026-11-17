""" Local-only Roomba control, via roombapy (local MQTT on the robot, no cloud) """
import asyncio
import os
import pathlib
import threading

from zzmw_lib.zmw_mqtt_service import ZmwMqttService
from zzmw_lib.mqtt_request_reply import MqttRequestReply
from zzmw_lib.logs import build_logger
from zzmw_lib.service_runner import service_runner

from roomba import Discovery, Roomba, SETTINGS, get_discovery_mechanism
from mission_monitor import MissionMonitor

log = build_logger("ZmwSucks")

# Commands exposed over MQTT and www. All take a robot alias, and reply on <cmd>_reply
_COMMANDS = {
    "start": "Start cleaning (or resume, if paused)",
    "pause": "Pause cleaning",
    "dock": "Stop cleaning, and go back to the dock",
    "find": "Play the locate chime, without moving",
}

# A robot that can't be reached for this long raises a service alert
_DISCONNECTED_ALERT_SECS = 30 * 60


class ZmwSucks(ZmwMqttService):
    """ ZmwService for a set of Roombas """
    def __init__(self, cfg, www, sched):
        roomba_cfgs = [r for r in cfg["roombas"] if not r.get("ignore", False)]
        svc_deps = ['ZmwTelegram']
        if any(get_discovery_mechanism(r) == "unifi" for r in roomba_cfgs):
            svc_deps.append('ZmwUnifiClientmon')
        super().__init__(cfg, "zmw_sucks", scheduler=sched, svc_deps=svc_deps)
        self._rr = MqttRequestReply(self.message_svc)

        # roombapy is asyncio only, run it in its own loop
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._loop_thread.start()
        discovery = Discovery()

        self._roombas = {}
        for dev_cfg in cfg["roombas"]:
            if dev_cfg.get("ignore", False):
                log.info("Ignoring %s, it's marked as ignored in config", dev_cfg.get("alias"))
                continue
            if dev_cfg["alias"] in self._roombas:
                raise ValueError(f"Duplicated Roomba alias '{dev_cfg['alias']}' in config")
            self._roombas[dev_cfg["alias"]] = Roomba(self._loop, discovery, dev_cfg, self._on_roomba_state_change,
                                                     self._find_ip_in_unifi)

        self._monitor = MissionMonitor(sched, lambda: list(self._roombas.values()), self._send_telegram,
                                       notify_on_schedule_success=cfg.get("notify_on_schedule_success", False),
                                       notify_on_schedule_failure=cfg.get("notify_on_schedule_failure", True))

        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        www.register_www_dir(www_path)
        www.serve_url('/get_state', self._get_state)
        for cmd in _COMMANDS:
            www.serve_url(f'/{cmd}/<alias>', lambda alias, cmd=cmd: self._send_command(cmd, alias),
                          methods=['PUT'])
        www.serve_url('/set_setting/<alias>/<setting>/<value>', self._set_setting, methods=['PUT'])
        www.serve_url('/get_raw_state/<alias>', self._get_raw_state)

    def _send_telegram(self, msg):
        try:
            self.message_svc("ZmwTelegram", "send_text", {'msg': msg})
        except RuntimeError as ex:
            log.warning("Can't send Telegram notification '%s': %s", msg, ex)

    def _find_ip_in_unifi(self, blid):
        """ IP of the robot with this BLID, as known by ZmwUnifiClientmon, or None. Robots are found by hostname
        (Roomba-<blid> or iRobot-<blid>). Blocks while waiting for a reply, don't call from the MQTT thread. """
        try:
            clients = self._rr.request("ZmwUnifiClientmon", "get_all_clients", {}, "get_all_clients_reply",
                                       timeout=5)
        except RuntimeError as ex:
            # ZmwUnifiClientmon isn't up (yet). The robot shows as not found meanwhile.
            log.debug("Can't ask ZmwUnifiClientmon for %s: %s", blid, ex)
            return None
        suffix = f"-{blid}".lower()
        for client in clients or []:
            ip = client.get("ip")
            if client.get("hostname", "").lower().endswith(suffix) and ip and ip != "(unknown)":
                return ip
        return None

    def get_service_alerts(self):
        alerts = []
        for alias, r in self._roombas.items():
            if r.auth_rejected:
                alerts.append(f"{alias} rejected its password")
                continue
            if r.not_found:
                alerts.append(f"{alias} not found on network")
                continue
            state = r.get_state()
            if not state["connected"]:
                mins = int(r.disconnected_for_secs() / 60)
                if mins * 60 >= _DISCONNECTED_ALERT_SECS:
                    alerts.append(f"{alias} not connected for {mins} minutes")
                continue
            if state["bin_full"]:
                alerts.append(f"{alias} bin is full")
            if state["error"]:
                alerts.append(f"{alias} error: {state['error']}")
            if state["phase"] == "stuck":
                alerts.append(f"{alias} is stuck")
        return alerts + self._monitor.get_alerts()

    def _get_raw_state(self, alias):
        if alias not in self._roombas:
            return {"alias": alias, "status": "unknown_device"}
        return self._roombas[alias].get_raw_state()

    def _on_roomba_state_change(self, alias, state):
        self.publish_own_svc_message(f"{alias}/state", state)

    def _get_state(self):
        return {alias: r.get_state() for alias, r in self._roombas.items()}

    def _send_command(self, cmd, alias):
        if alias not in self._roombas:
            log.warning("Requested %s for unknown robot '%s'", cmd, alias)
            return {"alias": alias, "status": "unknown_device"}
        return self._roombas[alias].send_command(cmd)

    def _set_setting(self, alias, setting, value):
        if alias not in self._roombas:
            log.warning("Requested %s=%s for unknown robot '%s'", setting, value, alias)
            return {"alias": alias, "status": "unknown_device"}
        return self._roombas[alias].set_setting(setting, str(value).lower())

    def stop(self):
        for r in self._roombas.values():
            r.disconnect()
        self._loop.call_soon_threadsafe(self._loop.stop)
        super().stop()

    def get_mqtt_description(self):
        return {
            "description": "Local-only Roomba control (robot's local MQTT API via roombapy, no cloud). "
                           "Checks scheduled runs start, and monitors missions: problems are sent over Telegram.",
            "meta": self.get_service_meta(),
            # MQTT data flow; feeds the map in the top-level README (scripts/build_mqtt_map.py).
            # Talks to the robots' own MQTT servers, and publishes to its own topic (and Telegram's). Asks
            # ZmwUnifiClientmon for robot IPs, if any robot uses the unifi discovery_mechanism.
            "reads_mqtt_topic": ["zmw_unifi_clientmon"],
            "writes_mqtt_topic": ["zmw_unifi_clientmon"],
            "commands": {
                "get_state": {
                    "description": "Current state of all robots. Response on get_state_reply",
                    "params": {}
                },
                **{cmd: {
                    "description": f"{desc}. Response on {cmd}_reply",
                    "params": {"alias": "Robot alias, as in config"}
                } for cmd, desc in _COMMANDS.items()},
                "set_setting": {
                    "description": "Change a robot setting. Response on set_setting_reply",
                    "params": {
                        "alias": "Robot alias, as in config",
                        "setting": "/".join(SETTINGS),
                        "value": "; ".join(f"{s}: {'/'.join(v)}" for s, v in SETTINGS.items()),
                    }
                },
                "get_raw_state": {
                    "description": "Debug: everything a robot reports, unparsed. Response on get_raw_state_reply",
                    "params": {"alias": "Robot alias, as in config"}
                },
                "get_mqtt_description": {
                    "description": "Service description",
                    "params": {}
                },
            },
            "announcements": {
                "<alias>/state": {
                    "description": "Published when a robot's state changes",
                    "payload": {
                        "alias": "Robot alias, as in config",
                        "connected": "Local connection to robot is up. If false, no other fields are present",
                        "ip": "Robot IP (discovered, unless fixed in config)",
                        "robot_name": "Name the robot reports for itself",
                        "state": "Derived mission state (eg 'Charging', 'Running')",
                        "phase": "Raw cleanMissionStatus phase",
                        "battery_pct": "Battery %",
                        "bin_full": "Bin is full",
                        "error_code": "Error code, or null",
                        "error": "Error message, or null",
                        "mission": {
                            "id": "Mission ID",
                            "cycle": "Mission type (eg 'clean', 'none')",
                            "initiator": "Who started it (eg 'localApp', 'schedule', 'rmtApp')",
                            "start_time": "Mission start, epoch secs",
                            "minutes": "Mission duration so far",
                            "sqft": "Area cleaned so far",
                            "recharge_minutes": "Minutes until recharge completes, mid mission",
                            "expire_minutes": "Minutes until the mission is abandoned, if paused",
                        },
                        "lifetime": {
                            "runtime_hours": "Total runtime, hours part",
                            "runtime_minutes": "Total runtime, minutes part",
                            "sqft": "Total area cleaned",
                            "missions": "Missions started",
                            "missions_ok": "Missions completed",
                            "missions_failed": "Missions failed",
                            "missions_cancelled": "Missions cancelled",
                            "avg_mission_minutes": "Average mission duration",
                            "stuck_count": "Times the robot got stuck",
                        },
                        "battery": {
                            "charge_cycles": "Battery charge cycles",
                            "est_capacity_mah": "Estimated battery capacity, mAh",
                            "manufacture_date": "Battery manufacture date",
                        },
                        "settings": {
                            "passes": "auto/one/two",
                            "bin_pause": "Stop cleaning when the bin is full",
                            "child_lock": "Robot buttons disabled",
                        },
                        "schedule": {
                            "paused": "Schedule is on hold",
                            "timezone": "Robot timezone, schedule times are local to it",
                            "entries": [{"enabled": "Entry is active", "days": ["Mon", "..."],
                                         "day_nums": "Days, 0 = Sunday", "hour": "Start hour",
                                         "min": "Start minute", "command": "Usually 'start'"}],
                        },
                        "wifi": {"rssi": "Signal strength, dBm", "snr": "Signal to noise ratio"},
                        "position_supported": "Robot answers position requests (null until known)",
                        "position": "Last known position, or null: {x_m, y_m, theta_rad}, origin at the dock",
                    }
                },
                "get_raw_state_reply": {
                    "description": "Everything the robot reports",
                    "payload": {"alias": "Robot alias", "connected": "Connection is up", "reported": {}}
                },
                "get_state_reply": {
                    "description": "Map of robot alias to state",
                    "payload": "See `<alias>/state`",
                },
                **{f"{cmd}_reply": {
                    "description": f"{cmd} sent to robot (or failed to)",
                    "payload": {"alias": "Robot alias", "status": "ok/not_connected/unknown_device"}
                } for cmd in _COMMANDS},
                "set_setting_reply": {
                    "description": "Setting sent to robot (or failed to)",
                    "payload": {"alias": "Robot alias",
                                "status": "ok/not_connected/unknown_device/unknown_setting/bad_value"}
                },
                "get_mqtt_description_reply": {
                    "description": "Service description",
                    "payload": {"commands": {}, "announcements": {}}
                },
            },
            "known_roombas": list(self._roombas.keys()),
        }

    def on_service_received_message(self, subtopic, payload):
        if subtopic.endswith('_reply'):
            return

        match subtopic:
            case "get_state":
                self.publish_own_svc_message("get_state_reply", self._get_state())
            case cmd if cmd in _COMMANDS:
                self.publish_own_svc_message(f"{cmd}_reply", self._send_command(cmd, payload.get('alias', '')))
            case "set_setting":
                self.publish_own_svc_message("set_setting_reply", self._set_setting(
                    payload.get('alias', ''), payload.get('setting', ''), payload.get('value', '')))
            case "get_raw_state":
                self.publish_own_svc_message("get_raw_state_reply", self._get_raw_state(payload.get('alias', '')))
            case "get_mqtt_description":
                self.publish_own_svc_message("get_mqtt_description_reply",
                    self.get_mqtt_description())
            case _:
                # Ignore echo (eg our own state announcements)
                pass

    def on_dep_published_message(self, svc_name, subtopic, payload):
        # Only ZmwUnifiClientmon replies are interesting; we only send to ZmwTelegram
        self._rr.on_reply(subtopic, payload)

service_runner(ZmwSucks)
