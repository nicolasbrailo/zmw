"""Face quality gate: decide from SCRFD's confidence and 5 landmarks whether a face is worth identifying.

Tuned in ~/src/visitordetect (CLAUDE.md): faces passing the gate gave genuine ArcFace similarities well above
every impostor pair; faces failing it are effectively unmatchable, and identifying them is what made the
previous version of this service look random.

The limits are config values (`face_gate` in the service config); DEFAULTS documents why each has its value.
"""
import numpy as np

DEFAULTS = {
    "min_iod_px": 18,
    # Yaw (0 = frontal). Turned faces up to 0.3 match their own person as well as frontal ones; up to 0.4 still
    # does for faces with eyes >= 35px apart. Small faces turned >= 0.4 start matching other people above the
    # identification threshold.
    "max_yaw": 0.3,
    "large_yaw_iod_px": 35,
    "max_yaw_large": 0.4,
    # SCRFD confidence. In video, backs of heads (eg a hair clip) are detected as faces at 0.5-0.65 and pass the
    # landmark checks; real gated faces score >= ~0.7. Those false faces are mid-sized (iod 35-46px), while SCRFD
    # scores very large close-ups lower (frontal faces with iod 106-217px at 0.53-0.72), so big faces get a lower
    # bar.
    "min_conf": 0.7,
    "large_conf_iod_px": 80,
    "min_conf_large": 0.5,
}


def yaw_iod(kps):
    """kps: 5 landmarks (left eye, right eye, nose, left mouth, right mouth) in pixels.
    Returns (yaw, iod): yaw is the nose's horizontal offset from the face centre line in eye-distance units
    (0 = frontal), iod the distance between the eyes in pixels."""
    le, re, nose, lm, rm = np.asarray(kps, dtype=np.float32)
    iod = float(np.linalg.norm(re - le))
    centre_x = ((le[0] + re[0]) / 2 + (lm[0] + rm[0]) / 2) / 2
    return float(abs(nose[0] - centre_x) / (iod + 1e-6)), iod


def gate(kps, night, conf, limits=DEFAULTS):
    """(passes, reason). Night IR faces never matched reliably, so they are rejected outright."""
    if night:
        return False, 'night'
    yaw, iod = yaw_iod(kps)
    if conf < (limits['min_conf_large'] if iod >= limits['large_conf_iod_px'] else limits['min_conf']):
        return False, f'low confidence ({conf:.2f})'
    if iod < limits['min_iod_px']:
        return False, f'small (iod {iod:.0f}px)'
    if yaw > (limits['max_yaw_large'] if iod >= limits['large_yaw_iod_px'] else limits['max_yaw']):
        return False, f'not frontal (yaw {yaw:.2f})'
    return True, 'ok'
