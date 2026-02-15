""" Doorbell/ONVIF-camera service """

import asyncio
import time
import logging
import aiohttp

from abc import ABC, abstractmethod

from flask import request as FlaskRequest
from threading import Lock, Thread

from rtsp import Rtsp
from snap_on_movement import SnapOnMovement

from zzmw_lib.logs import build_logger

import reolink_aio
from reolink_aio.api import Host as ReolinkDoorbellHost
from reolink_aio.exceptions import ReolinkError, SubscriptionError
from reolink_aio.helpers import parse_reolink_onvif_event

log = build_logger("Reolink")
logging.getLogger("asyncio").setLevel(logging.ERROR)
logging.getLogger("apscheduler.executors.default").setLevel(logging.ERROR)
logging.getLogger("apscheduler.scheduler").setLevel(logging.ERROR)
_reolink_api_logger = logging.getLogger("reolink_aio.api")
_reolink_api_logger.setLevel(logging.ERROR)
_reolink_api_logger.addFilter(lambda r: "Error while unsubscribing" not in r.getMessage())
logging.getLogger("reolink_aio.api.data").setLevel(logging.ERROR)
logging.getLogger("reolink_aio.helpers").setLevel(logging.ERROR)


async def _connect_to_cam(cam_host, cam_user, cam_pass, webhook_url, rtsp_cbs,
                          rec_path, rec_retention_days, rec_default_duration_secs, scheduler,
                          is_doorbell):
    log.info("Connecting to camera at %s...", cam_host)
    cam = ReolinkDoorbellHost(cam_host, cam_user, cam_pass, use_https=True,
                              # We assume all cams are LAN based, so make the timeout quite small
                              timeout=3)

    # Fetch all cam state, or throw on failure
    await cam.get_host_data()
    await cam.get_states()
    cam.construct_capabilities()

    # Cleanup old subscriptions, if there were any
    if webhook_url is not None:
        try:
            # Assumes we're the only client to subscribe to this cam
            await cam.unsubscribe()
        except ReolinkError as e:
            # unsubscribe failure is non-critical, proceeding anyway
            log.warning("Failed to cleanup old subscriptions for cam %s (continuing): %s", cam_host, e)

        try:
            log.info('Subscribe camera to announce callback "%s"', webhook_url)
            await cam.subscribe(webhook_url)
        except ReolinkError:
            log.error("Failed to subscribe to cam %s events", cam_host, exc_info=True)
            # subscribe failure is critical, re-raising
            raise

    log.info("Connected to camera %s %s model %s - firmware %s",
             cam_host,
             cam.camera_name(0),
             cam.camera_model(0),
             cam.camera_sw_version(0))

    if is_doorbell and not cam.is_doorbell(0):
        log.error("Camera %s is configured as doorbell but reports it isn't one!", cam_host)

    # RTSP failure is non-critical, recording will be disabled
    try:
        rtspurl = await cam.get_rtsp_stream_source(0, "main")
        log.info("Cam %s offers RTSP at %s", cam_host, rtspurl)
        rtsp = Rtsp(cam_host, rtsp_cbs, rtspurl, rec_path, scheduler, rec_retention_days, rec_default_duration_secs)
    except ReolinkError:
        log.error("Failed to get RTSP URL from cam %s (recording disabled)", cam_host, exc_info=True)

    return cam, rtsp


class ReolinkDoorbell(ABC):
    """ Subscribe to ONVIF notifications from a Reolink cam """

    def __init__(self, cfg, webhook_url, scheduler):
        super().__init__()
        # __del__ will run if the ctor fails, so mark "we've been here" somehow
        self._should_be_connected = False
        self._cam = None
        self._cam_host = cfg['cam_host']
        self._cam_user = cfg['cam_user']
        self._cam_pass = cfg['cam_pass']
        self._is_doorbell = cfg.get('is_doorbell', False)

        self._webhook_url = webhook_url
        self._cfg = cfg

        self._cam_movement_active_watchdog = cfg['cam_movement_active_watchdog']
        self._debounce_timeout_sec = cfg['debounce_timeout_sec']
        self._debounce_msg = {}
        self._motion_evt_lvl = 0
        self._motion_evt_job = None

        self.rtsp = None
        self._snap_manager = SnapOnMovement(cfg)

        self._video_on_movement = cfg.get('video_on_movement', False)
        self._rec_path = cfg.get('rec_path')
        if self._video_on_movement and not self._rec_path:
            self._video_on_movement = False
            log.error("Cam %s requests video on movement, but rec_path not available. Recordings disabled.", self._cam_host)
        self._rec_retention_days = int(cfg['rec_retention_days'])
        self._rec_default_duration_secs = int(cfg['rec_default_duration_secs'])

        self._scheduler = scheduler
        self._runner = asyncio.new_event_loop()
        self._runner_thread = None
        self._announce_lock = Lock()

        self._cam_subscription_watchdog = self._scheduler.add_job(
            func=self._check_cam_subscription,
            trigger="interval",
            seconds=cfg['cam_subscription_check_interval_secs'])

    def _start_runner_thread(self):
        """Start the event loop running in a background thread."""
        def _run_loop():
            asyncio.set_event_loop(self._runner)
            self._runner.run_forever()

        self._runner_thread = Thread(target=_run_loop, daemon=True)
        self._runner_thread.start()

    def _run_async(self, coro):
        """Schedule a coroutine on the event loop and wait for result."""
        future = asyncio.run_coroutine_threadsafe(coro, self._runner)
        return future.result()

    def get_cam_host(self):
        """Get camera host address."""
        return self._cam_host

    def connect_bg(self):
        """ Logs in and subscribes to camera events (non-blocking) """
        self._should_be_connected = True
        if self._runner_thread is None:
            self._start_runner_thread()

        camtask = _connect_to_cam(self._cam_host, self._cam_user, self._cam_pass, self._webhook_url, self,
                                  self._rec_path, self._rec_retention_days, self._rec_default_duration_secs,
                                  self._scheduler, self._is_doorbell)

        def on_done(future):
            try:
                self._cam, self.rtsp = future.result()
            except (reolink_aio.exceptions.LoginError, reolink_aio.exceptions.ReolinkTimeoutError) as e:
                log.error("Can't connect to camera %s, please check host is up and config is correct: %s", self._cam_host, e)
            except ReolinkError:
                log.error("Failed to connect to cam %s, will retry later", self._cam_host, exc_info=True)

        future = asyncio.run_coroutine_threadsafe(camtask, self._runner)
        future.add_done_callback(on_done)

    def failed_to_connect(self):
        return self._should_be_connected and not self._cam

    def __del__(self):
        self.disconnect()

    def disconnect(self):
        """ Logs out and tries to cleanup subscriptions to events in the camera """
        if not self._should_be_connected or not self._cam:
            # Constructor failed or already disconnected
            return

        async def _async_deinit():
            log.info("Disconnecting from camera at %s...", self._cam_host)
            try:
                await self._cam.unsubscribe()
                log.info("Unsubscribed camera %s from callbacks", self._cam_host)
            except ReolinkError:
                log.warning("Failed to unsubscribe during disconnect from %s", self._cam_host, exc_info=True)
            try:
                await self._cam.logout()
                log.info("Logged out camera %s", self._cam_host)
            except ReolinkError:
                log.warning("Failed to logout during disconnect from %s", self._cam_host, exc_info=True)

        self._should_be_connected = False
        self._cam_subscription_watchdog.remove()
        self._run_async(_async_deinit())
        log.info("Camera %s now disconnected", self._cam_host)
        self._runner.call_soon_threadsafe(self._runner.stop)
        self._runner_thread.join()
        self._runner.close()
        self._cam = None

    def _check_cam_subscription(self):
        if not self._should_be_connected or not self._cam:
            # Not init'd yet or subscription not required
            return

        def _reconnect():
            try:
                camtask = _connect_to_cam(self._cam_host, self._cam_user, self._cam_pass, self._webhook_url, self,
                                          self._rec_path, self._rec_retention_days, self._rec_default_duration_secs,
                                          self._scheduler, self._is_doorbell)
                self._cam, self.rtsp = self._run_async(camtask)
            except ReolinkError:
                log.error("Failed to reconnect to cam %s, will retry later", self._cam_host, exc_info=True)

        async def _renew_async():
            if not self._cam:
                _reconnect()
                return

            try:
                await self._cam.renew()
                return
            # On renew exception, fallthrough and try to resubscribe
            except SubscriptionError:
                log.info("Cam %s subscription renewal failed, will resubscribe", self._cam_host)
            except RuntimeError:
                log.error("Runtime error renewing cam %s subscription", self._cam_host, exc_info=True)

            try:
                await self._cam.unsubscribe()
                await self._cam.subscribe(self._webhook_url)
                log.info("Set up new subscription %s for cam %s...", self._webhook_url, self._cam_host)
                return
            # If this fails too, try to disconnect and reconnect
            except SubscriptionError:
                log.error("Error creating new cam %s subscription", self._cam_host, exc_info=True)
            except RuntimeError:
                log.error("Runtime error creating new cam %s subscription", self._cam_host, exc_info=True)

            log.error("All recovery attempts failed, start new connection to cam %s", self._cam_host)
            try:
                # Try to cleanup (but likely to fail, if we got here everything may be broken)
                await self._cam.unsubscribe()
                await self._cam.logout()
            except Exception:  # pylint: disable=broad-except
                pass

            _reconnect()

        must_renew = False
        try:
            t = self._cam.renewtimer() if self._cam else 0
            if t <= 100:
                log.debug("Subscription to cam %s has %s seconds remaining, renewing", self._cam_host, t)
                must_renew = True
        except Exception:  # pylint: disable=broad-except
            must_renew = True
            log.error("Error checking for cam %s subscription, will force renew", self._cam_host, exc_info=True)

        if must_renew:
            self._run_async(_renew_async())

    def on_cam_webhook(self):
        """Handle incoming webhook notifications from camera."""
        try:
            # If parsing fails, ensure the exception handler can print something
            msg = None # If prints None == flask failed
            msg = FlaskRequest.data
            msg = parse_reolink_onvif_event(msg)
            log.debug("Received event from camera %s: %s", self._cam_host, str(msg))
            # Flatten the message: we don't care about channels
            flatmsg = {}
            for k, v in msg.items():
                for kk, vv in v.items():
                    if kk in flatmsg:
                        log.error("Format error from camera %s: duplicated key %s", self._cam_host, k)
                    flatmsg[kk] = vv

            with self._announce_lock:
                self._on_cam_webhook_msg(flatmsg)
        except Exception:  # pylint: disable=broad-except
            log.error("Error processing event from camera %s: %s", self._cam_host, str(msg), exc_info=True)
        # Tell the camera we succesfully processed the message, always, so it doesn't retry
        return "", 200

    def _on_cam_webhook_msg(self, msg):
        # msg should look something like this: {
        #   'Motion': False, 'MotionAlarm': False, 'Visitor': False, 'FaceDetect': False,
        #   'PeopleDetect': False, 'VehicleDetect': False, 'DogCatDetect': False}
        # Note: 'Visitor' key is only present for doorbell cameras

        def debounce(msg, key, key_must_exist=True):
            if key not in msg:
                if key_must_exist:
                    log.error("Camera %s missing expected key %s from subscription", self._cam_host, key)
                return False

            # Event isn't active, skip debounce logic
            if not msg[key]:
                return False

            dt = 2 * self._debounce_timeout_sec
            if f'{key}_last_true' in self._debounce_msg:
                dt = time.time() - self._debounce_msg[f'{key}_last_true']
            debounced_active = dt > self._debounce_timeout_sec
            self._debounce_msg[f'{key}_last_true'] = time.time()
            return debounced_active

        if debounce(msg, 'Visitor', key_must_exist=self._is_doorbell):
            if not self._is_doorbell:
                log.error("Something weird is going on, non-doorbell '%s' reports doorbell button press", self._cam_host)
            log.info("Doorbell cam %s says someone pressed the visitor button", self._cam_host)
            self.on_doorbell_button_pressed(self._cam_host, self.get_snapshot(), msg)

        # Ignore debounce rules for rtsp pet rules
        for key in ['Visitor', 'Motion', 'MotionAlarm', 'PeopleDetect']:
            if key in msg and msg[key]:
                if self.rtsp is not None:
                    self.rtsp.pet_timer()
                break

        if msg.get('PeopleDetect') and not msg['Motion'] and not msg['MotionAlarm']:
            log.debug("Ignoring camera %s event: people detect outside alarm zone.", self._cam_host)
            return

        prev_motion_event_lvl = self._motion_evt_lvl
        self._motion_evt_lvl = 0
        if debounce(msg, 'Motion', key_must_exist=False):
            self._motion_evt_lvl += 1
        if debounce(msg, 'MotionAlarm', key_must_exist=False):
            self._motion_evt_lvl += 1
        if debounce(msg, 'PeopleDetect', key_must_exist=False):
            self._motion_evt_lvl += 1

        if prev_motion_event_lvl == 0 and self._motion_evt_lvl > 0:
            self._motion_evt_job = self._scheduler.add_job(
                func=self._motion_check_active,
                trigger="interval",
                seconds=self._cam_movement_active_watchdog)
            self._on_motion_detected(self._motion_evt_lvl, msg)
        elif prev_motion_event_lvl > 0 and self._motion_evt_lvl > 0:
            # Camera reports motion still detected, add more timeout
            if self._motion_evt_job is not None:
                self._motion_evt_job.remove()
            self._motion_evt_job = self._scheduler.add_job(
                func=self._motion_check_active,
                trigger="interval",
                seconds=self._cam_movement_active_watchdog)
        elif prev_motion_event_lvl > 0 and self._motion_evt_lvl == 0:
            if self._motion_evt_job is not None:
                self._motion_evt_job.remove()
            self._motion_evt_job = None
            self.on_motion_cleared(self._cam_host, msg)

    def _motion_check_active(self):
        try:
            state_updated = self._run_async(self._cam.get_ai_state_all_ch())
        except ReolinkError as e:
            log.warning("Failed to poll AI state for cam %s: %s", self._cam_host, e)
            state_updated = False

        if state_updated and self._cam.motion_detected(0):
            log.info("Camera %s motion timeout, but motion still active. Waiting more.", self._cam_host)
            self._motion_evt_job = self._scheduler.add_job(
                func=self._motion_check_active,
                trigger="interval",
                seconds=self._cam_movement_active_watchdog)
            return

        if not state_updated:
            log.info("Camera %s motion timeout, polling state failed", self._cam_host)
        elif not self._cam.motion_detected(0):
            log.info("Camera %s motion timeout, and motion not active: event lost?", self._cam_host)

        self._motion_evt_job = None
        # Timeout may be more than the watchdog, if the WD was reset at any point
        self.on_motion_timeout(self._cam_host, self._cam_movement_active_watchdog)


    def _on_motion_detected(self, motion_level, cam_msg):
        """ Motion detect event fired. Higher motion level means more confidence. """
        log.info("Camera %s detected motion (level %d)", self._cam_host, motion_level)
        snap_path = self.get_snapshot()
        if self._video_on_movement:
            self.start_recording()
        self.on_motion_detected(self._cam_host, snap_path, motion_level, cam_msg)

    def get_snapshot(self):
        """ Capture a snapshot from camera and save it via snap_manager """
        if not self._cam:
            log.warning("Requested snapshot from %s, but camera is offline", self._cam_host)
            return None

        if not self._snap_manager.is_enabled():
            return None

        try:
            snapshot_data = self._run_async(self._cam.get_snapshot(0))
        except ReolinkError:
            log.error("Failed to get snapshot from cam %s", self._cam_host, exc_info=True)
            return None

        return self._snap_manager.save_snapshot(snapshot_data)

    def get_last_snapshot_path(self):
        """Get path to the last saved snapshot."""
        return self._snap_manager.get_last_snap()

    def get_snap_manager(self):
        """Get the snapshot manager for this camera."""
        return self._snap_manager

    def start_recording(self, duration_secs=None):
        """Start RTSP recording for specified duration."""
        if self.rtsp is None:
            log.info("Ignore recording request for cam %s, recording disabled", self._cam_host)
            return

        try:
            log.info("Start recording for cam %s", self._cam_host)
            self.rtsp.trigger_recording(duration_secs)
        except Exception:  # pylint: disable=broad-except
            log.error("Failed to start doorbell recording", exc_info=True)

    # User is expected to extend this object to handle these events
    @abstractmethod
    def on_doorbell_button_pressed(self, cam_host, snap_path, full_cam_msg):
        """ Buttonn calling """

    @abstractmethod
    def on_motion_detected(self, cam_host, path_to_img, motion_level, full_cam_msg):
        """ Camera detects motion """

    @abstractmethod
    def on_motion_cleared(self, cam_host, full_cam_msg):
        """ Camera reports motion stopped """

    @abstractmethod
    def on_motion_timeout(self, cam_host, timeout):
        """ Motion event started but never finished within timeout """

    @abstractmethod
    def on_new_recording(self, cam_host, path):
        """ Camera recording available """

    @abstractmethod
    def on_recording_failed(self, cam_host, path):
        """ Camera recording failed """

    @abstractmethod
    def on_reencoding_ready(self, cam_host, orig_path, reencode_path):
        """ Reencoding requested and completed """

    @abstractmethod
    def on_reencoding_failed(self, cam_host, path):
        """ Reencoding requested but failed """
