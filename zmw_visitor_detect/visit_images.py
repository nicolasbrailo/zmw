"""Large images of a visit for other services: notification images (sent right away) and each person's best face,
saved next to the camera's recording of the visit (kept with it). Both are independent of the session crops in
data_dir, which are small (for the UI) and pruned with the session logs.
"""
import logging
import os
import re
import threading
import time
from datetime import datetime

import cv2

log = logging.getLogger("VisitImages")

# Height of notification images and recording faces: sharp on a phone. Crops are never upscaled.
LARGE_MAX_H = 720
# Notification images are read right after their event, so only the newest few are kept
MAX_NOTIFICATION_IMGS = 100
# Recorder file names (ZmwReolinkCams): the recording's start time
_REC_NAME_RE = re.compile(r'^(\d{8}_\d{6})\.mp4$')
# The recorder starts ~1 s after the camera event that starts a session, and its file name has 1 s resolution
MATCH_TOLERANCE_S = 5
# Recordings are announced when they end and sessions finish on their own schedule: how long one waits for the other
MATCH_KEEP_S = 900


def encode_jpg(img, max_h=LARGE_MAX_H):
    if img.shape[0] > max_h:
        img = cv2.resize(img, (int(img.shape[1] * max_h / img.shape[0]), max_h), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise ValueError(f"Can't encode a {img.shape} image as jpg")
    return buf.tobytes()


def _write_atomic(path, data):
    # Readers (the NVR listing, a notifier) never see a partial file
    tmp = f"{path}.tmp"
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)


class NotificationImages:
    """Notification images, in a dir the notifiers can read (the services' shared scratch dir)."""

    def __init__(self, path):
        self._dir = os.path.abspath(path)
        os.makedirs(self._dir, exist_ok=True)

    def write(self, name, jpg):
        """Path of the written image, or None if it couldn't be written (logged)."""
        path = os.path.join(self._dir, name)
        try:
            _write_atomic(path, jpg)
        except OSError:
            log.error("Can't write notification image %s", path, exc_info=True)
            return None
        self._cleanup()
        return path

    def _cleanup(self):
        try:
            files = [os.path.join(self._dir, f) for f in os.listdir(self._dir) if f.endswith('.jpg')]
            if len(files) <= MAX_NOTIFICATION_IMGS:
                return
            files.sort(key=os.path.getmtime)
            for f in files[:len(files) - MAX_NOTIFICATION_IMGS]:
                os.remove(f)
        except OSError:
            log.warning("Failed to clean up old notification images in %s", self._dir, exc_info=True)


def recording_face_path(rec_path, label):
    """Where a face is saved for a recording. The NVR shows any file named <recording>.face.<label>.jpg."""
    return f"{rec_path}.face.{label}.jpg"


class RecordingFaces:
    """Saves each person's best face next to the recording of the visit. A face goes to the recording (same camera)
    whose time span contains it; faces outside every recording are not saved. Recordings must be in allowed_paths.
    Old files are deleted by the recorder's own retention cleanup, along with the recording."""

    def __init__(self, allowlist):
        self._allowlist = allowlist
        self._lock = threading.Lock()
        self._recordings = []   # dicts: cam, path, start, end
        self._faces = []        # dicts: cam, person (unique per visit), named, label, ts, jpg, saved_to (rec paths)

    def add_recording(self, cam, path, now=None):
        """A recording ended (ZmwReolinkCams' on_new_recording)."""
        now = time.time() if now is None else now
        m = _REC_NAME_RE.match(os.path.basename(path)) if isinstance(path, str) else None
        if m is None:
            log.warning("Recording %r isn't named <YYYYmmdd_HHMMSS>.mp4: can't tell when it started, no faces "
                        "will be saved next to it", path)
            return
        resolved = self._allowlist.check(path)
        if resolved is None:
            return
        start = datetime.strptime(m.group(1), '%Y%m%d_%H%M%S').timestamp()
        with self._lock:
            self._prune(now)
            self._recordings.append({'cam': cam, 'path': resolved, 'start': start, 'end': now})
            self._match()

    def add_session(self, cam, session_id, faces, now=None):
        """A session finished. faces: Session.person_faces()."""
        now = time.time() if now is None else now
        with self._lock:
            self._prune(now)
            for f in faces:
                self._faces.append({'cam': cam, 'person': (session_id, f['person']), 'named': f['named'],
                                    'label': f['label'], 'ts': f['ts'], 'jpg': f['jpg'], 'saved_to': set()})
            self._match()

    def _prune(self, now):
        self._recordings = [r for r in self._recordings if r['end'] >= now - MATCH_KEEP_S]
        self._faces = [f for f in self._faces if f['ts'] >= now - MATCH_KEEP_S]

    def _match(self):
        for f in self._faces:
            for r in self._recordings:
                if (f['cam'] == r['cam'] and r['path'] not in f['saved_to']
                        and r['start'] - MATCH_TOLERANCE_S <= f['ts'] <= r['end'] + MATCH_TOLERANCE_S):
                    f['saved_to'].add(r['path'])
                    self._save(f, r['path'])

    @staticmethod
    def _save(face, rec_path):
        label = re.sub(r'[^\w-]', '_', face['label']) or 'unknown'
        path = recording_face_path(rec_path, label)
        if os.path.exists(path):
            if face['named']:
                # The same visitor, already saved for this recording by an earlier session
                return
            # Another unknown person
            n = 2
            while os.path.exists(recording_face_path(rec_path, f"{label}_{n}")):
                n += 1
            path = recording_face_path(rec_path, f"{label}_{n}")
        try:
            _write_atomic(path, face['jpg'])
            log.info("Saved %s's face next to recording %s", face['label'], os.path.basename(rec_path))
        except OSError:
            log.error("Can't save a face next to recording %s", rec_path, exc_info=True)
