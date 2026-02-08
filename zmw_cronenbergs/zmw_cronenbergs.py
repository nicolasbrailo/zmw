"""Cronenberg service for scheduled home automation tasks."""
import json
import os
import pathlib
import random
from datetime import datetime
from collections import deque

from zzmw_lib.service_runner import service_runner
from zzmw_lib.zmw_mqtt_service import ZmwMqttService
from zzmw_lib.logs import build_logger

from zz2m.z2mproxy import Z2MProxy
from zz2m.light_helpers import turn_all_lights_off
from zz2m.www import Z2Mwebservice

from apscheduler.triggers.cron import CronTrigger

log = build_logger("ZmwCronenbergs")


class ZmwCronenbergs(ZmwMqttService):
    """
    Scheduled tasks service. Runs calendar-based automation like:
    - Turning off lights at specific times
    - Sending notifications about scheduled events
    """

    def __init__(self, cfg, www, sched):
        super().__init__(cfg, "zmw_cronenbergs", sched, svc_deps=['ZmwTelegram', 'ZmwSpeakerAnnounce'])
        self._z2m = Z2MProxy(cfg, self, sched)
        self._z2mw = Z2Mwebservice(www, self._z2m)

        self._light_check_history = deque(maxlen=10)
        self._vacations_selected_lights = None

        # Set up www directory and endpoints
        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        self._public_url_base = www.register_www_dir(www_path)
        www.serve_url('/stats', self._get_stats)
        www.serve_url('/mock_auto_lights_off', self._mock_auto_lights_off)
        www.serve_url('/test_low_battery_notifs', self._check_low_battery)
        www.serve_url('/test_vacations_mode_late_afternoon', self._vacations_mode_late_afternoon)
        www.serve_url('/test_vacations_mode_evening', self._vacations_mode_evening)
        www.serve_url('/test_vacations_mode_night', self._vacations_mode_night)

        # Schedule automatic lights off if configured
        if 'auto_lights_off' in cfg and cfg['auto_lights_off']['enable']:
            day_of_week = cfg['auto_lights_off']['day_of_week']
            time_parts = cfg['auto_lights_off']['time'].split(':')
            hour, minute = int(time_parts[0]), int(time_parts[1])
            log.info(f"Scheduling light check for {day_of_week} at {hour:02d}:{minute:02d}")
            sched.add_job(
                self._check_and_turn_off_lights,
                trigger=CronTrigger(day_of_week=day_of_week, hour=hour, minute=minute, second=0),
                id='auto_lights_off'
            )

        # Schedule weekly battery check on Sundays at 10:00
        log.info("Scheduling battery check for Sundays at 10:00")
        sched.add_job(
            self._check_low_battery,
            trigger=CronTrigger(day_of_week='sun', hour=10, minute=0, second=0),
            id='low_battery_check'
        )

        self._vacations_mode = 'vacations_mode' in cfg and cfg['vacations_mode']['enable']
        if self._vacations_mode:
            log.info("Vacations mode enabled, scheduling light effects")
            for job_name in ['late_afternoon', 'evening', 'night']:
                time_parts = cfg['vacations_mode'][job_name].split(':')
                hour, minute = int(time_parts[0]), int(time_parts[1])
                method = getattr(self, f'_vacations_mode_{job_name}')
                sched.add_job(
                    method,
                    trigger=CronTrigger(hour=hour, minute=minute, second=0),
                    id=f'vacations_mode_{job_name}'
                )

        self._speaker_announce = cfg.get('speaker_announce', [])
        for idx, announce in enumerate(self._speaker_announce):
            time_parts = announce['time'].split(':')
            hour, minute = int(time_parts[0]), int(time_parts[1])
            log.info(f"Scheduling speaker announce '{announce['msg']}' at {hour:02d}:{minute:02d}")
            sched.add_job(
                lambda lang=announce['lang'], msg=announce['msg'], vol=announce['vol']: self._on_speaker_announce_cron(lang, msg, vol),
                trigger=CronTrigger(hour=hour, minute=minute, second=0),
                id=f'speaker_announce_{idx}'
            )

    def _get_stats(self):
        battery_things = self._z2m.get_things_if(lambda t: 'battery' in t.actions)
        battery_data = [
            {"name": t.name, "battery": t.get('battery')}
            for t in battery_things
        ]
        stats = {
            "light_check_history": list(self._light_check_history),
            "vacations_mode": self._vacations_mode,
            "speaker_announce": self._speaker_announce,
            "battery_things": battery_data,
        }
        return json.dumps(stats, default=str)

    def get_service_alerts(self):
        if self._vacations_mode:
            return ["Vacations mode is enabled! Expect random light effects."]
        return []

    def get_mqtt_description(self):
        return {
            "description": "Scheduled home automation cron jobs. Includes auto lights-off checks, vacation mode (simulates occupancy with random lights), scheduled TTS speaker announcements, and weekly low-battery device alerts via Telegram.",
            "meta": self.get_service_meta(),
            "commands": {
                "get_stats": {
                    "description": "Request service stats (light check history, vacation mode status, battery info). Response published on get_stats_reply",
                    "params": {}
                },
            },
            "announcements": {
                "get_stats_reply": {
                    "description": "Response to get_stats with full service statistics",
                    "payload": {
                        "light_check_history": "List of recent light check events",
                        "vacations_mode": "Whether vacation mode is enabled",
                        "speaker_announce": "Configured speaker announcements",
                        "battery_things": "List of devices with battery levels",
                    }
                },
                "get_mqtt_description_reply": {
                    "description": "Response to get_mqtt_description with this service's MQTT API",
                    "payload": {"commands": {}, "announcements": {}}
                },
            }
        }

    def on_dep_published_message(self, _svc_name, _subtopic, _payload):
        # We don't need any replies from deps, ignore them
        pass

    def on_service_received_message(self, subtopic, payload):
        if subtopic.endswith('_reply'):
            return

        match subtopic:
            case "get_stats":
                stats = json.loads(self._get_stats())
                self.publish_own_svc_message("get_stats_reply", stats)
            case "get_mqtt_description":
                self.publish_own_svc_message("get_mqtt_description_reply",
                    self.get_mqtt_description())
            case _:
                log.warning("Ignoring unknown message '%s'", subtopic)

    def _mock_auto_lights_off(self):
        self._light_check_history.append({
            'date': datetime.now().strftime('%Y-%m-%d'),
            'timestamp': datetime.now().isoformat(),
            'lights_forgotten': True,
            'lights_left_on': ["Light1", "Light3"],
        })
        self._light_check_history.append({
            'date': datetime.now().strftime('%Y-%m-%d'),
            'timestamp': datetime.now().isoformat(),
            'lights_forgotten': False,
            'lights_left_on': [],
        })
        self._light_check_history.append({
            'date': datetime.now().strftime('%Y-%m-%d'),
            'timestamp': datetime.now().isoformat(),
            'lights_forgotten': True,
            'lights_left_on': ["Light1", "Light2", "Light3"],
        })
        return "OK"

    def _check_and_turn_off_lights(self):
        """
        Check which lights are on, turn them off, and send a notification.
        """
        lights_on = self._z2m.get_things_if(lambda t: t.thing_type == 'light' and t.is_light_on())

        self._light_check_history.append({
            'date': datetime.now().strftime('%Y-%m-%d'),
            'timestamp': datetime.now().isoformat(),
            'lights_forgotten': len(lights_on) > 0,
            'lights_left_on': [l.name for l in lights_on] if len(lights_on) > 0 else []
        })

        if len(lights_on) == 0:
            log.info("Light checker: no lights forgot on, nothing to do")
            return

        turn_all_lights_off(self._z2m)
        names = ", ".join([l.name for l in lights_on])
        msg = f'Someone forgot the lights on. Will turn off {names}'
        #self.message_svc("ZmwTelegram", "send_text", {'msg': msg})
        log.info(msg)

    def _check_low_battery(self):
        """
        Check battery levels of all devices and notify if any are low.
        """
        battery_things = self._z2m.get_things_if(lambda t: 'battery' in t.actions)

        low_battery = []
        for thing in battery_things:
            battery = thing.get('battery')
            if battery is None:
                continue
            if battery < 30:
                low_battery.append((thing.name, battery))

        if not low_battery:
            log.info("Battery check: all devices have sufficient battery")
            return "OK"

        msg_parts = [f"Low battery: {name} ({level}%)" for name, level in low_battery]
        msg = '\n'.join(msg_parts)
        self.message_svc("ZmwTelegram", "send_text", {'msg': msg})
        log.info(f"Battery check notification sent: {msg}")
        return "OK"

    def _vacations_mode_late_afternoon(self):
        lights = self._z2m.get_things_if(lambda t: t.thing_type == 'light')
        half_count = len(lights) // 2
        self._vacations_selected_lights = random.sample(lights, half_count)
        for light in self._vacations_selected_lights:
            log.info("Vacation mode. Set brigthness=75 for %s", light.name)
            light.set_brightness_pct(75)
        self._z2m.broadcast_things(self._vacations_selected_lights)
        self.message_svc("ZmwTelegram", "send_text", {'msg': "Home entering vacation mode: random lights on"})
        return {}

    def _vacations_mode_evening(self):
        if self._vacations_selected_lights is None:
            log.error("No vacation lights selected, did afternoon mode get scheduled?")
            return
        for light in self._vacations_selected_lights:
            log.info("Vacation mode. Set brigthness=40 for %s", light.name)
            light.set_brightness_pct(40)
        self._z2m.broadcast_things(self._vacations_selected_lights)
        return {}

    def _vacations_mode_night(self):
        turn_all_lights_off(self._z2m)
        msg = f'Home going to sleep! Will turn off all lights. Night night.'
        self.message_svc("ZmwTelegram", "send_text", {'msg': msg})
        log.info(msg)
        return {}

    def _on_speaker_announce_cron(self, lang, msg, vol):
        payload = {'msg': msg, 'lang': lang, 'vol': vol}
        log.info("Cron trigger for TTS: %s", payload)
        self.message_svc("ZmwSpeakerAnnounce", "tts", payload)


service_runner(ZmwCronenbergs)
