import json
import os
import pathlib
from flask import abort, request

from zzmw_lib.service_runner import service_runner
from zzmw_lib.zmw_mqtt_service import ZmwMqttService
from zzmw_lib.logs import build_logger
from zz2m.z2mproxy import Z2MProxy
from zz2m.www import Z2Mwebservice

from config_enforcer import ConfigEnforcer
from dispense_tracking import DispenseTracking
from history import DispensingHistory
from notification_manager import NotificationManager
from schedule import DispensingSchedule, validate_schedule_config

log = build_logger("ZmwCatSnackDispenser")

class ZmwCatSnackDispenser(ZmwMqttService):
    def __init__(self, cfg, www, sched):
        super().__init__(cfg, svc_topic="zmw_cat_feeder", scheduler=sched, svc_deps=["ZmwTelegram"])
        self._z2m_cat_feeder_name = cfg["z2m_cat_feeder"]
        self._schedule_tolerance_secs = cfg["schedule_tolerance_secs"]

        # Set up www directory and endpoints
        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        self._public_url_base = www.register_www_dir(www_path)

        self._notifications = NotificationManager(
            cfg, self._z2m_cat_feeder_name, cfg["feeding_schedule"], sched, self.message_svc)

        history = DispensingHistory(self._z2m_cat_feeder_name, history_len=10,
                                         cb_on_dispense=self._notifications.notify_dispense_event)
        schedule = DispensingSchedule(self._z2m_cat_feeder_name, history, self.feed_now,
                                            cfg["feeding_schedule"], cfg["schedule_tolerance_secs"], sched)
        self._dispense_tracking = DispenseTracking(history, schedule)
        self._config_enforcer = ConfigEnforcer(backoff_secs=1, schedule=self._dispense_tracking)

        self._cat_feeder = None

        self._z2m = Z2MProxy(cfg, self, sched,
                             cb_on_z2m_network_discovery=self._on_z2m_network_discovery,
                             cb_is_device_interesting=lambda t: t.name == self._z2m_cat_feeder_name)
        self._z2mw = Z2Mwebservice(www, self._z2m)

        www.serve_url('/feed_now', lambda: self.feed_now(source="User requested via WWW"))
        www.serve_url('/feed_history', self._dispense_tracking.get_history)
        www.serve_url('/feed_schedule', self._dispense_tracking.get_schedule)
        www.serve_url('/save_schedule', self.save_schedule, methods=['PUT'])

    def save_schedule(self):
        try:
            new_schedule = request.get_json()
        except Exception as e:
            return abort(400, description=f"Invalid JSON: {e}")

        if new_schedule is None:
            return abort(400, description="No JSON body provided")

        try:
            validate_schedule_config(new_schedule, self._schedule_tolerance_secs)
        except ValueError as e:
            return abort(400, description=str(e))

        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        config['feeding_schedule'] = new_schedule
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)

        log.info("Schedule saved. Service will restart automatically once changes are detected by the system...")
        return {'status': 'saved'}

    def get_mqtt_description(self):
        return {
            "description": "Manages an Aqara cat food dispenser via Zigbee2MQTT. Handles feeding schedules, monitors dispense events, triggers emergency dispenses on missed feedings, and sends Telegram notifications on success/failure.",
            "meta": self.get_service_meta(),
            "commands": {
                "feed_now": {
                    "description": "Dispense food immediately. Response published on feed_now_reply",
                    "params": {"source": "(optional) Who/what triggered this request", "serving_size": "(optional) Number of portions to dispense"}
                },
                "get_history": {
                    "description": "Request dispensing history. Response published on get_history_reply",
                    "params": {}
                },
                "get_schedule": {
                    "description": "Request the current feeding schedule. Response published on get_schedule_reply",
                    "params": {}
                },
                "get_mqtt_description": {
                    "description": "Request MQTT API description. Response published on get_mqtt_description_reply",
                    "params": {}
                },
            },
            "announcements": {
                "feed_now_reply": {
                    "description": "Result of a feed_now command",
                    "payload": {"status": "'ok' or 'error'", "error": "(only on failure) Error description"}
                },
                "get_history_reply": {
                    "description": "Response to get_history. List of dispensing event objects",
                    "payload": [{"dispense_event_id": "int or null", "time_requested": "ISO timestamp",
                                 "source": "What triggered this (Schedule, Telegram, WWW, etc.)", "portions_dispensed": "int or null",
                                 "weight_dispensed": "int or null", "unit_acknowledged": "bool", "error": "string or null"}]
                },
                "get_schedule_reply": {
                    "description": "Response to get_schedule. List of schedule entry objects",
                    "payload": [{"days": "Day specifier (everyday, workdays, weekend, mon, etc.)", "hour": "0-23", "minute": "0-59", "serving_size": "int"}]
                },
                "get_mqtt_description_reply": {
                    "description": "Response to get_mqtt_description. Full MQTT API description dict",
                    "payload": {}
                },
            }
        }

    def get_service_alerts(self):
        if self._cat_feeder is None:
            return [f"No cat-feeder thing named {self._z2m_cat_feeder_name} found!"]
        return []

    def on_service_came_up(self, service_name):
        if service_name != "ZmwTelegram":
            return
        self.message_svc("ZmwTelegram",
                         "register_command", {'cmd': 'dispensecatsnacks', 'descr': 'Feed the cat'})

    def on_service_received_message(self, subtopic, payload):
        if subtopic.endswith('_reply'):
            return

        match subtopic:
            case "feed_now":
                source = payload.get('source', 'MQTT') if isinstance(payload, dict) else 'MQTT'
                serving_size = payload.get('serving_size') if isinstance(payload, dict) else None
                try:
                    self.feed_now(source=source, serving_size=serving_size)
                    self.publish_own_svc_message("feed_now_reply", {"status": "ok"})
                except Exception as ex:
                    self.publish_own_svc_message("feed_now_reply", {"status": "error", "error": str(ex)})
            case "get_history":
                self.publish_own_svc_message("get_history_reply",
                    self._dispense_tracking.get_history())
            case "get_schedule":
                self.publish_own_svc_message("get_schedule_reply",
                    self._dispense_tracking.get_schedule())
            case "get_mqtt_description":
                self.publish_own_svc_message("get_mqtt_description_reply",
                    self.get_mqtt_description())
            case _:
                log.warning("Ignoring unknown message '%s'", subtopic)

    def on_dep_published_message(self, svc_name, subtopic, payload):  # pylint: disable=unused-argument
        if svc_name == 'ZmwTelegram' and subtopic.startswith("on_command/dispensecatsnacks"):
            self.feed_now(source="Telegram")

    ### Z2M behaviour ###
    def _on_z2m_network_discovery(self, _is_first_discovery, known_things):
        if self._z2m_cat_feeder_name not in known_things:
            log.critical("No cat feeder '%s' found in the network, cat will be angry", self._z2m_cat_feeder_name)

        log.info("Cat feeder '%s' found, this service will manage it", self._z2m_cat_feeder_name)
        self._cat_feeder = known_things[self._z2m_cat_feeder_name]
        self._config_enforcer.ensure_config(self._cat_feeder, correct_if_bad=True)
        self._z2m.broadcast_thing(self._cat_feeder)
        # Set callback after ensuring unit config; messages are delivered async so it's likely we'll be here before
        # any unit has had a chance to reply back through the network, this won't help prevent callback loops
        self._cat_feeder.on_any_change_from_mqtt = self._z2m_thing_bcasting

    def _z2m_thing_bcasting(self, _msg):
        self._dispense_tracking.check_dispensing(self._cat_feeder)
        self._config_enforcer.ensure_config(self._cat_feeder, correct_if_bad=True)
        self._z2m.broadcast_thing(self._cat_feeder)

    def feed_now(self, source="unknown", serving_size=None):
        if not self._dispense_tracking.request_feed_now(source, self._cat_feeder, serving_size):
            return abort(409, description="Can't request food now, another request may be in progress.")
        self._z2m.broadcast_thing(self._cat_feeder)
        return {}

service_runner(ZmwCatSnackDispenser)
