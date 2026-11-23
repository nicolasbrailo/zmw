"""Visitor detection service: detects people at the doorbell and identifies them, discovering frequent visitors.

A camera event (motion or ring) from ZmwReolinkCams opens a session on the camera's RTSP main stream; each
session runs the pipeline in session.py and publishes at most one event per person. Design and the evidence
behind every model and threshold: ~/src/visitordetect/ARCH.md and CLAUDE.md.
"""
import json
import os
import pathlib
import re
import shutil
import threading
import time
from datetime import datetime, timedelta

from flask import abort, jsonify, request

from zzmw_lib.logs import build_logger
from zzmw_lib.path_allowlist import PathAllowlist
from zzmw_lib.service_runner import service_runner
from zzmw_lib.zmw_mqtt_service import ZmwMqttService

from frame_source import FrameSource, HwDecoder
from identity_store import IdentityStore
from models import Models, missing_models
from session import Session
from visit_images import NotificationImages, RecordingFaces
from visitor_config import with_defaults

log = build_logger("ZmwVisitorDetect")

_SESSION_ID_RE = re.compile(r'^[\w-]+$')


class ZmwVisitorDetect(ZmwMqttService):

    def __init__(self, cfg, www, sched):
        super().__init__(cfg, "zmw_visitor_detect", scheduler=sched, svc_deps=['ZmwReolinkCams'])
        self._cfg = with_defaults(cfg)
        # inject_clip reads whatever path it's given (MQTT and HTTP), and faces are saved next to the recordings
        # ZmwReolinkCams announces: only inside allowed_paths
        self._recordings_allowlist = PathAllowlist(self._cfg, "recordings")
        self._sched = sched
        self._data_dir = os.path.abspath(self._cfg['data_dir'])
        os.makedirs(os.path.join(self._data_dir, 'sessions'), exist_ok=True)
        self._store = IdentityStore(self._data_dir, self._cfg)
        self._hw = HwDecoder(self._cfg['hw_decode'], self._cfg['hw_decode_device'])
        self._notification_imgs, self._notification_imgs_error = None, None
        if self._cfg['notification_img_dir']:
            try:
                self._notification_imgs = NotificationImages(self._cfg['notification_img_dir'])
            except OSError as ex:
                self._notification_imgs_error = f"Events will have no notification images: {ex}"
                log.error(self._notification_imgs_error)
        self._recording_faces = RecordingFaces(self._recordings_allowlist) \
            if self._cfg['faces_next_to_recordings'] else None

        self._models = None
        self._models_error = None
        self._models_lock = threading.Lock()
        try:
            self._models = Models(self._cfg['models_dir'], self._cfg['inference'],
                                  os.path.join(self._data_dir, 'model_cache'))
            log.info("Models running on %s", self._models.inference_description)
        except FileNotFoundError as ex:
            # Not downloaded yet: run without models (events are ignored), the Status page says what to do
            self._models_error = f"Can't load models: {ex}"
            log.error(self._models_error)
        except Exception as ex:
            # The configured backend can't run: refuse to start rather than use another one (a different backend
            # would mix its embeddings with the stored ones)
            log.error("Refusing to start: inference backend '%s' unavailable: %s", self._cfg['inference'], ex)
            raise

        # cam_alias -> running Session
        self._sessions = {}
        self._sessions_lock = threading.Lock()
        self._cam_errors = {}
        self._last_session_error = None

        www.register_www_dir(os.path.join(pathlib.Path(__file__).parent.resolve(), 'www'), '/')
        www.register_www_dir(self._data_dir, '/data/')
        www.serve_url('/status', self._www_status)
        www.serve_url('/sessions', self._www_sessions)
        www.serve_url('/session/<session_id>', self._www_session)
        www.serve_url('/visitors', lambda: jsonify(self._store.identities()))
        www.serve_url('/unknown', lambda: jsonify(self._store.unknown_clusters()))
        www.serve_url('/admin/<op>', self._www_admin, methods=['PUT'])
        www.serve_url('/inject_clip', self._www_inject_clip, methods=['PUT'])

    def get_mqtt_description(self):
        return {
            "description": "Visitor detection: people at the doorbell, face identification, discovery of frequent "
                           "visitors. One event per person per camera session.",
            "meta": self.get_service_meta(),
            # MQTT data flow; feeds the map in the top-level README (scripts/build_mqtt_map.py).
            # Reads: motion/ring events (with RTSP URLs) that open a capture session, and finished recordings (faces
            # are saved next to them).
            "reads_mqtt_topic": ["zmw_reolink_cams"],
            # Writes: asks ZmwReolinkCams for its camera list, to check the configured cams exist.
            "writes_mqtt_topic": ["zmw_reolink_cams"],
            "commands": {
                "inject_clip": {
                    "description": "Test the pipeline end to end: play a recorded clip as if it were the camera's live "
                                   "stream. It's a real session: it fires events and feeds the identity store. "
                                   "Response on inject_clip_reply",
                    "params": {"cam_alias": "Camera to impersonate", "path": "Absolute path to a clip on the server"}
                },
            },
            "announcements": {
                "on_person_detected": {
                    "description": "First person seen in a session (from the person detector, or from a face if "
                                   "that came first). Once per session: faceless people can't be told apart",
                    "payload": {"event": "on_person_detected", "cam_alias": "Camera", "session_id": "Session id",
                                "trigger": "motion, ring or injected (a test clip, see inject_clip)",
                                "timestamp": "float epoch", "t": "Seconds into the session",
                                "day_night": "day or night", "via": "person_detector or face",
                                "conf": "Person confidence (null if via face)",
                                "person_count": "People in that frame", "crop_path": "Person crop (local path)",
                                "notify_img_path": "Large person crop (or face, if via face) in notification_img_dir, "
                                                   "for notifications; null if not configured"}
                },
                "on_face_detected": {
                    "description": "A face good enough to identify, of someone not known (yet). Once per person "
                                   "per session",
                    "payload": {"event": "on_face_detected", "cam_alias": "Camera", "session_id": "Session id",
                                "trigger": "motion, ring or injected",
                                "timestamp": "float epoch", "t": "Seconds into the session", "day_night": "day",
                                "track_id": "Face track in the session", "gated_faces": "Faces used",
                                "closest": "Closest known visitor id or null", "closest_sim": "Its similarity",
                                "face_crop_path": "Aligned 112px face", "context_crop_path": "Crop around the face",
                                "notify_img_path": "Large crop around the face in notification_img_dir, or null"}
                },
                "on_face_identified": {
                    "description": "A known visitor's face. Once per visitor per session",
                    "payload": {"event": "on_face_identified", "cam_alias": "Camera", "session_id": "Session id",
                                "trigger": "motion, ring or injected",
                                "timestamp": "float epoch", "t": "Seconds into the session", "day_night": "day",
                                "visitor_id": "Stable id, eg visitor_3", "name": "Display name (config visitor_names)",
                                "sim": "Similarity", "upgraded": "True if first reported as on_face_detected",
                                "track_id": "Face track in the session", "gated_faces": "Faces used",
                                "face_crop_path": "Aligned 112px face", "context_crop_path": "Crop around the face",
                                "notify_img_path": "Large crop around the face in notification_img_dir, or null"}
                },
                "on_new_frequent_visitor": {
                    "description": "Discovery promoted a recurring unknown face to a visitor (after a session ends)",
                    "payload": {"event": "on_new_frequent_visitor", "cam_alias": "Camera", "session_id": "Session id",
                                "trigger": "motion, ring or injected",
                                "timestamp": "float epoch", "visitor_id": "Stable id, eg visitor_3",
                                "name": "Display name", "visits": "Visits seen in", "days": "Days seen on",
                                "face_crop_paths": "A few crops of this visitor",
                                "notify_img_path": "One of them, copied to notification_img_dir, or null"}
                },
                "inject_clip_reply": {
                    "description": "Response to inject_clip",
                    "payload": {"session_id": "Session started, or null", "error": "Why it wasn't started, or null"}
                },
            }
        }

    def on_service_received_message(self, subtopic, payload):
        try:
            self._on_command(subtopic, payload)
        except Exception:  # pylint: disable=broad-except
            log.error("Failed to handle command %s", subtopic, exc_info=True)

    def _on_command(self, subtopic, payload):
        match subtopic:
            case "get_mqtt_description":
                self.publish_own_svc_message("get_mqtt_description_reply", self.get_mqtt_description())
            case "inject_clip":
                payload = payload if isinstance(payload, dict) else {}
                session_id, err = self._inject_clip(payload.get('cam_alias'), payload.get('path'))
                if err:
                    log.error("inject_clip: %s", err)
                self.publish_own_svc_message("inject_clip_reply", {"session_id": session_id, "error": err})

    def get_service_alerts(self):
        alerts = list(self._cam_errors.values())
        if self._models_error:
            alerts.append(self._models_error)
        if self._last_session_error:
            alerts.append(self._last_session_error)
        if self._notification_imgs_error:
            alerts.append(self._notification_imgs_error)
        return alerts

    def stop(self):
        with self._sessions_lock:
            for s in self._sessions.values():
                s.stop()
        super().stop()

    # ------------------------------------------------------------------ camera events

    def on_service_came_up(self, service_name):
        if service_name == "ZmwReolinkCams":
            # Delay the request: our subscription to the service may not be ready yet, so asking right away could
            # lose the reply.
            self._sched.add_job(lambda: self.message_svc("ZmwReolinkCams", "ls_cams", {}),
                                trigger='date', run_date=datetime.now() + timedelta(seconds=3))

    def _check_cams_exist(self, cams):
        known = {c.get("cam_alias"): c for c in cams}
        self._cam_errors = {}
        for alias in self._cfg['cam_aliases']:
            if alias not in known:
                self._cam_errors[alias] = (f"cam_alias '{alias}' is not a camera in ZmwReolinkCams "
                                           f"(known cams: {', '.join(known) or 'none'})")
                log.error(self._cam_errors[alias])
            elif not known[alias].get("online"):
                log.warning("Cam '%s' found in ZmwReolinkCams, but it's offline", alias)

    def on_dep_published_message(self, svc_name, subtopic, msg):
        try:
            self._on_camera_message(svc_name, subtopic, msg)
        except Exception:  # pylint: disable=broad-except
            log.error("Failed to handle %s/%s", svc_name, subtopic, exc_info=True)

    def _on_camera_message(self, svc_name, subtopic, msg):
        if svc_name != 'ZmwReolinkCams':
            return
        if subtopic == "ls_cams_reply":
            self._check_cams_exist(msg)
            return
        if not isinstance(msg, dict) or msg.get("cam_alias") not in self._cfg['cam_aliases']:
            return
        match subtopic:
            case "on_motion_started":
                self._start_or_extend(msg, 'motion')
            case "on_doorbell_ring":
                self._start_or_extend(msg, 'ring')
            case "on_new_recording":
                if self._recording_faces is not None:
                    self._recording_faces.add_recording(msg['cam_alias'], msg.get('path'))
            case "on_motion_cleared" | "on_motion_timeout":
                # Only logged: the camera clears motion while someone stands still at the door, the session's
                # own stop rules are better
                log.debug("%s: %s", msg.get("cam_alias"), subtopic)
            case _:
                pass

    def _start_or_extend(self, msg, trigger):
        cam = msg['cam_alias']
        with self._sessions_lock:
            running = self._sessions.get(cam)
            if running is not None:
                log.info("%s event for %s extends session %s", trigger, cam, running.id)
                running.extend()
                return
        url = (msg.get('rtsp_urls') or {}).get('main')
        if not url:
            log.error("%s event for %s has no main RTSP URL, can't start a session", trigger, cam)
            return
        _, err = self._start_session(
            cam, trigger, lambda: FrameSource.rtsp(url, self._cfg['fps'], self._cfg['stream_backlog_s'], self._hw))
        if err:
            log.error("%s event for %s ignored: %s", trigger, cam, err)

    def _inject_clip(self, cam, path):
        """Plays a recorded clip through the pipeline as if it were cam's live stream. Returns (session_id, error).
        The session is a real one: it fires MQTT events and feeds the identity store, like a visit would."""
        if cam not in self._cfg['cam_aliases']:
            return None, f"cam_alias '{cam}' is not one of {self._cfg['cam_aliases']}"
        if not self._recordings_allowlist.check(path):
            return None, f"'{path}' is not inside allowed_paths {self._recordings_allowlist.allowed_dirs}"
        if not isinstance(path, str) or not os.path.isabs(path) or not os.path.isfile(path):
            return None, f"'{path}' is not an absolute path to an existing file"
        session_id, err = self._start_session(
            cam, 'injected',
            lambda: FrameSource.injected(path, self._cfg['fps'], self._cfg['stream_backlog_s'], self._hw))
        if not err:
            log.info("Injected clip %s as %s's live stream, session %s", path, cam, session_id)
        return session_id, err

    def _start_session(self, cam, trigger, make_source):
        """Starts a session for cam, reading frames from make_source(). Returns (session_id, error)."""
        with self._sessions_lock:
            if cam in self._sessions:
                return None, f"{cam} already has a running session ({self._sessions[cam].id})"
            if self._models is None:
                return None, self._models_error
            start = time.time()
            session_id = f"{re.sub(r'[^\w-]', '_', cam)}_{datetime.fromtimestamp(start):%Y%m%d_%H%M%S}"
            try:
                session = Session(session_id, cam, start, trigger, self._cfg, self._models, self._models_lock,
                                  self._store, self._data_dir, self.publish_own_svc_message, self._notification_imgs)
            except Exception as ex:  # pylint: disable=broad-except
                log.error("Can't create session %s", session_id, exc_info=True)
                return None, f"can't create session: {ex!r}"
            self._sessions[cam] = session
        log.info("%s event for %s: starting session %s", trigger, cam, session_id)
        threading.Thread(target=self._run_session, args=(session, make_source), daemon=True,
                         name=f"session_{cam}").start()
        return session_id, None

    def _run_session(self, session, make_source):
        try:
            reason = session.run(make_source())
            self._last_session_error = None if not reason.startswith(('error', 'stream error')) else \
                f"Session {session.id} failed: {reason}"
            summary = session.finish(time.time())
            log.info("Session %s ended (%s) after %.0fs: %s", session.id, reason, summary['analysed_s'],
                     [e['type'] for e in summary['events']] or 'no events')
            # An injected clip isn't the visit any recording shows
            if self._recording_faces is not None and session.trigger != 'injected':
                self._recording_faces.add_session(session.cam_alias, session.id, session.person_faces())
        except Exception:  # pylint: disable=broad-except
            log.error("Session %s failed", session.id, exc_info=True)
            self._last_session_error = f"Session {session.id} failed, see logs"
        finally:
            with self._sessions_lock:
                if self._sessions.get(session.cam_alias) is session:
                    del self._sessions[session.cam_alias]
            self._prune_session_logs()

    def _prune_session_logs(self):
        try:
            for sid in self._store.session_ids_to_prune(self._cfg['keep_sessions']):
                path = os.path.join(self._data_dir, 'sessions', sid)
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
        except Exception:  # pylint: disable=broad-except
            log.error("Failed to prune old session logs", exc_info=True)

    # ------------------------------------------------------------------ web UI

    def _www_status(self):
        with self._sessions_lock:
            active = [s.live_status() for s in self._sessions.values()]
        return jsonify({
            'models_error': self._models_error,
            'models_missing': missing_models(self._cfg['models_dir']),
            'alerts': self.get_service_alerts(),
            'active_sessions': active,
            'decoding': self._hw.status(),
            'inference': self._models.inference_description if self._models else None,
            'config': self._cfg,
        })

    def _www_sessions(self):
        limit = min(request.args.get('limit', 100, type=int), 500)
        before = request.args.get('before', type=float)
        sessions = self._store.sessions(limit, before)
        for s in sessions:
            s['has_log'] = os.path.isfile(os.path.join(self._data_dir, 'sessions', s['id'], 'log.json'))
        return jsonify(sessions)

    def _www_session(self, session_id):
        if not _SESSION_ID_RE.match(session_id):
            abort(400, description="Bad session id")
        path = os.path.join(self._data_dir, 'sessions', session_id, 'log.json')
        if not os.path.isfile(path):
            abort(404, description=f"No decision log for {session_id} (still running, or pruned)")
        with open(path) as f:
            return jsonify(json.load(f))

    def _www_inject_clip(self):
        req = request.get_json(silent=True) or {}
        session_id, err = self._inject_clip(req.get('cam_alias'), req.get('path'))
        if err:
            abort(400, description=err)
        return jsonify({'session_id': session_id})

    def _www_admin(self, op):
        req = request.get_json(silent=True) or {}
        try:
            match op:
                case 'reset_tracks':
                    self._store.reset_tracks([int(r) for r in req['track_rows']])
                case 'remove_track':
                    self._store.remove_track_from_identity(int(req['track_row']))
                case 'delete_identity':
                    self._store.delete_identity(int(req['id']), bool(req.get('to_pool', False)))
                case 'merge_identities':
                    self._store.merge_identities(int(req['keep_id']), int(req['other_id']))
                case 'split_identity':
                    ids = self._store.split_identity(int(req['id']), float(req.get('thr', 0.55)))
                    return jsonify({'identities': ids})
                case _:
                    abort(404, description=f"Unknown admin operation {op}")
        except (KeyError, ValueError, TypeError) as ex:
            abort(400, description=f"Bad request for {op}: {ex}")
        log.info("Admin %s: %s", op, req)
        return jsonify({})


service_runner(ZmwVisitorDetect)
