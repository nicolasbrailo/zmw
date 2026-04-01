#!/usr/bin/env python3
"""Test face detection and recognition on a single image.

Runs all three embedding models (SFace, ArcFace, InsightFace) on each detected face,
saves crops/aligned images/embeddings, and compares across all saved results.

Usage: python test.py <image_path> [models_dir]
"""
import json
import sys
import os
import cv2
import logging
import glob as globmod
import numpy as np
import onnxruntime as ort
from pathlib import Path

from visitor_detector import (
    _detect_face_yunet, _extract_yunet_landmarks, _is_frontal,
    _align_face_arcface, _compute_sface_embedding,
    _compute_insightface_embedding,
    _cosine_similarity, _MIN_FACE_PX,
)

_COSINE_THRESHOLDS = {'sface': 0.363, 'insightface': 0.4}

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def _run_matching(label, embed_files, key):
    """Run sequential matching mirroring production _find_closest behavior.
    Each embedding is compared against existing groups' embeddings; if the best
    match is above threshold it joins that group, otherwise it starts a new one."""
    entries = []
    for ef in embed_files:
        with open(ef) as f:
            data = json.load(f)
        if key not in data:
            continue
        name = os.path.basename(os.path.dirname(ef)).removesuffix("_crops")
        entries.append((name, data[key]['vec']))

    if len(entries) < 2:
        print(f"  {label}: not enough embeddings ({len(entries)})")
        return

    threshold = _COSINE_THRESHOLDS.get(key, 0.4)

    # groups: list of (names, embeddings) — each group is one person
    groups = []

    for name, vec in entries:
        best_group = None
        best_sim = -1
        for gi, (_, group_vecs) in enumerate(groups):
            for gvec in group_vecs:
                sim = _cosine_similarity(vec, gvec)
                if sim > best_sim:
                    best_sim = sim
                    best_group = gi

        if best_sim >= threshold and best_group is not None:
            groups[best_group][0].append(name)
            groups[best_group][1].append(vec)
        else:
            groups.append(([name], [vec]))

    print(f"  {label} (threshold={threshold}):")
    for i, (names, _) in enumerate(groups):
        print(f"    Person {i+1}: {', '.join(names)}")
    print(f"    -> {len(entries)} embeddings, {len(groups)} unique {'person' if len(groups) == 1 else 'people'}")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <image_path> [models_dir]")
        sys.exit(1)

    image_path = sys.argv[1]
    models_dir = sys.argv[2] if len(sys.argv) > 2 else "./models"

    if not os.path.isfile(image_path):
        print(f"File not found: {image_path}")
        sys.exit(1)

    img = cv2.imread(image_path)
    if img is None:
        print(f"Could not read image: {image_path}")
        sys.exit(1)

    h, w = img.shape[:2]
    print(f"Image: {image_path} ({w}x{h})")
    print(f"Min face size: {_MIN_FACE_PX}px")
    print()

    out_dir = os.path.splitext(image_path)[0] + "_crops"
    os.makedirs(out_dir, exist_ok=True)

    # Load models
    md = Path(models_dir)
    yunet_net = cv2.FaceDetectorYN.create(str(md / "face_detection_yunet_2023mar.onnx"), "", (300, 300))
    sface_net = cv2.FaceRecognizerSF.create(str(md / "face_recognition_sface_2021dec.onnx"), "")
    insightface_session = ort.InferenceSession(str(md / "w600k_r50.onnx"), providers=['CPUExecutionProvider'])

    # Detect
    face_row = _detect_face_yunet(yunet_net, img, 0.3)
    if face_row is None:
        print("No face detected")
        return

    x, y, fw, fh = int(face_row[0]), int(face_row[1]), int(face_row[2]), int(face_row[3])
    conf = float(face_row[14])
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(w, x + fw), min(h, y + fh)
    landmarks = _extract_yunet_landmarks(face_row)
    frontal = _is_frontal(landmarks)

    print(f"FACE DETECTED")
    print(f"  bbox: ({x1}, {y1}) -> ({x2}, {y2})  size: {x2-x1}x{y2-y1}")
    print(f"  confidence: {conf:.3f}")
    print(f"  frontal: {frontal}")
    print(f"  landmarks:")
    labels = ["right_eye", "left_eye", "nose", "right_mouth", "left_mouth"]
    for label, pt in zip(labels, landmarks):
        print(f"    {label}: ({pt[0]:.1f}, {pt[1]:.1f})")

    # Raw crop
    crop = img[y1:y2, x1:x2]
    crop_path = os.path.join(out_dir, "crop.jpg")
    cv2.imwrite(crop_path, crop)
    print(f"  crop: {crop_path}")

    # Annotated image
    annotated = img.copy()
    cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
    for pt in landmarks:
        cv2.circle(annotated, (int(pt[0]), int(pt[1])), 3, (0, 0, 255), -1)
    annot_path = os.path.join(out_dir, "annotated.jpg")
    cv2.imwrite(annot_path, annotated)
    print(f"  annotated: {annot_path}")

    # Aligned crops
    sface_aligned = sface_net.alignCrop(img, face_row)
    sface_aligned_path = os.path.join(out_dir, "crop_aligned_sface.jpg")
    cv2.imwrite(sface_aligned_path, sface_aligned)

    insightface_aligned = _align_face_arcface(img, landmarks)
    insightface_aligned_path = os.path.join(out_dir, "crop_aligned_insightface.jpg")
    cv2.imwrite(insightface_aligned_path, insightface_aligned)
    print(f"  crop_aligned_sface: {sface_aligned_path}")
    print(f"  crop_aligned_insightface: {insightface_aligned_path}")

    # Compute embeddings
    sface_emb = _compute_sface_embedding(sface_net, img, face_row)
    insightface_emb = _compute_insightface_embedding(insightface_session, insightface_aligned)

    embed_data = {
        'bbox': [x1, y1, x2, y2],
        'confidence': round(conf, 3),
        'frontal': bool(frontal),
        'sface': {'dims': len(sface_emb), 'vec': sface_emb},
        'insightface': {'dims': len(insightface_emb), 'vec': insightface_emb},
    }
    embed_path = os.path.join(out_dir, "embedding.json")
    with open(embed_path, 'w') as f:
        json.dump(embed_data, f, indent=2)

    print(f"  sface embedding: {len(sface_emb)}-d")
    print(f"  insightface embedding: {len(insightface_emb)}-d")
    print()
    print(f"Output saved to: {out_dir}")

    # --- Match across all existing embeddings ---
    print()
    print("--- Matching across all saved embeddings ---")

    parent = os.path.dirname(os.path.abspath(image_path))
    embed_files = sorted(globmod.glob(os.path.join(parent, "*_crops", "embedding.json")))
    if len(embed_files) < 2:
        print("Not enough embeddings to compare (need at least 2)")
        return

    _run_matching("SFace", embed_files, "sface")
    print()
    _run_matching("InsightFace w600k_r50", embed_files, "insightface")


if __name__ == "__main__":
    main()
