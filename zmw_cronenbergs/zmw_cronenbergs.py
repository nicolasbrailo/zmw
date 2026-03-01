"""Cronenberg service for scheduled home automation tasks."""
import json
import os
import pathlib
import random
from datetime import datetime, timedelta
from collections import deque

from zzmw_lib.service_runner import service_runner
from zzmw_lib.zmw_mqtt_service import ZmwMqttService
from zzmw_lib.logs import build_logger
from zzmw_lib.geo_helpers import get_sun_times

from zzmw_lib.z2m.z2mproxy import Z2MProxy
from zzmw_lib.z2m.light_helpers import turn_all_lights_off
from zzmw_lib.z2m.www import Z2Mwebservice

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

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
        self._scheduled_jobs_info = []
        self._geo = cfg.get('geo', None)
        self._sun_jobs = []
        self._sched = sched

        # Set up www directory and endpoints
        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        self._public_url_base = www.register_www_dir(www_path)
        www.serve_url('/stats', self._get_stats)
        www.serve_url('/test_vacations_mode_late_afternoon', self._vacations_mode_late_afternoon)
        www.serve_url('/test_vacations_mode_evening', self._vacations_mode_evening)
        www.serve_url('/test_vacations_mode_night', self._vacations_mode_night)

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

        for idx, job_cfg in enumerate(cfg.get('scheduled_jobs', [])):
            if job_cfg['schedule'] in {'sunset', 'sunrise', 'dawn', 'dusk'}:
                self._sun_jobs.append(job_cfg)
            else:
                self._schedule_cron_job(idx, job_cfg)

        if len(self._sun_jobs) != 0:
            log.info("Sun-triggered jobs configured, scheduling daily recalculation at 00:05")
            sched.add_job(
                self._recalculate_sun_jobs,
                trigger=CronTrigger(hour=0, minute=5, second=0),
                id='sun_jobs_recalculate'
            )
            self._recalculate_sun_jobs()

    def _schedule_cron_job(self, idx, job_cfg):
        """Schedule a fixed-time cron job."""
        schedule = job_cfg['schedule']
        action = job_cfg['action']
        day_of_week = job_cfg.get('day_of_week', 'every_day')
        job_id = f'scheduled_{idx}_{action}'

        time_parts = schedule.split(':')
        hour, minute = int(time_parts[0]), int(time_parts[1])

        method = self._resolve_job_action(job_cfg)
        if method is None:
            log.error("Failed to schedule job: %s", job_cfg)
            return

        dow = None if day_of_week == 'every_day' else day_of_week
        log.info("Scheduling job '%s' at %02d:%02d (days: %s)", action, hour, minute, day_of_week)
        self._sched.add_job(
            method,
            trigger=CronTrigger(day_of_week=dow, hour=hour, minute=minute, second=0),
            id=job_id,
        )

        self._scheduled_jobs_info.append({
            'name': action,
            'schedule': f"{schedule} ({day_of_week})",
        })

    @staticmethod
    def _matches_day_of_week(day_of_week):
        """Check if today matches a day_of_week spec (e.g. 'mon', 'mon-fri', 'every_day')."""
        if day_of_week == 'every_day':
            return True
        _DAY_NAMES = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
        today = _DAY_NAMES[datetime.now().weekday()]
        if '-' in day_of_week:
            start, end = day_of_week.split('-')
            start_idx = _DAY_NAMES.index(start)
            end_idx = _DAY_NAMES.index(end)
            today_idx = _DAY_NAMES.index(today)
            return start_idx <= today_idx <= end_idx
        return today in day_of_week.split(',')

    def _recalculate_sun_jobs(self):
        """Compute today's sun times and schedule (or reschedule) one-shot sun jobs."""
        lat, lon = self._geo['lat'], self._geo['lon']
        sun = get_sun_times(lat, lon)
        now = datetime.now(sun['sunset'].tzinfo)

        # Remove old sun job info, keep cron job info
        self._scheduled_jobs_info = [j for j in self._scheduled_jobs_info if 'today_time' not in j]

        for idx, job_cfg in enumerate(self._sun_jobs):
            event = job_cfg['schedule']
            offset = job_cfg.get('offset_minutes', 0)
            action = job_cfg['action']
            day_of_week = job_cfg.get('day_of_week', 'every_day')
            job_id = f'sun_job_{idx}_{action}'

            base_time = sun[event]
            target_time = base_time + timedelta(minutes=offset)

            offset_str = ""
            if offset > 0:
                offset_str = f" + {offset}min"
            elif offset < 0:
                offset_str = f" - {abs(offset)}min"

            info = {
                'name': action,
                'schedule': f"{event}{offset_str} ({day_of_week})",
                'today_time': target_time.isoformat(),
            }

            if not self._matches_day_of_week(day_of_week):
                log.info("Sun job '%s' skipped, today is not %s", action, day_of_week)
                info['today_time'] = None
                self._scheduled_jobs_info.append(info)
                continue

            if target_time.date() != base_time.date():
                log.warning("Sun job '%s' offset would cross day boundary (%s -> %s), skipping",
                            action, base_time.strftime('%H:%M'), target_time.strftime('%Y-%m-%d %H:%M'))
                info['today_time'] = None
                self._scheduled_jobs_info.append(info)
                continue

            if target_time > now:
                method = self._resolve_job_action(job_cfg)
                if method is None:
                    info['today_time'] = None
                else:
                    log.info("Scheduling sun job '%s' at %s (%s)", action, target_time.strftime('%H:%M'), info['schedule'])
                    self._sched.add_job(
                        method,
                        trigger=DateTrigger(run_date=target_time),
                        id=job_id,
                        replace_existing=True,
                    )
            else:
                log.info("Sun job '%s' target time %s already passed, skipping", action, target_time.strftime('%H:%M'))
                info['today_time'] = None

            self._scheduled_jobs_info.append(info)

    def _get_stats(self):
        battery_things = self._z2m.get_things_if(lambda t: 'battery' in t.actions)
        battery_data = [
            {"name": t.name, "battery": t.get('battery')}
            for t in battery_things
        ]
        stats = {
            "light_check_history": list(self._light_check_history),
            "vacations_mode": self._vacations_mode,
            "scheduled_jobs": self._scheduled_jobs_info,
            "battery_things": battery_data,
        }
        return json.dumps(stats, default=str)

    def get_service_alerts(self):
        if self._vacations_mode:
            return ["Vacations mode is enabled! Expect random light effects."]
        return []

    def get_mqtt_description(self):
        return {
            "description": "Scheduled home automation cron jobs. Has scheduled lights-off, vacation mode (simulates occupancy), "\
                           "scheduled TTS speaker announcements, weekly low-battery Telegram alerts.",
            "meta": self.get_service_meta(),
            "commands": {
                "get_stats": {
                    "description": "light check history, vacation mode, battery info. Response on get_stats_reply",
                    "params": {}
                },
            },
            "announcements": {
                "get_stats_reply": {
                    "description": "Service stats",
                    "payload": {
                        "light_check_history": "light check events",
                        "vacations_mode": "bool, vacation mode enabled",
                        "scheduled_jobs": "List of scheduled jobs and their config",
                        "battery_things": "List of devices and their battery levels",
                    }
                },
                "get_mqtt_description_reply": {
                    "description": "Service description",
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

    def _resolve_job_action(self, job_cfg):
        """Resolve a job config into a callable. Returns None if action is invalid."""
        action = job_cfg['action']
        args = job_cfg.get('args', {})

        if action == 'turn_lights_on':
            return lambda a=args: self._turn_lights(a['names'], on=True)
        if action == 'turn_lights_off':
            return lambda a=args: self._turn_lights(a['names'], on=False)
        if action == 'speaker_announce':
            return lambda a=args: self._on_speaker_announce_cron(a['lang'], a['msg'], a['vol'])

        method = getattr(self, f'_{action}', None)
        if method is None:
            log.error("Scheduled job action '_%s' not found, skipping", action)
        return method

    def _turn_lights(self, light_names, on):
        """Turn a list of lights on or off by name."""
        for name in light_names:
            thing = self._z2m.get_thing(name)
            if thing is None:
                log.error("Scheduled job: light '%s' not found", name)
                continue
            if on:
                thing.turn_on()
            else:
                thing.turn_off()
            log.info("Scheduled job: turned %s %s", name, "on" if on else "off")
        self._z2m.broadcast_things(light_names)

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
