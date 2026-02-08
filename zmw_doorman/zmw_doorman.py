"""Doorbell event handler and notification service."""
import time
import os
import pathlib
import threading

from flask import send_file, jsonify

from zzmw_lib.service_runner import service_runner
from zzmw_lib.zmw_mqtt_service import ZmwMqttService
from zzmw_lib.logs import build_logger

from door_open_scene import DoorOpenScene
from door_stats import DoorStats

log = build_logger("ZmwDoorman")

class ZmwDoorman(ZmwMqttService):
    """Doorbell service that handles button press events and motion detection."""

    def __init__(self, cfg, www, sched):
        super().__init__(cfg, "zmw_doorman", scheduler=sched,
                         svc_deps=['ZmwSpeakerAnnounce', 'ZmwWhatsapp', 'ZmwTelegram',
                                   'ZmwReolinkCams', 'ZmwContactmon'])
        self._cfg = cfg
        # Ensure required config keys exist
        _ = self._cfg["doorbell_announce_volume"]
        _ = self._cfg["doorbell_announce_sound"]
        _ = self._cfg["doorbell_contact_sensor"]
        _ = self._cfg["doorbell_cam_host"]

        self._waiting_on_telegram_snap = None
        self._snap_request_timeout_secs = 5
        self._telegram_cmd_door_snap = 'door_snap'

        self._door_open_scene = DoorOpenScene(cfg, self, sched)
        self._door_stats = DoorStats(sched)

        self._contactmon_state_baton = threading.Event()
        self._contactmon_state = None
        self._last_motion_detected_time = 0

        # Initialize snap directory from persisted last snap path
        last_snap_path = self._door_stats.get_last_snap_path()
        if last_snap_path:
            self._snap_directory = os.path.dirname(last_snap_path)
            log.info("Restored snap directory from persisted state: %s", self._snap_directory)
        else:
            self._snap_directory = None

        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        www.serve_url('/get_cams_svc_url', self._get_cams_svc_url)
        www.serve_url('/get_contactmon_svc_url', self._get_contactmon_svc_url)
        www.serve_url('/contactmon_state', self._get_contactmon_state)
        www.serve_url('/stats', self._door_stats.get_stats)
        www.serve_url('/get_snap/<filename>', self._get_snap)
        www.serve_url('/request_snap', self._request_snap, methods=['PUT'])
        www.serve_url('/skip_chimes', self._skip_chimes, methods=['PUT'])
        self._public_url_base = www.register_www_dir(www_path)

    def get_mqtt_description(self):
        return {
            "commands": {
                "get_stats": {
                    "description": "Request door statistics (doorbell presses, motion events, door opens). Response published on get_stats_reply",
                    "params": {}
                },
                "get_mqtt_description": {
                    "description": "Request the MQTT interface description. Response published on get_mqtt_description_reply",
                    "params": {}
                },
            },
            "announcements": {
                "on_doorbell_pressed": {
                    "description": "Published when the doorbell button is pressed",
                    "payload": {"snap_path": "Path to camera snapshot (may be null)"}
                },
                "on_motion_detected": {
                    "description": "Published when motion is detected at the door camera",
                    "payload": {"snap_path": "Path to camera snapshot (may be null)"}
                },
                "on_motion_cleared": {
                    "description": "Published when the door motion event ends (vacancy reported or timeout)",
                    "payload": {}
                },
                "on_door_opened": {
                    "description": "Published when the door contact sensor reports the door opened",
                    "payload": {}
                },
                "on_door_closed": {
                    "description": "Published when the door contact sensor reports the door closed",
                    "payload": {}
                },
                "get_stats_reply": {
                    "description": "Response to get_stats command with current door statistics",
                    "payload": {"doorbell_press_count_today": "int", "motion_detection_count_today": "int",
                                "last_snap": "filename or null", "last_snap_time": "epoch or null",
                                "history": "list of event records", "motion_in_progress": "bool",
                                "door_open_in_progress": "bool"}
                },
                "get_mqtt_description_reply": {
                    "description": "Response to get_mqtt_description with this service's MQTT interface",
                    "payload": {"commands": "...", "announcements": "..."}
                },
            }
        }

    def on_service_received_message(self, subtopic, payload):
        # Ignore self-echo on reply topics and own announcements
        if subtopic.endswith('_reply'):
            return
        if subtopic.startswith('on_'):
            return

        match subtopic:
            case "get_stats":
                self.publish_own_svc_message("get_stats_reply",
                    self._door_stats.get_stats())
            case "get_mqtt_description":
                self.publish_own_svc_message("get_mqtt_description_reply",
                    self.get_mqtt_description())
            case _:
                log.error("Ignoring unknown MQTT command '%s'", subtopic)

    def _get_cams_svc_url(self):
        url = self.get_known_services().get("ZmwReolinkCams", {}).get("www")
        return jsonify({"url": url})

    def _get_contactmon_svc_url(self):
        url = self.get_known_services().get("ZmwContactmon", {}).get("www")
        return jsonify({"url": url})

    def _get_contactmon_state(self):
        self._contactmon_state_baton.clear()
        self.message_svc("ZmwContactmon", "publish_state", {})
        if not self._contactmon_state_baton.wait(timeout=3):
            return jsonify({'error': 'Timeout waiting for contactmon state'}), 504
        return jsonify(self._contactmon_state)

    def _skip_chimes(self):
        log.info("User requested to skip chimes via web UI")
        self._contactmon_state_baton.clear()
        self.message_svc("ZmwContactmon", "skip_chimes", {})
        if not self._contactmon_state_baton.wait(timeout=3):
            return jsonify({'error': 'Timeout waiting for contactmon state'}), 504
        return jsonify(self._contactmon_state)

    def on_service_came_up(self, service_name):
        if service_name == "ZmwTelegram":
            self.message_svc("ZmwTelegram", "register_command",
                             {'cmd': self._telegram_cmd_door_snap,
                              'descr': 'Take and send a doorbell cam picture'})

    def on_dep_published_message(self, svc_name, subtopic, msg):
        match svc_name:
            case 'ZmwContactmon':
                if subtopic.startswith("publish_state_reply"):
                    self._contactmon_state = msg
                    self._contactmon_state_baton.set()
                else:
                    self.on_contact_report(subtopic, msg)
            case 'ZmwSpeakerAnnounce':
                pass
            case 'ZmwWhatsapp':
                pass
            case 'ZmwTelegram':
                if subtopic.startswith("on_command/"):
                    self.on_telegram_cmd(subtopic[len("on_command/"):], msg)
            case 'ZmwReolinkCams':
                if subtopic.startswith("ls_cams"):
                    # Announcing cams, we don't care as we only monitor a single cam
                    return
                if msg.get("cam_host") != self._cfg["doorbell_cam_host"]:
                    # Service announced event for camera we don't monitor, ignore
                    return
                match subtopic:
                    case "on_snap_ready":
                        self.on_snap_ready(msg)
                    case "on_doorbell_button_pressed":
                        self.on_doorbell_button_pressed(msg)
                    case "on_motion_detected":
                        self.on_door_motion_detected(msg)
                    case "on_motion_cleared":
                        self.on_door_motion_cleared()
                    case "on_motion_timeout":
                        self.on_door_motion_timeout()
                    case _:
                        pass
            case _:
                log.error("Received unexpected message from service %s/%s: %s", service_name, subtopic, msg)

    def on_contact_report(self, msg_topic, msg):
        if self._cfg["doorbell_contact_sensor"] in msg_topic:
            if msg["entering_non_normal"] == True:
                self._door_open_scene.maybe_start()
                self._door_stats.record_door_open()
                self.publish_own_svc_message("on_door_opened", {})
            else:
                self._door_stats.record_door_close()
                self.publish_own_svc_message("on_door_closed", {})

    def on_telegram_cmd(self, cmd, _msg):
        """Handle Telegram commands."""
        if cmd == self._telegram_cmd_door_snap:
            log.info("User requested doorbell snap over Telegram, requesting snap from camera")
            if self._waiting_on_telegram_snap is not None:
                log.warning(
                    "A snap request is in progress. Requesting new snap. "
                    "First snap to arrive will be sent, others will be ignored."
                )
            self._waiting_on_telegram_snap = time.time()
            self.message_svc("ZmwReolinkCams", "snap", {"cam_host", self._cfg["doorbell_cam_host"]})

    def on_snap_ready(self, msg):
        """Handle camera snap ready event."""
        if 'snap_path' not in msg:
            log.error("Bad message format for snap_ready, missing path. Message: %s", msg)
            return
        self._update_snap_directory(msg['snap_path'])
        self._door_stats.record_snap(msg['snap_path'])

        if self._waiting_on_telegram_snap is None:
            log.debug("Received snap_ready command but it wasn't a Telegram request, will not send overt msg")
            return

        snap_rq_t = time.time() - self._waiting_on_telegram_snap
        if snap_rq_t >= self._snap_request_timeout_secs:
            log.warning(
                "Snap was requested %d seconds ago, ignoring (max timeout %d)",
                snap_rq_t, self._snap_request_timeout_secs
            )
            self._waiting_on_telegram_snap = None
            return

        log.info("Received camera snap, sending over Telegram")
        self.message_svc("ZmwTelegram", "send_photo", {'path': msg['snap_path']})
        self._waiting_on_telegram_snap = None

    def on_doorbell_button_pressed(self, msg):
        """Handle doorbell button press event."""
        url = self._public_url_base + self._cfg["doorbell_announce_sound"]
        log.info("Doorbell reports button pressed, announce '%s' over speakers", url)
        self.message_svc("ZmwSpeakerAnnounce", "play_asset", {
                            'vol': self._cfg.get("doorbell_announce_volume", "default"),
                            'public_www': url})

        snap_path = msg.get('snap_path')
        self._update_snap_directory(snap_path)
        self._door_stats.record_doorbell_press(snap_path)

        # Announce over own MQTT topic
        self.publish_own_svc_message("on_doorbell_pressed", {"snap_path": snap_path})

        if snap_path is None:
            log.warning("Doorbell button pressed but no snap available")
        else:
            log.info("Send visitor snap from doorbell camera")
            self.message_svc("ZmwWhatsapp", "send_photo",
                             {'path': snap_path, 'msg': "RING!"})
            self.message_svc("ZmwTelegram", "send_photo",
                             {'path': snap_path, 'msg': "RING!"})

    def on_door_motion_detected(self, msg):
        """Handle door motion detection event."""
        # Update history and stats (unconditionally, as this doesn't spam messages, the user needs to ask for it)
        snap_path = msg.get('path_to_img')
        self._door_open_scene.pet_timer()
        self._door_stats.record_motion_start(snap_path)
        self._update_snap_directory(snap_path)

        # Announce over own MQTT topic (before rate limiting, so subscribers always see it)
        self.publish_own_svc_message("on_motion_detected", {"snap_path": snap_path})

        if snap_path:
            self._door_stats.record_snap(snap_path)

        # Rate limit (update last motion time unconditionally, so that we extend the rate limit if messages
        # keep spamming)
        dt = time.time() - self._last_motion_detected_time
        self._last_motion_detected_time = time.time()
        if dt < 120:
            log.debug("Motion detected but rate limited (last event %.1fs ago)", dt)
            return

        log.info("Door reports motion! Sending snap over WA")
        self.message_svc("ZmwWhatsapp", "send_photo",
                         {'path': msg['path_to_img'], 'msg': "Motion detected"})

    def on_door_motion_cleared(self):
        """Handle door motion cleared event."""
        log.info("Door reports motion event cleared")
        self._door_stats.record_motion_end()
        self.publish_own_svc_message("on_motion_cleared", {})

    def on_door_motion_timeout(self):
        """Handle door motion timeout event."""
        log.warning("Motion event timedout, no vacancy reported")
        self._door_stats.record_motion_end()
        self.publish_own_svc_message("on_motion_cleared", {})

    def _update_snap_directory(self, snap_path):
        """Update the snap directory from a full snap path."""
        if snap_path is None:
            return
        if self._snap_directory is None:
            self._snap_directory = os.path.dirname(snap_path)
            log.info("Snap directory discovered: %s", self._snap_directory)

    def _get_snap(self, filename):
        """Serve a snap file by filename."""
        if self._snap_directory is None:
            return jsonify({'error': 'No snap directory available yet'}), 503

        # Prevent path traversal attacks
        if '/' in filename or '\\' in filename or '..' in filename:
            return jsonify({'error': 'Invalid filename'}), 400

        snap_path = os.path.join(self._snap_directory, filename)
        if not os.path.isfile(snap_path):
            return jsonify({'error': 'Snap not found'}), 404

        return send_file(snap_path, mimetype='image/jpeg')

    def _request_snap(self):
        log.info("User requested new snap via web UI")
        self.message_svc("ZmwReolinkCams", "snap", {"cam_host": self._cfg["doorbell_cam_host"]})
        return jsonify({'status': 'ok'})

service_runner(ZmwDoorman)
