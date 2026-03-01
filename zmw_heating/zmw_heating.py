""" Heating manager. Controls a simple on/off relay that powers a boiler. """
import json
import os
import signal
import time
import pathlib
from collections import deque
from datetime import datetime, timedelta

from zzmw_lib.zmw_mqtt_service import ZmwMqttService
from zzmw_lib.service_runner import service_runner
from zzmw_lib.logs import build_logger
from zzmw_lib.z2m.z2mproxy import Z2MProxy
from zzmw_lib.z2m.thing import create_virtual_thing

from rules import create_rules_from_config
from schedule_builder import ScheduleBuilder
from schedule import ScheduleSlot

log = build_logger("ZmwHeating")

class ZmwHeating(ZmwMqttService):
    """ Service to control an on/off relay that operates a boiler """
    def __init__(self, cfg, www, sched):
        super().__init__(cfg, "zmw_heating", scheduler=sched, svc_deps=['ZmwTelegram'])

        self._z2m_boiler_name = cfg['zigbee_boiler_name']
        self._rules = create_rules_from_config(cfg['rules'])
        self._cfg_rules = cfg['rules']

        self._boiler = None
        self._pending_state = None
        self._off_val = None
        self._on_val = None
        self._curr_val = None
        self._boiler_state_history = deque(maxlen=30)
        self._sched = sched

        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        self._public_url_base = www.register_www_dir(www_path)

        self.schedule = ScheduleBuilder(self._on_boiler_state_should_change, cfg['schedule_persist_file'], self._rules)
        self._schedule_tick_interval_secs = 60 * 3

        www.serve_url('/svc_state', self.svc_state)
        www.serve_url('/get_cfg_rules', lambda: cfg['rules'])
        www.serve_url('/active_schedule', self.schedule.active().as_jsonifyable_dict)
        www.url_cb_ret_none('/boost=<hours>', self.schedule.active().boost)
        www.url_cb_ret_none('/off_now', self.schedule.active().off_now)
        www.url_cb_ret_none('/slot_toggle=<slot_nm>', lambda slot_nm: self.schedule.active().toggle_slot_by_name(slot_nm, reason="Set by web UI"))
        www.url_cb_ret_none('/template_slot_set=<vs>', lambda vs: self.schedule.set_slot(*vs.split(',')))
        www.url_cb_ret_none('/template_apply', self.schedule.apply_template_to_today)
        www.url_cb_ret_none('/template_reset=<reset_state>', self.schedule.reset_template)
        www.serve_url('/template_schedule', self.schedule.as_json)

        wanted_things = set()
        wanted_things.add(self._z2m_boiler_name)
        for r in self._rules:
            for s in r.get_monitored_sensors().keys():
                wanted_things.add(s)

        self._z2m = Z2MProxy(cfg, self, sched,
                             cb_on_z2m_network_discovery=self._on_z2m_network_discovery,
                             cb_is_device_interesting=lambda t: t.name in wanted_things)
        # Register for updates on weather
        self._z2m.register_virtual_thing(create_virtual_thing(
            name="Weather",
            description="Outside weather from Open-Meteo",
            thing_type="sensor",
            manufacturer="Open-Meteo"
        ))


    def get_service_alerts(self):
        if self._boiler is None:
            return [f"Boiler '{self._z2m_boiler_name}' not found in the network yet"]
        return []

    def get_mqtt_description(self):
        return {
            "description": "Manages heating via a boiler with a Zigbee on/off relay. Has a schedule with on/off overrides, temperature-based rules, and Telegram integration",
            "meta": self.get_service_meta(),
            "commands": {
                "svc_state": {
                    "description": "Service state (schedule, boiler, sensors). Response on svc_state_reply",
                    "params": {}
                },
                "get_cfg_rules": {
                    "description": "Get heating rules. Response on get_cfg_rules_reply",
                    "params": {}
                },
                "active_schedule": {
                    "description": "Request today's schedule. Response on active_schedule_reply",
                    "params": {}
                },
                "boost": {
                    "description": "Turn heating on for N hours",
                    "params": {"hours?": "Number of hours to boost (1-12)"}
                },
                "off_now": {
                    "description": "Force heating off",
                    "params": {}
                },
                "slot_toggle": {
                    "description": "Toggle a schedule slot on/off by time name",
                    "params": {"slot_nm": "Slot time in HH:MM format", "reason?": "Reason to turn on/off"}
                },
                "get_mqtt_description": {
                    "description": "Service description",
                    "params": {}
                },
            },
            "announcements": {
                "svc_state_reply": {
                    "description": "Current schedule, boiler state, sensor readings",
                    "payload": {"active_schedule": "List of schedule slots",
                                "allow_on": "Current slot allow_on policy",
                                "mqtt_thing_reports_on": "Boiler relay state value",
                                "boiler_state_history": "Recent state changes",
                                "monitoring_sensors": "Sensor name to current value map"}
                },
                "get_cfg_rules_reply": {
                    "description": "Configured temp-based rules",
                    "payload": "List of rule config objects"
                },
                "active_schedule_reply": {
                    "description": "Today's schedule starting from current slot",
                    "payload": [{"hour": "int", "minute": "int", "allow_on": "Always|Never|Rule", "request_on": "bool", "reason": "str"}]
                },
                "get_mqtt_description_reply": {
                    "description": "Service description",
                    "payload": "This object"
                },
            }
        }

    def on_service_received_message(self, subtopic, payload):
        if subtopic.endswith('_reply'):
            return

        match subtopic:
            case "svc_state":
                self.publish_own_svc_message("svc_state_reply",
                    self.svc_state())
            case "get_cfg_rules":
                self.publish_own_svc_message("get_cfg_rules_reply",
                    self._cfg_rules)
            case "active_schedule":
                self.publish_own_svc_message("active_schedule_reply",
                    self.schedule.active().as_jsonifyable_dict())
            case "boost":
                hours = payload.get('hours', 1) if isinstance(payload, dict) else 1
                self.schedule.active().boost(hours)
            case "off_now":
                self.schedule.active().off_now()
            case "slot_toggle":
                if not isinstance(payload, dict) or 'slot_nm' not in payload:
                    log.error("slot_toggle requires 'slot_nm' param, got: %s", payload)
                    return
                self.schedule.active().toggle_slot_by_name(payload['slot_nm'], reason=payload.get("reason", "Set by MQTT"))
            case "get_mqtt_description":
                self.publish_own_svc_message("get_mqtt_description_reply",
                    self.get_mqtt_description())
            case _:
                log.warning("Ignoring unknown message '%s'", subtopic)

    def svc_state(self):
        """Return current service state as dict."""
        tsched = self.schedule.active().as_jsonifyable_dict()
        sensors = {}
        for r in self._rules:
            sensors.update(r.get_monitored_sensors())
        return {
            "active_schedule": tsched,
            "allow_on": tsched[0]['allow_on'],
            "mqtt_thing_reports_on": self._curr_val,
            "boiler_state_history": list(self._boiler_state_history),
            "monitoring_sensors": sensors,
        }

    def on_service_came_up(self, service_name):
        if service_name == "ZmwTelegram":
            self.message_svc("ZmwTelegram", "register_command",
                             {'cmd': 'tengofrio',
                              'descr': 'Heating boost'})

    def on_dep_published_message(self, svc_name, subtopic, msg):
        log.debug("%s.%s: %s", svc_name, subtopic, msg)
        match svc_name:
            case 'ZmwTelegram':
                if subtopic.startswith("on_command/tengofrio"):
                    self.schedule.active().boost(1)

    def _on_z2m_network_discovery(self, _is_first_discovery, known_things):
        if self._boiler is not None:
            if self._z2m_boiler_name in known_things:
                # z2m published network update, everything is fine
                # (sensors may be gone though, TODO XXX propagate validation to rules sensors)
                return
            log.critical(
                "MQTT network published update, boiler %s is now gone. Will crash.",
                self._z2m_boiler_name)
            self._boiler = None
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(1)
            log.critical("Sent SIGTERM, if you're seeing this something is broken...")
            return

        log.info("Z2M network discovered, there are %d things: %s", len(known_things), list(known_things.keys()))
        if self._z2m_boiler_name not in known_things:
            log.critical("No boiler %s found", self._z2m_boiler_name)
            return

        thing = known_things[self._z2m_boiler_name]
        if 'state' not in thing.actions:
            log.critical('Thing %s has no action "state", required for boiler control', thing.name)
            return

        if thing.actions['state'].value.meta['type'] != 'binary':
            log.critical("Thing %s action 'state' isn't binary, can't use it for a boiler", thing.name)
            return

        try:
            self._off_val = thing.actions['state'].value.meta['value_off']
            self._on_val = thing.actions['state'].value.meta['value_on']
        except KeyError:
            log.critical(
                "Boiler doesn't describe on and off values, "
                "don't know how to use it. Will assume True/False works.")
            return

        log.info("Discovered boiler %s, run startup in a few seconds...", thing.name)
        self._sched.add_job(func=lambda: self._on_boiler_discovered(thing),
                           trigger="date", run_date=datetime.now() + timedelta(seconds=3))

    def _on_boiler_discovered(self, thing):
        self._boiler = thing

        # If a rule fails to setup (eg sensor is missing) complain but continue:
        # the rules should survive and ignore null sensors, and the
        # system can still work under schedule if there are no sensors available
        if not all(r.set_z2m(self._z2m) for r in self._rules):
            log.critical(
                "Some rules failed to startup, heating system may not work as expected")

        for r in self._rules:
            r.set_boiler_state_cb(lambda: self._curr_val == self._on_val)

        log.info("MQTT Heating manager started. Heating state %s link %s PowerOn %s",
                  self._boiler.get('state'),
                  self._boiler.get('linkquality'),
                  self._boiler.get('power_on_behavior'))
        self._set_poweron_behaviour(thing)

        if self._pending_state is not None:
            # There was a saved state, apply ASAP
            log.info("Boiler discovered, applying pending state...")
            self._on_boiler_state_should_change(new=self._pending_state, old=ScheduleSlot(hour=0, minute=0))

        self._sched.add_job(func=self._tick, trigger="date", run_date=self.schedule.active().get_slot_change_time())
        # Tick every few minutes, just in case there's a bug in scheduling somewhere and to verify
        # the state of the mqtt thing
        self._sched.add_job(func=self._tick, trigger="interval",
                                seconds=self._schedule_tick_interval_secs, next_run_time=datetime.now())

    def _set_poweron_behaviour(self, thing):
        if 'power_on_behavior' not in thing.actions:
            log.info("Boiler %s doesn't support power_on_behavior, not setting", thing.name)
            return

        if thing.get('power_on_behavior') in ['previous', 'off']:
            log.debug(
                "Boiler %s already has power_on_behavior=%s, not setting",
                thing.name, thing.get('power_on_behavior'))
            return

        for val in ['previous', 'off']:
            if val in thing.actions['power_on_behavior'].value.meta['values']:
                thing.set('power_on_behavior', val)
                log.info("Set boiler %s power_on_behavior to '%s'", thing.name, val)
                self._z2m.broadcast_thing(thing)
                return

        opts = ", ".join(thing.actions['power_on_behavior'].value.meta['values'])
        log.error(
            "Can't set boiler %s power_on_behavior, "
            "don't know what option to choose. Options: %s",
            thing.name, opts)

    def _tick(self):
        # TODO: Check MQTT thing is alive
        advanced_slot = self.schedule.tick()
        if advanced_slot:
            self._sched.add_job(func=self._tick, trigger="date", run_date=self.schedule.active().get_slot_change_time())

    def _on_boiler_state_should_change(self, new, old):
        if self._boiler is None:
            # This is benign and happens at startup, while boiler isn't knowon yet. If the boiler isn't found, a
            # critical error will be logged later.
            log.debug(
                "Boiler state changed to %s (reason: %s), but no boiler is known yet",
                new.request_on, new.reason)
            self._pending_state = new
            return

        log.info(
            "Boiler state or reason changed, notifying MQTT thing "
            "(%s, Policy: %s, reason: %s)",
            new.request_on, new.allow_on, new.reason)
        is_first_set = self._curr_val is None
        if new.request_on in (True, 1, self._on_val):
            self._curr_val = self._on_val
        else:
            self._curr_val = self._off_val

        log.info("Change boiler state: self._boiler.set('state', %s)", self._curr_val)
        self._boiler.set('state', self._curr_val)
        self._z2m.broadcast_thing(self._boiler)

        now_on = 'on' if new.request_on else 'off'
        old_on = 'on' if old.request_on else 'off'
        self._boiler_state_history.append({
            'time': datetime.now(),
            'new_state': now_on,
            'old_state': old_on,
            'reason': new.reason,
        })

        if old.request_on == new.request_on:
            log.debug("Boiler state hasn't actually changed (state is %s, reason %s), will skip Telegram notification",
                      new.request_on, new.reason)
            return
        if is_first_set:
            log.debug("Skip Telegram notifications for service startup")
            return

        msg = f'Heating is now {now_on} (was {old_on}). Reason: {new.reason}'
        self.message_svc("ZmwTelegram", "send_text", {'msg': msg})

service_runner(ZmwHeating)
