"""Contact sensor monitoring with timeout and curfew alerts."""

from zzmw_lib.service_runner import service_runner
from zzmw_lib.zmw_mqtt_service import ZmwMqttService
from zzmw_lib.logs import build_logger

from timeout_mon import TimeoutMonitor
from transition_executor import TransitionExecutor
from validate_config import validate_cfg_actions
from z2m_sensor_debouncer import Z2mContactSensorDebouncer

import os
import pathlib

log = build_logger("ZmwContactmon")

class ZmwContactmon(ZmwMqttService):
    """
    Monitors Z2M contact sensors and executes configured actions (notifications,
    announcements) when sensors change state, timeout, or violate curfew.
    """
    def __init__(self, cfg, www, sched):
        super().__init__(cfg, svc_topic='zmw_contactmon', scheduler=sched,
                         svc_deps=['ZmwSpeakerAnnounce', 'ZmwWhatsapp', 'ZmwTelegram'])

        self._sched = sched

        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        self._public_url_base = www.register_www_dir(www_path)

        # Last action: connect to z2m once everything is setup
        self._actions_on_sensor_change = validate_cfg_actions(www_path, self._public_url_base, cfg)
        self._exec = TransitionExecutor(cfg, self._sched, self, self._actions_on_sensor_change)
        self._timeouts = TimeoutMonitor(self._sched, self._exec, self._actions_on_sensor_change)

        # Set up curfew monitor
        if 'curfew_hour' in cfg:
            curfew_time = cfg['curfew_hour'].split(':')
            self._sched.add_job(self._curfew, 'cron', hour=int(curfew_time[0]), minute=int(curfew_time[1]))
            log.info("Curfew check scheduled daily at %s", cfg['curfew_hour'])

        www.serve_url('/svc_state', self._svc_state)
        www.serve_url('/skip_chimes', self._exec.skip_chimes_with_timeout)
        www.serve_url('/skip_chimes_with_timeout/<duration_secs>', self._exec.skip_chimes_with_timeout)
        www.serve_url('/enable_chimes', self._exec.enable_chimes)
        www.serve_url('/test_curfew', self._curfew)

        self._z2m = Z2mContactSensorDebouncer(cfg, self,
                                              self._actions_on_sensor_change,
                                              self._on_sensor_change,
                                              self._sched)

    def get_service_alerts(self):
        alerts = []
        for sensor, status in self._timeouts.get_monitoring_sensors().items():
            alerts.append(f"{sensor}: {status}")
        return alerts

    def get_mqtt_description(self):
        return {
            "commands": {
                "skip_chimes": {
                    "description": "Temporarily disable chime/sound notifications",
                    "params": {"timeout": "(optional) Duration in seconds to skip chimes. Uses configured default if omitted."}
                },
                "enable_chimes": {
                    "description": "Re-enable chime notifications immediately, cancelling any pending skip timeout",
                    "params": {}
                },
                "publish_state": {
                    "description": "Request current service state. Response published on publish_state_reply",
                    "params": {}
                },
                "get_mqtt_description": {
                    "description": "Request MQTT API description. Response published on get_mqtt_description_reply",
                    "params": {}
                },
            },
            "announcements": {
                "publish_state_reply": {
                    "description": "Response to publish_state command with full service state. Also published after skip_chimes, enable_chimes, or publish_state. Contains full service state",
                    "payload": {
                        "sensors": "Dict of sensor_name -> {in_normal_state, contact, ...}",
                        "history": "List of recent contact state changes",
                        "skipping_chimes": "Boolean, true if chimes are currently suppressed",
                        "skipping_chimes_timeout_secs": "Seconds until chimes re-enable, or null"
                    }
                },
                "<sensor_name>/contact": {
                    "description": "Published when a contact sensor changes state",
                    "payload": {
                        "sensor": "Name of the sensor",
                        "contact": "Current contact state",
                        "prev_contact": "Previous contact state",
                        "entering_non_normal": "Previous contact state (indicates if entering non-normal)"
                    }
                },
                "get_mqtt_description_reply": {
                    "description": "Response to get_mqtt_description with this API description",
                    "payload": "(this object)"
                },
            }
        }

    def on_service_received_message(self, subtopic, msg):
        """ MQTT callback """
        if subtopic.endswith('_reply'):
            return
        match subtopic:
            case "skip_chimes":
                self._exec.skip_chimes_with_timeout(msg.get('timeout'))
                self.publish_own_svc_message("publish_state_reply", self._svc_state())
            case "enable_chimes":
                self._exec.enable_chimes()
                self.publish_own_svc_message("publish_state_reply", self._svc_state())
            case "publish_state":
                self.publish_own_svc_message("publish_state_reply", self._svc_state())
            case "get_mqtt_description":
                self.publish_own_svc_message("get_mqtt_description_reply",
                    self.get_mqtt_description())
            case _:
                pass  # Ignore unknown subtopics and sensor echos

    def on_dep_published_message(self, svc_name, subtopic, msg):
        pass

    def _svc_state(self):
        return {
            'sensors': self._z2m.get_sensors_state(),
            'history': self._z2m.get_contact_history(),
            'skipping_chimes': self._exec.get_skipping_chimes(),
            'skipping_chimes_timeout_secs': self._exec.get_skipping_chimes_timeout_secs(),
        }

    def _on_sensor_change(self, thing, contact, contact_action, prev_contact_state, entering_non_normal):
        log.info("Sensor %s transitions from %s to %s. Will execute '%s' actions",
                 thing.name, contact, prev_contact_state, contact_action)
        self._exec.on_transition(thing.name, contact_action)
        self._timeouts.notify_change(thing, entering_non_normal)

        self.publish_own_svc_message(f"{thing.name}/contact", {
                "sensor": thing.name,
                "contact": contact,
                "prev_contact": prev_contact_state,
                "entering_non_normal": prev_contact_state,
        })

    def _curfew(self):
        log.info("Running curfew check")
        sensors = self._z2m.get_sensors_state()
        for sensor_name, sensor_state in sensors.items():
            if not sensor_state.get('in_normal_state', True):
                log.info("Curfew: Sensor %s in non-normal state, triggering curfew action", sensor_name)
                self._exec.on_transition(sensor_name, 'curfew')

service_runner(ZmwContactmon)
