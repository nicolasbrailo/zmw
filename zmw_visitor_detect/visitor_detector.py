import cv2
import numpy as np
import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)


def _compute_embedding(embed_net, face_crop):
    """Compute 128-d embedding from a face crop."""
    blob = cv2.dnn.blobFromImage(face_crop, 1.0 / 255, (96, 96), (0, 0, 0), swapRB=True, crop=False)
    embed_net.setInput(blob)
    return embed_net.forward().flatten().tolist()


def _detect_face_res10(face_net, img, min_confidence):
    """Detect the largest face using res10 SSD. Returns (x1, y1, x2, y2, confidence) or None."""
    h, w = img.shape[:2]
    blob = cv2.dnn.blobFromImage(img, 1.0, (300, 300), (104.0, 177.0, 123.0))
    face_net.setInput(blob)
    detections = face_net.forward()
    best_face = None
    best_area = 0
    best_conf = 0
    for i in range(detections.shape[2]):
        confidence = float(detections[0, 0, i, 2])
        if confidence < min_confidence:
            continue
        x1 = max(0, int(detections[0, 0, i, 3] * w))
        y1 = max(0, int(detections[0, 0, i, 4] * h))
        x2 = min(w, int(detections[0, 0, i, 5] * w))
        y2 = min(h, int(detections[0, 0, i, 6] * h))
        if x2 - x1 < 10 or y2 - y1 < 10:
            continue
        area = (x2 - x1) * (y2 - y1)
        if area > best_area:
            best_area = area
            best_conf = confidence
            best_face = (x1, y1, x2, y2)
    if best_face is None:
        return None
    return (*best_face, best_conf)


def _detect_face_yunet(yunet_net, img, min_confidence):
    """Detect the largest face using YuNet. Returns (x1, y1, x2, y2, confidence) or None."""
    h, w = img.shape[:2]
    yunet_net.setInputSize((w, h))
    yunet_net.setScoreThreshold(min_confidence)
    _, faces = yunet_net.detect(img)
    if faces is None:
        return None
    best_face = None
    best_area = 0
    best_conf = 0
    for face in faces:
        x, y, fw, fh = int(face[0]), int(face[1]), int(face[2]), int(face[3])
        conf = float(face[14])
        if fw < 10 or fh < 10:
            continue
        area = fw * fh
        if area > best_area:
            best_area = area
            best_conf = conf
            best_face = (x, y, fw, fh)
    if best_face is None:
        return None
    x, y, fw, fh = best_face
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(w, x + fw), min(h, y + fh)
    return (x1, y1, x2, y2, best_conf)


def _apply_clahe(img):
    """Apply CLAHE contrast enhancement to improve face detection in poor lighting."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    lab[:, :, 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lab[:, :, 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def _detect_faces(face_net, yunet_net, embed_net, img, face_confidence=0.3):
    """Detect faces in img, return list of (bbox, embedding, confidence, detector_name).
    bbox is (x1, y1, x2, y2). embedding is 128-d list."""

    # TODO: currently only detects the single largest face. After benchmarking which
    # detector works best, return all faces above threshold to support multiple visitors

    # TODO: benchmark YuNet vs res10 on doorbell camera images and pick one
    detection = _detect_face_yunet(yunet_net, img, face_confidence)
    detector = 'yunet'

    # Fallback 1: res10 on original image
    if detection is None:
        detection = _detect_face_res10(face_net, img, face_confidence)
        detector = 'res10'

    # Fallback 2: CLAHE-enhanced image with res10
    if detection is None:
        enhanced = _apply_clahe(img)
        detection = _detect_face_res10(face_net, enhanced, face_confidence)
        detector = 'res10_clahe'

    if detection is None:
        return []

    x1, y1, x2, y2, confidence = detection
    face_crop = img[y1:y2, x1:x2]
    embedding = _compute_embedding(embed_net, face_crop)
    return [((x1, y1, x2, y2), embedding, confidence, detector)]


def _find_closest(faces, embedding, face_tolerance):
    """Find closest match in faces within tolerance. Returns index or None."""
    best_idx = None
    best_dist = float('inf')
    for i, entry in enumerate(faces):
        for known_emb in entry['embeddings']:
            dist = float(np.linalg.norm(np.array(embedding) - np.array(known_emb)))
            if dist < best_dist:
                best_dist = dist
                best_idx = i
    if best_dist < face_tolerance:
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

    State is persisted to state_path as a flat JSON list. Each entry holds a name
    (None while pending), a rolling window of embeddings, and a sighting count.
    """

    def __init__(self, models_dir, state_path, crops_dir,
                 face_confidence=0.3,
                 face_tolerance=0.85, sightings_to_mark_as_known=3,
                 max_embeddings=10, sighting_dedup_gap_secs=1800,
                 max_crops=200):
        self._models_dir = Path(models_dir)
        self._state_path = Path(state_path)
        self._crops_dir = Path(crops_dir)
        os.makedirs(self._crops_dir, exist_ok=True)
        self._face_confidence = face_confidence
        self._face_tolerance = face_tolerance
        self._sightings_to_mark_as_known = sightings_to_mark_as_known
        self._max_embeddings = max_embeddings
        self._sighting_dedup_gap_secs = sighting_dedup_gap_secs
        self._max_crops = max_crops

        self._face_net = self._load_caffe_net("face_deploy.prototxt", "res10_300x300_ssd_iter_140000.caffemodel")
        self._yunet_net = self._load_yunet("face_detection_yunet_2023mar.onnx")
        self._embed_net = self._load_torch_net("nn4.small2.v1.t7")

        # faces: [{"name": str|None, "embeddings": [...], "sightings": int, "last_sighting_time": float}, ...]
        # name=None means pending (not yet confirmed)
        self._faces = []
        if self._state_path.exists():
            with open(self._state_path, 'r') as f:
                self._faces = json.load(f)
            for entry in self._faces:
                entry.setdefault('last_sighting_time', 0)
            known = sum(1 for f in self._faces if f['name'] is not None)
            log.info("Loaded faces: %d named, %d known but unnamed", known, len(self._faces) - known)

    def _load_caffe_net(self, prototxt_name, model_name):
        prototxt = self._models_dir / prototxt_name
        model = self._models_dir / model_name
        for f in (prototxt, model):
            if not f.exists():
                raise FileNotFoundError(f"{model_name}: {f} not found. Run 'make download_models'.")
        net = cv2.dnn.readNetFromCaffe(str(prototxt), str(model))
        log.info("Loaded %s", model_name)
        return net

    def _load_yunet(self, model_name):
        model_path = self._models_dir / model_name
        if not model_path.exists():
            raise FileNotFoundError(f"{model_path} not found. Run 'make download_models'.")
        net = cv2.FaceDetectorYN.create(str(model_path), "", (300, 300))
        log.info("Loaded %s", model_name)
        return net

    def _load_torch_net(self, model_name):
        model_path = self._models_dir / model_name
        if not model_path.exists():
            raise FileNotFoundError(f"{model_path} not found. Run 'make download_models'.")
        net = cv2.dnn.readNetFromTorch(str(model_path))
        log.info("Loaded %s", model_name)
        return net

    def _match_or_track(self, embedding):
        """Match embedding against known faces. Returns (name, event). Event tracks if the person is
        known or not. A face detected is marked as new, and once it reaches a threshold it's updated to
        visitor (ie a known person).

        Sighting dedup: sightings only increment if enough time has passed since the last sighting
        (sighting_dedup_gap_secs). This prevents a person standing by the camera from being
        auto-promoted to visitor by rapid-fire motion events."""
        now = time.time()
        idx = _find_closest(self._faces, embedding, self._face_tolerance)

        if idx is None:
            entry = {
                'name': None,
                'embeddings': [embedding],
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
            entry['embeddings'].append(embedding)
            if len(entry['embeddings']) > self._max_embeddings:
                entry['embeddings'].pop(0)
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
            self._face_net, self._yunet_net, self._embed_net, img,
            self._face_confidence)

        input_image_path = self._save_input_image(img, now)
        results = []

        for bbox, embedding, confidence, face_detector in faces:
            entry, event = self._match_or_track(embedding)
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
