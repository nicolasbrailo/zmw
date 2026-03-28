"""Visitor detection service: detects and identifies visitors from doorbell camera snapshots."""
import os
import pathlib
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from flask import jsonify

from zzmw_lib.service_runner import service_runner
from zzmw_lib.zmw_mqtt_service import ZmwMqttService
from zzmw_lib.logs import build_logger
from zzmw_lib.runtime_state_cache import runtime_state_cache_get, runtime_state_cache_set

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
            state_path="./known_people.json",
            crops_dir=cfg.get("detection_crops_dir", "./detection_crops"),
            sighting_dedup_gap_secs=cfg.get("sighting_dedup_gap_secs", 1800),
            max_crops=cfg.get("max_crops", 50),
        )

        # Per-person cooldown: {name: last_announced_epoch}
        self._announce_cooldowns = {}
        # Last N detections for web endpoint
        self._recent_detections = deque(runtime_state_cache_get("recent_detections") or [], maxlen=20)
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
                        log.info("Received doorbell event, will schedule visitor detection")
                        self._submit_detection(msg.get("snap_path"), is_doorbell=True)
                    case "on_motion_detected":
                        log.info("Received motion event, will schedule visitor detection")
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
        if len(result['visitors']) == 0:
            log.info("Snap %s received, no people detected", snap_path)
            return

        announce_names = []
        last_crop = None
        should_announce = False

        for visitor in result['visitors']:
            visitor['snap_path'] = snap_path
            log.info("%s: %s confidence=%.2f sightings=%s",
                      visitor['event'], visitor['name'] or 'unknown face',
                     visitor['person_confidence'], visitor['sightings'])
            self._recent_detections.append(visitor)
            runtime_state_cache_set("recent_detections", list(self._recent_detections))
            self.publish_own_svc_message("on_detection", visitor)
            last_crop = visitor['crop_path']

            if self._should_announce(visitor['name'], visitor['timestamp'], is_doorbell):
                should_announce = True
                announce_names.append(visitor['name'])

        if not should_announce:
            return

        if announce_names:
            if len(announce_names) == 1:
                msg = f"{announce_names[0]} is at the door"
            else:
                msg = f"{', '.join(announce_names)} are at the door"
            self.message_svc("ZmwSpeakerAnnounce", "tts", {"msg": msg, "lang": "en"})

        if last_crop:
            self.message_svc("ZmwTelegram", "send_photo",
                             {"path": last_crop, "msg": msg if announce_names else "Visitor detected"})

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
