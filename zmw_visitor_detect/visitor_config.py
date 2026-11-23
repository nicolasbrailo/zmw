"""Config defaults. Values were tuned with ~/src/visitordetect/visitor_sim.py; see that repo's CLAUDE.md before
changing them. Every threshold is applied at runtime, so changing one never requires discarding stored data."""
import copy
import logging

import face_gate

DEFAULTS = {
    "cam_aliases": ["doorbell"],
    "models_dir": "./models",
    "data_dir": "./visitor_data",
    # Frames sampled from the RTSP main stream
    "fps": 4,
    # Where the models run: "cpu" (onnxruntime) or "gpu" (OpenVINO on the Intel GPU, ~2.5x faster, same results).
    # No fallback: if the chosen backend can't run, the service refuses to start (make check_gpu, logs)
    "inference": "cpu",
    # Video decoding: "vaapi" (GPU, falls back to the CPU when it doesn't work) or "off" (CPU). GPU decoding needs
    # the VA driver (Intel: intel-media-va-driver) and the service user in the device's group (usually "render")
    "hw_decode": "vaapi",
    "hw_decode_device": "/dev/dri/renderD128",
    # Decoded frames waiting for analysis, in seconds of stream. Keeps the burst ffmpeg decodes at startup (the
    # first seconds, usually the most valuable); beyond it the oldest frames are dropped. ~7 MB per frame.
    "stream_backlog_s": 3,
    # Session stop rules
    "max_session_s": 180,
    "idle_stop_s": 20,
    "motion_stop_s": 5,
    # Changed thumbnail pixels that count as motion; null disables the motion gate for that mode. At night the
    # IR noise is above what a person changes (a night gate lost 3/18 people), so night always analyses.
    "motion_min_px": {"day": 8, "night": None},
    # Person detector: "always" (every person_every_s), "first" (until on_person_detected fires, by detector or by
    # a face: the event is once per session, later checks only kept the session open) or "off" (people are only
    # reported through their faces, so never at night). It's the most expensive stage (~0.6 s per run).
    "person_detection": "first",
    # Night only reports people (no faces), so it checks less often; every 8 s missed short visits
    "person_every_s": {"day": 2, "night": 4},
    "person_thr": 0.5,
    # Smaller person boxes (pixels, on the 1920px tall main stream) are ignored: background passers-by on the
    # path and lawn measured 205-263px; household members arriving from far measured from 277px and grow as they
    # approach, so a later check catches them
    "person_min_height_px": 300,
    # Quality gate for faces worth identifying: size, SCRFD confidence, yaw (see face_gate.py for the evidence)
    "face_gate": dict(face_gate.DEFAULTS),
    # Once a track is decided, embed at most one of its faces per this many seconds (ArcFace is ~80 ms per face;
    # a track needs decide_min_faces to be decided, later faces only check for tracker mix-ups and refresh the
    # best faces kept)
    "decided_embed_every_s": 1.0,
    # Face tracker
    "track_max_gap_s": 2.0,
    "track_max_jump": 1.5,
    "track_split_thr": 0.2,
    # Decisions
    "decide_min_faces": 2,
    "id_thr": 0.35,
    "same_person_thr": 0.45,
    "gallery_add_thr": 0.45,
    "gallery_cap": 20,
    # Discovery of frequent visitors
    "discovery_min_visits": 3,
    "discovery_min_days": 2,
    "visit_gap_s": 300,
    "unknown_ttl_days": 30,
    # Notification images: each event gets a large crop (the person, or the face with some context) written here,
    # its path in notify_img_path, for notifiers (ZmwDoorman -> ZmwWhatsapp) to send. Must be a dir they can read,
    # eg the services' shared scratch dir; null: no notification images. Only the newest 100 are kept.
    "notification_img_dir": None,
    # Save each person's best face (large crop) next to the camera's recording of the visit, as
    # <recording>.face.<name>.jpg, for the NVR to show. Only for recordings inside allowed_paths; they're deleted
    # with the recording by the recorder's retention cleanup.
    "faces_next_to_recordings": True,
    # Decision logs (with their crops) kept for the UI; stored identities are not affected
    "keep_sessions": 500,
}


PERSON_DETECTION_MODES = ('always', 'first', 'off')


def with_defaults(cfg):
    out = copy.deepcopy(DEFAULTS)
    for k, v in (cfg or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    if out['person_detection'] not in PERSON_DETECTION_MODES:
        logging.getLogger("VisitorConfig").error(
            "person_detection is '%s', must be one of %s; using '%s'", out['person_detection'],
            PERSON_DETECTION_MODES, DEFAULTS['person_detection'])
        out['person_detection'] = DEFAULTS['person_detection']
    return out
