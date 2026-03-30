import cv2
import numpy as np
import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)

# PASCAL VOC class labels matching MobileNet-SSD's training order.
# Hardcoded because Caffe model files don't embed label metadata.
_MOBILENET_CLASSES = [
    "background", "aeroplane", "bicycle", "bird", "boat", "bottle", "bus",
    "car", "cat", "chair", "cow", "diningtable", "dog", "horse", "motorbike",
    "person", "pottedplant", "sheep", "sofa", "train", "tvmonitor"
]
_PERSON_CLASS_ID = _MOBILENET_CLASSES.index("person")


def _compute_embedding(embed_net, face_crop):
    """Compute 128-d embedding from a face crop."""
    blob = cv2.dnn.blobFromImage(face_crop, 1.0 / 255, (96, 96), (0, 0, 0), swapRB=True, crop=False)
    embed_net.setInput(blob)
    return embed_net.forward().flatten().tolist()


def _face_embedding(face_net, embed_net, img, min_confidence):
    """Detect the largest face in img and return its 128-d embedding, or None."""
    h, w = img.shape[:2]
    blob = cv2.dnn.blobFromImage(img, 1.0, (300, 300), (104.0, 177.0, 123.0))
    face_net.setInput(blob)
    detections = face_net.forward()
    best_face = None
    best_area = 0
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
            best_face = (x1, y1, x2, y2)
    if best_face is None:
        return None
    x1, y1, x2, y2 = best_face
    return _compute_embedding(embed_net, img[y1:y2, x1:x2])


# TODO: benchmark YuNet vs res10 on doorbell camera images and pick one
def _face_embedding_yunet(yunet_net, embed_net, img, min_confidence):
    """Detect the largest face using YuNet and return its 128-d embedding, or None."""
    h, w = img.shape[:2]
    yunet_net.setInputSize((w, h))
    yunet_net.setScoreThreshold(min_confidence)
    _, faces = yunet_net.detect(img)
    if faces is None:
        return None
    best_face = None
    best_area = 0
    for face in faces:
        x, y, fw, fh = int(face[0]), int(face[1]), int(face[2]), int(face[3])
        if fw < 10 or fh < 10:
            continue
        area = fw * fh
        if area > best_area:
            best_area = area
            best_face = (x, y, fw, fh)
    if best_face is None:
        return None
    x, y, fw, fh = best_face
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(w, x + fw), min(h, y + fh)
    return _compute_embedding(embed_net, img[y1:y2, x1:x2])


def _apply_clahe(img):
    """Apply CLAHE contrast enhancement to improve face detection in poor lighting."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    lab[:, :, 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lab[:, :, 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def _detect_visitors(person_net, face_net, yunet_net, embed_net, img,
                     person_confidence=0.5, face_confidence=0.3):
    """Detect persons in img, return list of (bbox, embedding_or_none, person_confidence).
    bbox is (x1, y1, x2, y2). embedding is 128-d list or None if no face found."""
    h, w = img.shape[:2]

    # Person detection
    blob = cv2.dnn.blobFromImage(cv2.resize(img, (300, 300)), 0.007843, (300, 300), 127.5)
    person_net.setInput(blob)
    detections = person_net.forward()

    results = []
    for i in range(detections.shape[2]):
        class_id = int(detections[0, 0, i, 1])
        confidence = float(detections[0, 0, i, 2])
        if class_id != _PERSON_CLASS_ID or confidence < person_confidence:
            continue
        x1 = max(0, int(detections[0, 0, i, 3] * w))
        y1 = max(0, int(detections[0, 0, i, 4] * h))
        x2 = min(w, int(detections[0, 0, i, 5] * w))
        y2 = min(h, int(detections[0, 0, i, 6] * h))

        # Pad the person crop by 20% to give the face detector more context
        pad_h = int((y2 - y1) * 0.2)
        pad_w = int((x2 - x1) * 0.2)
        crop = img[max(0, y1 - pad_h):min(h, y2 + pad_h), max(0, x1 - pad_w):min(w, x2 + pad_w)]
        embedding = _face_embedding(face_net, embed_net, crop, face_confidence)
        face_detector = 'res10' if embedding is not None else None

        # Fallback 1: CLAHE-enhanced full image with res10
        if embedding is None:
            enhanced = _apply_clahe(img)
            embedding = _face_embedding(face_net, embed_net, enhanced, face_confidence)
            if embedding is not None:
                face_detector = 'res10_clahe'

        # Fallback 2: YuNet on full image (better with small/rotated/low-quality faces)
        # TODO: benchmark YuNet vs res10 on doorbell camera images and pick one
        if embedding is None:
            embedding = _face_embedding_yunet(yunet_net, embed_net, img, face_confidence)
            if embedding is not None:
                face_detector = 'yunet'

        results.append(((x1, y1, x2, y2), embedding, confidence, face_detector))

    return results


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
      1. person_no_face_detected — person body found but no face in the crop
      2. new_face_detected — face found but not yet seen enough times to be a visitor
         (stays here until sightings_to_mark_as_known threshold is reached)
      3. new_visitor_recognized — face just crossed the sighting threshold, assigned
         a name ("Person N") for the first time
      4. visitor_recognized — previously named visitor seen again

    State is persisted to state_path as a flat JSON list. Each entry holds a name
    (None while pending), a rolling window of embeddings, and a sighting count.
    """

    def __init__(self, models_dir, state_path, crops_dir,
                 person_confidence=0.5, face_confidence=0.3,
                 face_tolerance=0.85, sightings_to_mark_as_known=3,
                 max_embeddings=10, sighting_dedup_gap_secs=1800,
                 max_crops=200):
        self._models_dir = Path(models_dir)
        self._state_path = Path(state_path)
        self._crops_dir = Path(crops_dir)
        os.makedirs(self._crops_dir, exist_ok=True)
        self._person_confidence = person_confidence
        self._face_confidence = face_confidence
        self._face_tolerance = face_tolerance
        self._sightings_to_mark_as_known = sightings_to_mark_as_known
        self._max_embeddings = max_embeddings
        self._sighting_dedup_gap_secs = sighting_dedup_gap_secs
        self._max_crops = max_crops

        self._person_net = self._load_caffe_net("MobileNetSSD_deploy.prototxt", "MobileNetSSD_deploy.caffemodel")
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
        visitors = _detect_visitors(
            self._person_net, self._face_net, self._yunet_net, self._embed_net, img,
            self._person_confidence, self._face_confidence)

        input_image_path = self._save_input_image(img, now)
        results = []

        for bbox, embedding, person_conf, face_detector in visitors:
            if embedding is None:
                name, event, sightings = None, 'person_no_face_detected', None
            else:
                entry, event = self._match_or_track(embedding)
                name, sightings = entry['name'], entry['sightings']

            crop_path = self._save_crop(img, bbox, name, now)
            results.append({
                'timestamp': now,
                'name': name,
                'event': event,
                'sightings': sightings,
                'person_confidence': round(person_conf, 3),
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
            'person_count': len(visitors),
            'visitors': results,
        }

    def _rotate_crops(self):
        crops = sorted(self._crops_dir.glob("*.jpg"), key=lambda p: p.stat().st_mtime)
        to_remove = len(crops) - self._max_crops
        for p in crops[:to_remove]:
            p.unlink(missing_ok=True)
