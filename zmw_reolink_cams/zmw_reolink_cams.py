"""MQTT camera service with motion detection and recording."""
import os
import pathlib
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

    def on_doorbell_button_pressed(self, cam_host, snap_path, full_cam_msg):
        self._mqtt.on_doorbell_pressed(cam_host)
        self._mqtt.publish_own_svc_message("on_doorbell_button_pressed", {
            'event': 'on_doorbell_button_pressed',
            'cam_host': cam_host,
            'snap_path': snap_path,
            'full_cam_msg': full_cam_msg,
        })

    def on_motion_detected(self, cam_host, path_to_img, motion_level, full_cam_msg):
        self._mqtt.publish_own_svc_message("on_motion_detected", {
            'event': 'on_motion_detected',
            'cam_host': cam_host,
            'path_to_img': path_to_img,
            'motion_level': motion_level,
            'full_cam_msg': full_cam_msg,
        })

    def on_motion_cleared(self, cam_host, full_cam_msg):
        self._mqtt.publish_own_svc_message("on_motion_cleared", {
            'event': 'on_motion_cleared',
            'cam_host': cam_host,
            'full_cam_msg': full_cam_msg,
        })

    def on_motion_timeout(self, cam_host, timeout):
        self._mqtt.publish_own_svc_message("on_motion_timeout", {
            'event': 'on_motion_timeout',
            'cam_host': cam_host,
            'timeout': timeout,
        })

    def on_new_recording(self, cam_host, path):
        self._mqtt.publish_own_svc_message("on_new_recording", {
            'event': 'on_new_recording',
            'cam_host': cam_host,
            'path': path,
        })

    def on_recording_failed(self, cam_host, path):
        self._mqtt.publish_own_svc_message("on_recording_failed", {
            'event': 'on_recording_failed',
            'cam_host': cam_host,
            'path': path,
        })

    def on_reencoding_ready(self, cam_host, orig_path, reencode_path):
        self._mqtt.publish_own_svc_message("on_reencoding_ready", {
            'event': 'on_reencoding_ready',
            'cam_host': cam_host,
            'orig_path': orig_path,
            'reencode_path': reencode_path,
        })

    def on_reencoding_failed(self, cam_host, path):
        self._mqtt.publish_own_svc_message("on_reencoding_failed", {
            'event': 'on_reencoding_failed',
            'cam_host': cam_host,
            'path': path,
        })


class ZmwReolinkCams(ZmwMqttService):
    """ Bridge between Zmw services and multiple Reolink cams """
    DOORBELL_ALERT_DURATION_SECS = 60

    def __init__(self, cfg, www, sched):
        super().__init__(cfg, "zmw_reolink_cams", scheduler=sched)
        self._doorbell_pressed_at = {}  # cam_host -> timestamp

        # Initialize cameras from config array
        self.cams = {}
        for cam_cfg in cfg['cameras']:
            cam_host = cam_cfg['cam_host']
            merged_cfg = dict(cfg)
            merged_cfg.update(cam_cfg)
            webhook_url = f"{www.public_url_base}/cam/{cam_host}"
            cam = ZmwReolinkCam(merged_cfg, webhook_url=webhook_url, mqtt=self, scheduler=sched)
            self.cams[cam_host] = cam

            # Register webhook endpoint for this camera
            www.serve_url(f'/cam/{cam_host}', cam.on_cam_webhook, methods=['GET', 'POST'])

        # Initialize NVR
        self.nvr = Nvr(cfg['rec_path'], cfg.get('snap_path_on_movement'), www)

        # Register Flask routes
        www.serve_url('/ls_cams', self._get_online_cams)
        www.serve_url('/snap/<cam_host>', self._get_snap_for_cam)
        www.serve_url('/lastsnap/<cam_host>', self._get_last_snap_for_cam)
        www.serve_url('/record/<cam_host>', self._record_for_cam)

        # Register www directory
        wwwdir = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        www.register_www_dir(wwwdir)

        # Connect to all cameras
        for cam_host, cam in self.cams.items():
            log.info("Connecting to camera %s...", cam_host)
            cam.connect_bg()

    def on_doorbell_pressed(self, cam_host):
        """Record when a doorbell was pressed"""
        self._doorbell_pressed_at[cam_host] = time.time()

    def get_service_alerts(self):
        """Return alerts for any doorbell pressed within the last 60 seconds"""
        alerts = []
        now = time.time()
        for cam_host, pressed_at in self._doorbell_pressed_at.items():
            elapsed = now - pressed_at
            if elapsed < self.DOORBELL_ALERT_DURATION_SECS:
                secs_ago = int(elapsed)
                alerts.append(f"Doorbell {cam_host} pressed {secs_ago} seconds ago")
        for cam_host, cam in self.cams.items():
            if cam.failed_to_connect():
                alerts.append(f"Doorbell {cam_host} is not connected")
        return alerts

    def get_mqtt_description(self):
        return {
            "description": "Multi-camera Reolink service with motion detection, doorbell events, recording, and NVR-like web interface. Connects to Reolink cameras via webhook/ONVIF, broadcasts events over MQTT, and provides snapshot/recording controls.",
            "meta": self.get_service_meta(),
            "commands": {
                "snap": {
                    "description": "Take a snapshot from a camera. Response published on on_snap_ready",
                    "params": {"cam_host": "Camera host identifier"}
                },
                "rec": {
                    "description": "Start recording on a camera",
                    "params": {"cam_host": "Camera host identifier", "secs": "Recording duration in seconds"}
                },
                "ls_cams": {
                    "description": "List online cameras. Response published on ls_cams_reply",
                    "params": {}
                },
                "get_mqtt_description": {
                    "description": "Get MQTT API description. Response published on get_mqtt_description_reply",
                    "params": {}
                },
            },
            "announcements": {
                "on_snap_ready": {
                    "description": "Snapshot captured and ready",
                    "payload": {"event": "on_snap_ready", "cam_host": "Camera host identifier", "snap_path": "Local path to snapshot file"}
                },
                "on_doorbell_button_pressed": {
                    "description": "Doorbell button was pressed",
                    "payload": {"event": "on_doorbell_button_pressed", "cam_host": "Camera host", "snap_path": "Path to snapshot", "full_cam_msg": "Raw camera event data"}
                },
                "on_motion_detected": {
                    "description": "Camera detected motion",
                    "payload": {"event": "on_motion_detected", "cam_host": "Camera host", "path_to_img": "Path to motion snapshot", "motion_level": "Motion intensity level", "full_cam_msg": "Raw camera event data"}
                },
                "on_motion_cleared": {
                    "description": "Motion cleared by camera",
                    "payload": {"event": "on_motion_cleared", "cam_host": "Camera host", "full_cam_msg": "Raw camera event data"}
                },
                "on_motion_timeout": {
                    "description": "Motion event timed out without camera reporting clear",
                    "payload": {"event": "on_motion_timeout", "cam_host": "Camera host", "timeout": "Timeout value"}
                },
                "on_new_recording": {
                    "description": "A new recording completed and is available",
                    "payload": {"event": "on_new_recording", "cam_host": "Camera host", "path": "Local path to recording file"}
                },
                "on_recording_failed": {
                    "description": "Recording failed",
                    "payload": {"event": "on_recording_failed", "cam_host": "Camera host", "path": "Path of failed recording"}
                },
                "on_reencoding_ready": {
                    "description": "Re-encoding of a recording completed",
                    "payload": {"event": "on_reencoding_ready", "cam_host": "Camera host", "orig_path": "Original recording path", "reencode_path": "Re-encoded file path"}
                },
                "on_reencoding_failed": {
                    "description": "Re-encoding of a recording failed",
                    "payload": {"event": "on_reencoding_failed", "cam_host": "Camera host", "path": "Path of failed re-encode"}
                },
                "ls_cams_reply": {
                    "description": "Response to ls_cams. List of online camera host identifiers",
                    "payload": ["cam_host_1", "cam_host_2"]
                },
                "get_mqtt_description_reply": {
                    "description": "Response to get_mqtt_description. Full MQTT API description",
                    "payload": {"commands": {}, "announcements": {}}
                },
            }
        }

    def _get_online_cams(self):
        cams = []
        for cam_host, cam in self.cams.items():
            if not cam.failed_to_connect():
                cams.append(cam_host)
        return cams

    def _get_snap_for_cam(self, cam_host):
        """Get a new snapshot from specific camera"""
        if cam_host not in self.cams:
            return jsonify({'error': f'Unknown camera {cam_host}'}), 404
        snap_path = self.cams[cam_host].get_snapshot()
        if snap_path is None:
            return jsonify({'error': 'Failed to get snapshot from camera'}), 500
        return send_file(snap_path, mimetype='image/jpeg')

    def _get_last_snap_for_cam(self, cam_host):
        """Get the last saved snapshot from specific camera"""
        if cam_host not in self.cams:
            return jsonify({'error': f'Unknown camera {cam_host}'}), 404
        snap_path = self.cams[cam_host].get_last_snapshot_path()
        if snap_path is None:
            return jsonify({'error': 'No snapshot available'}), 404
        return send_file(snap_path, mimetype='image/jpeg')

    def _record_for_cam(self, cam_host):
        """Start video recording on specific camera"""
        if cam_host not in self.cams:
            return jsonify({'error': f'Unknown camera {cam_host}'}), 404
        try:
            secs = request.args.get('secs', type=int)
            if secs is None or secs < 5 or secs > 120:
                return jsonify({'error': f'Invalid duration {secs}, must be [5, 120]'}), 400

            self.cams[cam_host].start_recording(secs)
            return jsonify({'status': 'ok', 'duration': secs, 'cam_host': cam_host})
        except ValueError:
            return jsonify({'error': 'Invalid secs parameter'}), 400

    def stop(self):
        """Cleanup on shutdown"""
        log.info("Stopping camera service: disconnecting from cameras...")
        for cam_host, cam in self.cams.items():
            log.info("Disconnecting from camera %s...", cam_host)
            cam.disconnect()
        super().stop()

    def on_service_received_message(self, subtopic, payload):
        """Handle MQTT messages for snapshot and recording commands."""
        # Ignore self-echo from our own announcements and reply topics
        if subtopic.endswith('_reply'):
            return
        if subtopic.startswith('on_'):
            return

        cam_host = payload.get('cam_host') if payload else None

        match subtopic:
            case "snap":
                cam = self.cams.get(cam_host)
                if cam is None:
                    log.warning("Received snap for unknown camera: %s", cam_host)
                    return
                self.publish_own_svc_message("on_snap_ready", {
                    'event': 'on_snap_ready',
                    'cam_host': cam.get_cam_host(),
                    'snap_path': cam.get_snapshot(),
                })
            case "rec":
                cam = self.cams.get(cam_host)
                if cam is None:
                    log.warning("Received rec for unknown camera: %s", cam_host)
                    return
                cam.start_recording(payload.get('secs', None) if payload else None)
            case "ls_cams":
                self.publish_own_svc_message("ls_cams_reply",
                    self._get_online_cams())
            case "get_mqtt_description":
                self.publish_own_svc_message("get_mqtt_description_reply",
                    self.get_mqtt_description())
            case _:
                log.warning("Ignoring unknown message '%s'", subtopic)

service_runner(ZmwReolinkCams)
