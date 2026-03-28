"""Visitor detection service: detects and identifies visitors from doorbell camera snapshots."""
import os
import pathlib
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from flask import jsonify

from zzmw_lib.service_runner import service_runner
from zzmw_lib.zmw_mqtt_service import ZmwMqttService
from zzmw_lib.logs import build_logger

from visitor_detector import VisitorDetector

log = build_logger("ZmwVisitorDetect")


class ZmwVisitorDetect(ZmwMqttService):

    def __init__(self, cfg, www, sched):
        super().__init__(cfg, "zmw_visitor_detect", scheduler=sched,
                         svc_deps=['ZmwReolinkCams', 'ZmwSpeakerAnnounce', 'ZmwTelegram'])
        self._cfg = cfg
        self._doorbell_cam_host = cfg["doorbell_cam_host"]
        self._cooldown_secs = cfg.get("detection_cooldown_secs", 300)

        self._detector = VisitorDetector(
            models_dir=cfg.get("models_dir", "./models"),
            state_path="./run_state.json",
            crops_dir=cfg.get("detection_crops_dir", "./detection_crops"),
            sighting_dedup_gap_secs=cfg.get("sighting_dedup_gap_secs", 1800),
            max_crops=cfg.get("max_crops", 50),
        )

        # Per-person cooldown: {name: last_announced_epoch}
        self._announce_cooldowns = {}
        # Last N detections for web endpoint
        self._recent_detections = deque(maxlen=20)
        # Single-threaded executor so detection doesn't block MQTT loop
        self._detect_executor = ThreadPoolExecutor(max_workers=1)

        www.register_www_dir(os.path.join(pathlib.Path(__file__).parent.resolve(), 'www'), '/')
        www.register_www_dir(cfg.get("detection_crops_dir", "./detection_crops"), '/crops/')
        www.serve_url('/detections', lambda: jsonify(list(self._recent_detections)))

    def get_mqtt_description(self):
        return {
            "commands": {
                "get_mqtt_description": {
                    "description": "Service description",
                    "params": {}
                },
            },
            "announcements": {
                "on_detection": {
                    "description": "Visitor detection event",
                    "payload": {
                        "timestamp": "float epoch",
                        "event": "new_face_detected | new_visitor_recognized | visitor_recognized | person_no_face_detected",
                        "name": "Person name or null",
                        "sightings": "int or null",
                        "person_confidence": "float",
                        "bbox": "[x1, y1, x2, y2]",
                        "snap_path": "Source image path",
                        "crop_path": "Cropped person image path",
                    }
                },
                "get_mqtt_description_reply": {
                    "description": "Service interface",
                    "payload": {"commands": "...", "announcements": "..."}
                },
            }
        }

    def on_service_received_message(self, subtopic, payload):
        match subtopic:
            case "get_mqtt_description":
                self.publish_own_svc_message("get_mqtt_description_reply",
                                             self.get_mqtt_description())

    def on_dep_published_message(self, svc_name, subtopic, msg):
        match svc_name:
            case 'ZmwReolinkCams':
                if msg.get("cam_host") != self._doorbell_cam_host:
                    return
                match subtopic:
                    case "on_doorbell_button_pressed":
                        self._submit_detection(msg.get("snap_path"), is_doorbell=True)
                    case "on_motion_detected":
                        self._submit_detection(msg.get("path_to_img"), is_doorbell=False)
                    case _:
                        pass
            case 'ZmwSpeakerAnnounce' | 'ZmwTelegram':
                pass

    def _submit_detection(self, snap_path, is_doorbell):
        if not snap_path:
            log.warning("Detection requested but no image path provided")
            return
        if not os.path.isfile(snap_path):
            log.warning("Snap file does not exist: %s", snap_path)
            return
        future = self._detect_executor.submit(self._run_detection, snap_path, is_doorbell)
        future.add_done_callback(self._detection_done_cb)

    @staticmethod
    def _detection_done_cb(future):
        exc = future.exception()
        if exc:
            log.error("Detection failed: %s", exc)

    def _run_detection(self, snap_path, is_doorbell):
        result = self._detector.detect(snap_path)

        for visitor in result['visitors']:
            visitor['snap_path'] = snap_path
            self._recent_detections.append(visitor)
            self.publish_own_svc_message("on_detection", visitor)

            if not self._should_announce(visitor['name'], visitor['timestamp'], is_doorbell):
                continue

            if visitor['event'] == 'new_visitor_recognized':
                self.message_svc("ZmwTelegram", "send_photo",
                                 {"path": visitor['crop_path'],
                                  "msg": f"New visitor recorded: {visitor['name']}"})

            elif visitor['event'] == 'visitor_recognized':
                self.message_svc("ZmwSpeakerAnnounce", "tts",
                                 {"msg": f"{visitor['name']} is at the door", "lang": "en"})

    def _should_announce(self, name, now, is_doorbell):
        if name is None:
            return False
        if is_doorbell:
            self._announce_cooldowns[name] = now
            return True
        last = self._announce_cooldowns.get(name, 0)
        if now - last < self._cooldown_secs:
            return False
        self._announce_cooldowns[name] = now
        return True


service_runner(ZmwVisitorDetect)
