""" Executes user-defined actions """

from flask import abort
from datetime import datetime, timedelta
from zzmw_lib.logs import build_logger

log = build_logger("Z2mContactSensorDebouncer")

class TransitionExecutor:
    """
    Executes actions defined on the config file on transition changes
    """
    def __init__(self, cfg, sched, svc_mgr, actions):
        self._svc_mgr = svc_mgr
        self._actions = actions

        self._skipping_sms = False
        self._skipping_chime = False
        self._scheduler = sched
        self._chime_skip_job = None
        self._chime_overrides = {}  # (sensor_name, action) -> {"url": url, "job": scheduler_job}

        self._chime_skip_default_secs = cfg['chime_skip_default_secs']
        self._chime_skip_min_secs = 5
        self._chime_skip_max_secs =  cfg['chime_skip_max_secs']
        if self._chime_skip_min_secs > self._chime_skip_default_secs:
            raise ValueError("Invalid skip chime defaults: Minimum should be bigger than default")
        if self._chime_skip_max_secs < self._chime_skip_default_secs:
            raise ValueError("Invalid skip chime defaults: default should be less than maximum")
        if self._chime_skip_max_secs < self._chime_skip_min_secs:
            raise ValueError("Invalid skip chime defaults: maximum should be more than minimum")

        # TODO
        self._running_in_mock_mode = False
        if self._running_in_mock_mode:
            log.warning("RUNNING IN MOCK MODE")
            self._skipping_sms = True
            self._skipping_chime = True

    def get_skipping_chimes(self):
        """ True if chimes are not playing """
        return self._chime_skip_job is not None

    def get_skipping_chimes_timeout_secs(self):
        """ Time until chimes play again (if skipping). Null if chimes playing """
        if self._chime_skip_job is None or self._chime_skip_job.next_run_time is None:
            return None
        next_t = self._chime_skip_job.next_run_time
        delta = next_t - datetime.now(next_t.tzinfo)
        return max(delta.total_seconds(), 0)

    def _skip_chime_job_cancel(self):
        cancel = False
        if self._chime_skip_job is not None:
            try:
                self._scheduler.remove_job(self._chime_skip_job.id)
                cancel = True
            except Exception:  # pylint: disable=broad-except
                # Job removal can fail for many reasons (already removed, scheduler stopped, etc.)
                # This is cleanup code, so we log and continue
                pass
        self._chime_skip_job = None
        return cancel

    def skip_chimes_with_timeout(self, duration_secs=None):
        """
        Disable chimes for specified duration.
        If chimes are already being skipped, this resets the timeout to the new duration.
        """
        duration_secs = duration_secs or self._chime_skip_default_secs
        try:
            duration_secs = int(duration_secs)
        except ValueError:
            log.warning("User requested to skip chimes for invalid '%s' seconds", duration_secs)
            return abort(400, "Invalid timeout: not a number")
        if not(self._chime_skip_min_secs < duration_secs < self._chime_skip_max_secs):
            log.error("Request to skip chimes for %d is not valid, should be [%d, %d]",
                      duration_secs, self._chime_skip_min_secs, self._chime_skip_max_secs)
            return abort(400, "Invalid timeout: not in range")

        timeout_existed = self._skip_chime_job_cancel()
        log.info("Request to skip chimes for %s seconds%s", duration_secs,
                 " (resetting existing timeout)" if timeout_existed else "")

        run_time = datetime.now() + timedelta(seconds=duration_secs)
        self._chime_skip_job = self._scheduler.add_job(self.enable_chimes, 'date', run_date=run_time)
        self._skipping_chime = True
        return {'timeout': duration_secs}

    def enable_chimes(self):
        """ Re-enable chimes immediately, cancelling any pending skip job. """
        if self._skipping_chime:
            log.info("Reenabling chimes!")
        self._skipping_chime = self._running_in_mock_mode
        self._skip_chime_job_cancel()
        return ""

    def chime_override(self, sensor_name, action, url, timeout=None):
        """
        Register a temporary override for sound_asset_announce on a sensor+action.
        While active, triggers for this sensor+action will play the override URL
        instead of the configured sound asset.
        """
        timeout = timeout or self._chime_skip_default_secs
        try:
            timeout = int(timeout)
        except ValueError:
            log.warning("chime_override: invalid timeout '%s'", timeout)
            return abort(400, "Invalid timeout: not a number")
        if not(self._chime_skip_min_secs < timeout < self._chime_skip_max_secs):
            log.warning("chime_override: timeout %d not in range [%d, %d]",
                        timeout, self._chime_skip_min_secs, self._chime_skip_max_secs)
            return abort(400, "Invalid timeout: not in range")

        key = (sensor_name, action)
        # Cancel existing override for this key if any
        if key in self._chime_overrides:
            old_job = self._chime_overrides[key]["job"]
            try:
                self._scheduler.remove_job(old_job.id)
            except Exception:
                pass

        run_time = datetime.now() + timedelta(seconds=timeout)
        job = self._scheduler.add_job(self._remove_chime_override, 'date',
                                      run_date=run_time, args=[key])
        self._chime_overrides[key] = {"url": url, "job": job}
        log.info("chime_override: %s.%s -> %s (timeout %ds)", sensor_name, action, url, timeout)
        return {'sensor_name': sensor_name, 'action': action, 'url': url, 'timeout': timeout}

    def _remove_chime_override(self, key):
        if key in self._chime_overrides:
            log.info("chime_override expired for %s.%s", key[0], key[1])
            del self._chime_overrides[key]

    def on_transition(self, sensor_name, action):
        """ Execute a set of user defined actions for a sensor event. """
        # Z2mContactSensorDebouncer should have validated that this sensor is valid, we can assume
        # access is correct (and crash if it's not, as it's a bug). action may not exist.
        if action not in self._actions[sensor_name]:
            log.debug("No action to exec for %s.%s", sensor_name, action)
            return

        log.info("Exec actions for %s.%s", sensor_name, action)
        to_exec = self._actions[sensor_name][action]
        for act, cfg in to_exec.items():
            if cfg is None:
                log.warning("Action %s.%s is empty, is the config OK?", sensor_name, action)
                continue
            match act:
                case 'telegram':
                    self._telegram(sensor_name, cfg)
                case 'whatsapp':
                    self._whatsapp(sensor_name, cfg)
                case 'tts_announce':
                    self._tts_announce(sensor_name, cfg)
                case 'sound_asset_announce':
                    self._sound_asset_announce(sensor_name, action, cfg)
                case _:
                    log.error("Requested invalid action %s.%s", sensor_name, act)

    def _telegram(self, sensor_name, cfg):
        if self._skipping_sms:
            log.info("Skipping SMS: Sensor %s would Telegram '%s'", sensor_name, cfg)
            return
        log.debug("Sensor %s Telegram's '%s'", sensor_name, cfg)
        self._svc_mgr.message_svc("ZmwTelegram", "send_text", {'msg': cfg['msg']})

    def _whatsapp(self, sensor_name, cfg):
        if self._skipping_sms:
            log.info("Skipping SMS: Sensor %s would WA '%s'", sensor_name, cfg)
            return
        log.debug("Sensor %s WA's '%s'", sensor_name, cfg)
        self._svc_mgr.message_svc("ZmwWhatsapp", "send_text", {'msg': cfg['msg']})

    def _tts_announce(self, sensor_name, cfg):
        if self._skipping_chime:
            log.info("Skipping announcement: Sensor %s would TTS '%s'", sensor_name, cfg)
            return
        log.debug("Sensor %s TTS '%s'", sensor_name, cfg)
        self._svc_mgr.message_svc("ZmwSpeakerAnnounce", "tts", {'msg': cfg['msg'], 'lang': cfg['lang']})

    def _sound_asset_announce(self, sensor_name, action, cfg):
        if self._skipping_chime:
            log.info("Skipping announcement: Sensor %s would play '%s'", sensor_name, cfg)
            return
        override_key = (sensor_name, action)
        if override_key in self._chime_overrides:
            override_url = self._chime_overrides[override_key]["url"]
            log.info("Sensor %s.%s using chime override: %s", sensor_name, action, override_url)
            self._svc_mgr.message_svc("ZmwSpeakerAnnounce", "play_asset", {"public_www": override_url})
            return
        log.debug("Sensor %s plays '%s'", sensor_name, cfg)
        self._svc_mgr.message_svc("ZmwSpeakerAnnounce", "play_asset", cfg)
