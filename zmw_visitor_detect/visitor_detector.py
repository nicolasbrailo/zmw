import cv2
import numpy as np
import onnxruntime as ort
import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)

# Minimum face size in pixels (shortest side). Anything smaller is too low-res for recognition.
_MIN_FACE_PX = 80

# Standard reference landmarks for ArcFace 112x112 alignment
_ARCFACE_REF_LANDMARKS = np.array([
    [38.2946, 51.6963],  # left eye
    [73.5318, 51.5014],  # right eye
    [56.0252, 71.7366],  # nose tip
    [41.5493, 92.3655],  # left mouth corner
    [70.7299, 92.2041],  # right mouth corner
], dtype=np.float32)


def _cosine_similarity(a, b):
    a, b = np.array(a), np.array(b)
    dot = np.dot(a, b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    return float(dot / (norm + 1e-10))


def _extract_yunet_landmarks(face_row):
    """Extract 5 landmark points from YuNet face detection row.
    YuNet order: right_eye, left_eye, nose, right_mouth, left_mouth."""
    return np.array([
        [face_row[4], face_row[5]],
        [face_row[6], face_row[7]],
        [face_row[8], face_row[9]],
        [face_row[10], face_row[11]],
        [face_row[12], face_row[13]],
    ], dtype=np.float32)


def _is_frontal(landmarks, threshold=0.3):
    """Check if face is roughly frontal based on nose-to-eye-center offset ratio."""
    right_eye, left_eye, nose = landmarks[0], landmarks[1], landmarks[2]
    eye_center_x = (left_eye[0] + right_eye[0]) / 2
    eye_dist = abs(right_eye[0] - left_eye[0])
    if eye_dist < 1:
        return False
    nose_offset = abs(nose[0] - eye_center_x) / eye_dist
    return nose_offset < threshold


def _align_face_arcface(img, landmarks):
    """Align face to 112x112 using similarity transform from landmarks to ArcFace reference."""
    M, _ = cv2.estimateAffinePartial2D(landmarks, _ARCFACE_REF_LANDMARKS)
    if M is None:
        h, w = img.shape[:2]
        cx, cy = w // 2, h // 2
        half = min(cx, cy, 56)
        crop = img[max(0, cy - half):cy + half, max(0, cx - half):cx + half]
        return cv2.resize(crop, (112, 112))
    return cv2.warpAffine(img, M, (112, 112))


def _compute_sface_embedding(sface_net, img, face_row):
    """Compute SFace 128-d embedding using built-in alignCrop."""
    aligned = sface_net.alignCrop(img, face_row)
    return sface_net.feature(aligned).flatten().tolist()


def _compute_insightface_embedding(insightface_session, aligned_face):
    """Compute InsightFace w600k_r50 512-d L2-normalized embedding."""
    img = cv2.resize(aligned_face, (112, 112)).astype(np.float32)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = (img - 127.5) / 127.5
    blob = np.transpose(img, (2, 0, 1))[np.newaxis, ...]  # NCHW
    input_name = insightface_session.get_inputs()[0].name
    embedding = insightface_session.run(None, {input_name: blob})[0].flatten()
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = embedding / norm
    return embedding.tolist()


def _detect_face_yunet(yunet_net, img, min_confidence):
    """Detect the largest face using YuNet. Returns full face row (with landmarks) or None."""
    h, w = img.shape[:2]
    yunet_net.setInputSize((w, h))
    yunet_net.setScoreThreshold(min_confidence)
    _, faces = yunet_net.detect(img)
    if faces is None:
        return None
    best_face = None
    best_area = 0
    for face in faces:
        fw, fh = int(face[2]), int(face[3])
        if fw < _MIN_FACE_PX or fh < _MIN_FACE_PX:
            continue
        area = fw * fh
        if area > best_area:
            best_area = area
            best_face = face
    return best_face


def _detect_faces(yunet_net, sface_net, insightface_session, img, face_confidence=0.3):
    """Detect faces in img, return list of (bbox, embedding, embed_type, confidence, detector_name).
    Uses SFace for frontal faces (via YuNet landmarks), InsightFace w600k_r50 for non-frontal."""

    face_row = _detect_face_yunet(yunet_net, img, face_confidence)
    if face_row is None:
        return []

    x, y, fw, fh = int(face_row[0]), int(face_row[1]), int(face_row[2]), int(face_row[3])
    h, w = img.shape[:2]
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(w, x + fw), min(h, y + fh)
    confidence = float(face_row[14])
    bbox = (x1, y1, x2, y2)

    landmarks = _extract_yunet_landmarks(face_row)
    frontal = _is_frontal(landmarks)

    if frontal:
        embedding = _compute_sface_embedding(sface_net, img, face_row)
        embed_type = 'sface'
        detector = 'yunet_sface'
    else:
        aligned = _align_face_arcface(img, landmarks)
        embedding = _compute_insightface_embedding(insightface_session, aligned)
        embed_type = 'insightface'
        detector = 'yunet_insightface'

    return [(bbox, embedding, embed_type, confidence, detector)]


def _find_closest(faces, embedding, embed_type, thresholds):
    """Find closest match using cosine similarity, comparing only same-type embeddings."""
    threshold = thresholds.get(embed_type, 0.4)
    best_idx = None
    best_sim = -1
    for i, entry in enumerate(faces):
        for emb_entry in entry['embeddings']:
            if emb_entry['type'] != embed_type:
                continue
            sim = _cosine_similarity(embedding, emb_entry['vec'])
            if sim > best_sim:
                best_sim = sim
                best_idx = i
    if best_sim >= threshold:
        return best_idx
    return None


class VisitorDetector:
    """Tracks faces across images and promotes them to named visitors.

    Recognition lifecycle:
      1. new_face_detected — face found but not yet seen enough times to be a visitor
         (stays here until sightings_to_mark_as_known threshold is reached)
      2. new_visitor_recognized — face just crossed the sighting threshold, assigned
         a name ("Person N") for the first time
      3. visitor_recognized — previously named visitor seen again

    Embedding strategy:
      - SFace (128-d) for frontal faces detected by YuNet (fast, accurate when aligned)
      - InsightFace w600k_r50 (512-d) for non-frontal faces (pose-tolerant, via onnxruntime)
      - Embeddings are tagged with type; matching only compares same-type embeddings.

    State is persisted to state_path as a flat JSON list. Each entry holds a name
    (None while pending), typed embeddings, and a sighting count.
    """

    def __init__(self, models_dir, state_path, crops_dir,
                 face_confidence=0.3,
                 sface_cosine_threshold=0.363, insightface_cosine_threshold=0.4,
                 sightings_to_mark_as_known=3,
                 max_embeddings=10, sighting_dedup_gap_secs=1800,
                 max_crops=200):
        self._models_dir = Path(models_dir)
        self._state_path = Path(state_path)
        self._crops_dir = Path(crops_dir)
        os.makedirs(self._crops_dir, exist_ok=True)
        self._face_confidence = face_confidence
        self._cosine_thresholds = {
            'sface': sface_cosine_threshold,
            'insightface': insightface_cosine_threshold,
        }
        self._sightings_to_mark_as_known = sightings_to_mark_as_known
        self._max_embeddings = max_embeddings
        self._sighting_dedup_gap_secs = sighting_dedup_gap_secs
        self._max_crops = max_crops

        self._yunet_net = self._load_yunet("face_detection_yunet_2023mar.onnx")
        self._sface_net = self._load_sface("face_recognition_sface_2021dec.onnx")
        self._insightface_session = self._load_ort_session("w600k_r50.onnx")

        # faces: [{"name": str|None, "embeddings": [{"vec": [...], "type": "sface"|"arcface"}, ...],
        #          "sightings": int, "last_sighting_time": float}, ...]
        self._faces = []
        if self._state_path.exists():
            with open(self._state_path, 'r') as f:
                self._faces = json.load(f)
            migrated = 0
            for entry in self._faces:
                entry.setdefault('last_sighting_time', 0)
                # Migrate old nn4 embeddings (flat lists) to new tagged format
                if entry['embeddings'] and not isinstance(entry['embeddings'][0], dict):
                    entry['embeddings'] = []
                    migrated += 1
            known = sum(1 for f in self._faces if f['name'] is not None)
            log.info("Loaded faces: %d named, %d pending", known, len(self._faces) - known)
            if migrated:
                log.info("Migrated %d entries: discarded old nn4 embeddings", migrated)

    def _load_yunet(self, model_name):
        model_path = self._models_dir / model_name
        if not model_path.exists():
            raise FileNotFoundError(f"{model_path} not found. Run 'make download_models'.")
        net = cv2.FaceDetectorYN.create(str(model_path), "", (300, 300))
        log.info("Loaded %s", model_name)
        return net

    def _load_sface(self, model_name):
        model_path = self._models_dir / model_name
        if not model_path.exists():
            raise FileNotFoundError(f"{model_path} not found. Run 'make download_models'.")
        net = cv2.FaceRecognizerSF.create(str(model_path), "")
        log.info("Loaded %s", model_name)
        return net

    def _load_ort_session(self, model_name):
        model_path = self._models_dir / model_name
        if not model_path.exists():
            raise FileNotFoundError(f"{model_path} not found. Run 'make download_models'.")
        session = ort.InferenceSession(str(model_path), providers=['CPUExecutionProvider'])
        log.info("Loaded %s", model_name)
        return session

    def _match_or_track(self, embedding, embed_type):
        """Match embedding against known faces. Returns (entry, event).

        Sighting dedup: sightings only increment if enough time has passed since the last sighting
        (sighting_dedup_gap_secs). This prevents a person standing by the camera from being
        auto-promoted to visitor by rapid-fire motion events."""
        now = time.time()
        idx = _find_closest(self._faces, embedding, embed_type, self._cosine_thresholds)

        if idx is None:
            entry = {
                'name': None,
                'embeddings': [{'vec': embedding, 'type': embed_type}],
                'sightings': 1,
                'last_sighting_time': now,
            }
            self._faces.append(entry)
            return entry, 'new_face_detected'

        entry = self._faces[idx]
        gap = now - entry.get('last_sighting_time', 0)
        count_as_sighting = gap >= self._sighting_dedup_gap_secs

        if count_as_sighting:
            entry['sightings'] += 1
            entry['embeddings'].append({'vec': embedding, 'type': embed_type})
            # Trim per-type embeddings to max, keeping most recent
            type_indices = [i for i, e in enumerate(entry['embeddings']) if e['type'] == embed_type]
            while len(type_indices) > self._max_embeddings:
                entry['embeddings'].pop(type_indices.pop(0))
        entry['last_sighting_time'] = now

        if entry['name'] is not None:
            return entry, 'visitor_recognized'

        if entry['sightings'] >= self._sightings_to_mark_as_known:
            person_id = sum(1 for f in self._faces if f['name'] is not None) + 1
            entry['name'] = f"Person {person_id}"
            return entry, 'new_visitor_recognized'

        return entry, 'new_face_detected'

    def _save_crop(self, img, bbox, name, timestamp):
        x1, y1, x2, y2 = bbox
        crop = img[y1:y2, x1:x2]
        name_slug = (name or 'unknown').replace(' ', '_').lower()
        crop_path = str(self._crops_dir / f"{int(timestamp)}_{name_slug}.jpg")
        cv2.imwrite(crop_path, crop)
        return crop_path

    def _save_input_image(self, img, timestamp):
        input_path = str(self._crops_dir / f"{int(timestamp)}_input.jpg")
        cv2.imwrite(input_path, img)
        return input_path

    def detect(self, image_path):
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"Could not read image: {image_path}")

        now = time.time()
        faces = _detect_faces(
            self._yunet_net, self._sface_net, self._insightface_session, img,
            self._face_confidence)

        input_image_path = self._save_input_image(img, now)
        results = []

        for bbox, embedding, embed_type, confidence, face_detector in faces:
            entry, event = self._match_or_track(embedding, embed_type)
            name, sightings = entry['name'], entry['sightings']

            crop_path = self._save_crop(img, bbox, name, now)
            results.append({
                'timestamp': now,
                'name': name,
                'event': event,
                'sightings': sightings,
                'face_confidence': round(confidence, 3),
                'face_detector': face_detector,
                'bbox': list(bbox),
                'crop_path': crop_path,
            })

        # Update run state
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._state_path, 'w') as f:
            json.dump(self._faces, f, indent=2)

        self._rotate_crops()

        return {
            'timestamp': now,
            'image': str(image_path),
            'input_image_path': input_image_path,
            'face_count': len(faces),
            'visitors': results,
        }

    def _rotate_crops(self):
        crops = sorted(self._crops_dir.glob("*.jpg"), key=lambda p: p.stat().st_mtime)
        to_remove = len(crops) - self._max_crops
        for p in crops[:to_remove]:
            p.unlink(missing_ok=True)
