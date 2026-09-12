"""MQTT camera service with motion detection and recording."""
import os
import pathlib
import re
import time

from flask import send_file, request, jsonify

from zzmw_lib.zmw_mqtt_service import ZmwMqttService
from zzmw_lib.logs import build_logger
from zzmw_lib.service_runner import service_runner

from reolink import ReolinkDoorbell
from nvrish import Nvr

log = build_logger("ZmwReolinkCams")


class ZmwReolinkCam(ReolinkDoorbell):
    """ Link Reolink events to mqtt b-casts """

    def __init__(self, cfg, webhook_url, mqtt, scheduler):
        super().__init__(cfg, webhook_url, scheduler)
        self._mqtt = mqtt
        self._is_doorbell_cam = cfg.get('is_doorbell', False)

    def _publish_event(self, event, cam_host, payload):
        self._mqtt.publish_own_svc_message(event, {
            'event': event,
            'cam_alias': self._cam_alias,
            'cam_host': cam_host,
            **payload,
        })

    def on_doorbell_button_pressed(self, cam_host, snap_path, full_cam_msg):
        self._mqtt.on_doorbell_pressed(self._cam_alias)
        self._publish_event("on_doorbell_button_pressed", cam_host, {
            'snap_path': snap_path,
            'full_cam_msg': full_cam_msg,
        })

    def on_motion_detected(self, cam_host, path_to_img, motion_level, full_cam_msg):
        self._publish_event("on_motion_detected", cam_host, {
            'path_to_img': path_to_img,
            'motion_level': motion_level,
            'full_cam_msg': full_cam_msg,
        })

    def on_motion_cleared(self, cam_host, full_cam_msg):
        self._publish_event("on_motion_cleared", cam_host, {
            'full_cam_msg': full_cam_msg,
        })

    def on_motion_timeout(self, cam_host, timeout):
        self._publish_event("on_motion_timeout", cam_host, {
            'timeout': timeout,
        })

    def on_new_recording(self, cam_host, path):
        self._publish_event("on_new_recording", cam_host, {
            'path': path,
        })

    def on_recording_failed(self, cam_host, path):
        self._publish_event("on_recording_failed", cam_host, {
            'path': path,
        })

    def on_reencoding_ready(self, cam_host, orig_path, reencode_path):
        self._publish_event("on_reencoding_ready", cam_host, {
            'orig_path': orig_path,
            'reencode_path': reencode_path,
        })

    def on_reencoding_failed(self, cam_host, path):
        self._publish_event("on_reencoding_failed", cam_host, {
            'path': path,
        })


class ZmwReolinkCams(ZmwMqttService):
    """ Bridge between Zmw services and multiple Reolink cams """
    DOORBELL_ALERT_DURATION_SECS = 60
    # Aliases are used in URLs and as directory names for recordings and snapshots
    CAM_ALIAS_RE = re.compile(r'^[A-Za-z0-9_-]+$')

    def __init__(self, cfg, www, sched):
        super().__init__(cfg, "zmw_reolink_cams", scheduler=sched)
        self._doorbell_pressed_at = {}  # cam_alias -> timestamp

        # Initialize cameras from config array. Cams are keyed by alias, as the host may change.
        self.cams = {}
        for cam_cfg in cfg['cameras']:
            cam_host = cam_cfg['cam_host']
            cam_alias = cam_cfg.get('cam_alias')
            if not cam_alias or not self.CAM_ALIAS_RE.match(cam_alias):
                raise ValueError(f"Camera {cam_host} needs a 'cam_alias' made of letters, digits, '_' or '-', "
                                 f"got '{cam_alias}'")
            if cam_alias in self.cams:
                raise ValueError(f"Duplicated cam_alias '{cam_alias}' for cameras "
                                 f"{self.cams[cam_alias].get_cam_host()} and {cam_host}")
            merged_cfg = dict(cfg)
            merged_cfg.update(cam_cfg)
            webhook_url = f"{www.public_url_base}/cam/{cam_alias}"
            cam = ZmwReolinkCam(merged_cfg, webhook_url=webhook_url, mqtt=self, scheduler=sched)
            self.cams[cam_alias] = cam

            # Register webhook endpoint for this camera
            www.serve_url(f'/cam/{cam_alias}', cam.on_cam_webhook, methods=['GET', 'POST'])

        # Initialize NVR
        self.nvr = Nvr(cfg['rec_path'], cfg.get('snap_path_on_movement'), www)

        # Register Flask routes
        www.serve_url('/ls_cams', self._get_online_cam_aliases)
        www.serve_url('/snap/<cam_alias>', self._get_snap_for_cam)
        www.serve_url('/lastsnap/<cam_alias>', self._get_last_snap_for_cam)
        www.serve_url('/record/<cam_alias>', self._record_for_cam)

        # Register www directory
        wwwdir = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        www.register_www_dir(wwwdir)

        # Connect to all cameras
        for cam_alias, cam in self.cams.items():
            log.info("Connecting to camera %s (%s)...", cam_alias, cam.get_cam_host())
            cam.connect_bg()

    def _resolve_cam(self, payload):
        """Find the cam a command targets: by cam_alias, or by cam_host as a fallback."""
        if not payload:
            return None
        if 'cam_alias' in payload:
            return self.cams.get(payload['cam_alias'])
        return next((cam for cam in self.cams.values()
                     if cam.get_cam_host() == payload.get('cam_host')), None)

    def on_doorbell_pressed(self, cam_alias):
        """Record when a doorbell was pressed"""
        self._doorbell_pressed_at[cam_alias] = time.time()

    def get_service_alerts(self):
        """Return alerts for any doorbell pressed within the last 60 seconds"""
        alerts = []
        now = time.time()
        for cam_alias, pressed_at in self._doorbell_pressed_at.items():
            elapsed = now - pressed_at
            if elapsed < self.DOORBELL_ALERT_DURATION_SECS:
                secs_ago = int(elapsed)
                alerts.append(f"Doorbell {cam_alias} pressed {secs_ago} seconds ago")
        for cam in self.cams.values():
            if cam.failed_to_connect():
                alerts.append(f"Camera {cam.get_cam_alias()} ({cam.get_cam_host()}) is not connected")
        return alerts

    def _get_online_cam_aliases(self):
        return [alias for alias, cam in self.cams.items() if not cam.failed_to_connect()]

    def _build_llm_grammar_values(self):
        names = self._get_online_cam_aliases()
        if names:
            return {'cam_alias': names}
        return {}

    def _build_llm_context_extra(self):
        names = self._get_online_cam_aliases()
        if not names:
            return ''
        return "Cameras: " + ', '.join(names)

    def get_mqtt_description(self):
        return {
            "description": "Multi-camera Reolink service with motion detection, doorbell events, recording, NVR. "\
                           "Connects via webhook/ONVIF, broadcasts events over MQTT, expose snapshot/recording controls.",
            "meta": self.get_service_meta(),
            # MQTT data flow; feeds the map in the top-level README (scripts/build_mqtt_map.py).
            # Empty: talks to Reolink cameras over webhook/ONVIF and only publishes to its own topic.
            "reads_mqtt_topic": [],
            "writes_mqtt_topic": [],
            "known_cameras": [
                {"cam_alias": alias, "cam_host": cam.get_cam_host(),
                 "is_doorbell": cam._is_doorbell_cam}
                for alias, cam in self.cams.items()
                if not cam.failed_to_connect()
            ],
            "llm_skip_commands": ["ls_cams"],
            "llm_context_extra": self._build_llm_context_extra(),
            "llm_grammar_values": self._build_llm_grammar_values(),
            "commands": {
                "snap": {
                    "description": "Cam snapshot. Response published on_snap_ready",
                    "params": {"cam_alias": "Camera name"}
                },
                "rec": {
                    "description": "Start recording",
                    "params": {"cam_alias": "Camera name", "secs": "Duration (seconds)"}
                },
                "ls_cams": {
                    "description": "List all configured cams, and whether they are online. Response on ls_cams_reply",
                    "params": {}
                },
                "get_mqtt_description": {
                    "description": "Service description",
                    "params": {}
                },
            },
            "announcements": {
                "on_snap_ready": {
                    "description": "Snapshot ready",
                    "payload": {"event": "on_snap_ready", "cam_alias": "Cam name", "cam_host": "Cam IP (may change, use cam_alias)", "snap_path": "Local path to snapshot file"}
                },
                "on_doorbell_button_pressed": {
                    "description": "Doorbell button was pressed",
                    "payload": {"event": "on_doorbell_button_pressed", "cam_alias": "Cam name", "cam_host": "Cam IP (may change, use cam_alias)", "snap_path": "Path to snapshot", "full_cam_msg": "Raw cam event"}
                },
                "on_motion_detected": {
                    "description": "Camera detected motion",
                    "payload": {"event": "on_motion_detected", "cam_alias": "Cam name", "cam_host": "Cam IP (may change, use cam_alias)", "path_to_img": "Snapshot path", "motion_level": "Motion confidence", "full_cam_msg": "Raw cam event"}
                },
                "on_motion_cleared": {
                    "description": "Motion cleared by camera",
                    "payload": {"event": "on_motion_cleared", "cam_alias": "Cam name", "cam_host": "Cam IP (may change, use cam_alias)", "full_cam_msg": "Raw cam event"}
                },
                "on_motion_timeout": {
                    "description": "Motion event timed out without camera reporting clear",
                    "payload": {"event": "on_motion_timeout", "cam_alias": "Cam name", "cam_host": "Cam IP (may change, use cam_alias)", "timeout": "seconds"}
                },
                "on_new_recording": {
                    "description": "New recording completed and is available",
                    "payload": {"event": "on_new_recording", "cam_alias": "Cam name", "cam_host": "Cam IP (may change, use cam_alias)", "path": "Local path to recording file"}
                },
                "on_recording_failed": {
                    "description": "Recording failed",
                    "payload": {"event": "on_recording_failed", "cam_alias": "Cam name", "cam_host": "Cam IP (may change, use cam_alias)", "path": "Path of failed recording"}
                },
                "on_reencoding_ready": {
                    "description": "Re-encoding of a recording completed",
                    "payload": {"event": "on_reencoding_ready", "cam_alias": "Cam name", "cam_host": "Cam IP (may change, use cam_alias)", "orig_path": "Original recording path", "reencode_path": "Re-encoded file path"}
                },
                "on_reencoding_failed": {
                    "description": "Re-encoding of a recording failed",
                    "payload": {"event": "on_reencoding_failed", "cam_alias": "Cam name", "cam_host": "Cam IP (may change, use cam_alias)", "path": "Path of failed re-encode"}
                },
                "ls_cams_reply": {
                    "description": "All configured cams, including offline ones",
                    "payload": [{"cam_alias": "Cam name", "online": "bool"}]
                },
                "get_mqtt_description_reply": {
                    "description": "Service description",
                    "payload": {"commands": {}, "announcements": {}}
                },
            }
        }

    def _get_snap_for_cam(self, cam_alias):
        """Get a new snapshot from specific camera"""
        if cam_alias not in self.cams:
            return jsonify({'error': f'Unknown camera {cam_alias}'}), 404
        snap_path = self.cams[cam_alias].get_snapshot()
        if snap_path is None:
            return jsonify({'error': 'Failed to get snapshot from camera'}), 500
        return send_file(snap_path, mimetype='image/jpeg')

    def _get_last_snap_for_cam(self, cam_alias):
        """Get the last saved snapshot from specific camera"""
        if cam_alias not in self.cams:
            return jsonify({'error': f'Unknown camera {cam_alias}'}), 404
        snap_path = self.cams[cam_alias].get_last_snapshot_path()
        if snap_path is None:
            return jsonify({'error': 'No snapshot available'}), 404
        return send_file(snap_path, mimetype='image/jpeg')

    def _record_for_cam(self, cam_alias):
        """Start video recording on specific camera"""
        if cam_alias not in self.cams:
            return jsonify({'error': f'Unknown camera {cam_alias}'}), 404
        try:
            secs = request.args.get('secs', type=int)
            if secs is None or secs < 5 or secs > 120:
                return jsonify({'error': f'Invalid duration {secs}, must be [5, 120]'}), 400

            self.cams[cam_alias].start_recording(secs)
            return jsonify({'status': 'ok', 'duration': secs, 'cam_alias': cam_alias})
        except ValueError:
            return jsonify({'error': 'Invalid secs parameter'}), 400

    def stop(self):
        """Cleanup on shutdown"""
        log.info("Stopping camera service: disconnecting from cameras...")
        for cam_alias, cam in self.cams.items():
            log.info("Disconnecting from camera %s...", cam_alias)
            cam.disconnect()
        super().stop()

    def on_service_received_message(self, subtopic, payload):
        """Handle MQTT messages for snapshot and recording commands."""
        # Ignore self-echo from our own announcements and reply topics
        if subtopic.endswith('_reply'):
            return
        if subtopic.startswith('on_'):
            return

        match subtopic:
            case "snap":
                cam = self._resolve_cam(payload)
                if cam is None:
                    log.warning("Received snap for unknown camera: %s", payload)
                    return
                self.publish_own_svc_message("on_snap_ready", {
                    'event': 'on_snap_ready',
                    'cam_alias': cam.get_cam_alias(),
                    'cam_host': cam.get_cam_host(),
                    'snap_path': cam.get_snapshot(),
                })
            case "rec":
                cam = self._resolve_cam(payload)
                if cam is None:
                    log.warning("Received rec for unknown camera: %s", payload)
                    return
                cam.start_recording(payload.get('secs', None) if payload else None)
            case "ls_cams":
                self.publish_own_svc_message("ls_cams_reply", [
                    {'cam_alias': alias, 'online': not cam.failed_to_connect()}
                    for alias, cam in self.cams.items()])
            case "get_mqtt_description":
                self.publish_own_svc_message("get_mqtt_description_reply",
                    self.get_mqtt_description())
            case _:
                log.warning("Ignoring unknown message '%s'", subtopic)

service_runner(ZmwReolinkCams)
