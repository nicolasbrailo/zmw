"""ONNX models used by the visitor pipeline. Chosen and tuned in ~/src/visitordetect.

- persons: YOLOX-m (Megvii) + YOLO11m (Ultralytics export) at 640, merged with combine_persons
- faces: SCRFD-10G (insightface buffalo_l det_10g.onnx), boxes + 5 landmarks
- identity: ArcFace r50 (buffalo_l w600k_r50.onnx) on faces aligned to the 112x112 ArcFace template

Inference backends (config `inference`): "cpu" runs onnxruntime on the CPU; "gpu" runs OpenVINO on the Intel GPU,
the detectors in FP16 and ArcFace in FP32. Measured on the server (Iris Xe): detectors 2.5-3x faster, ArcFace 2x;
FP16 detections match the CPU (no face or person missing or extra, confidence within 0.007), FP32 embeddings are
identical to the CPU's. There is no fallback between backends: embeddings from two backends would end up mixed in
the identity store, so a backend that can't run is an error (see ~/src/visitordetect/CLAUDE.md).
"""
import os
import sys

import cv2
import numpy as np

PERSON_INPUT = 640
FACE_INPUT = 640
NMS_IOU = 0.45
# A box from a 2nd person model is the same person if the intersection covers this much of the smaller box
COMBINE_OVERLAP = 0.6
FACE_MIN_CONF = 0.5

# Standard ArcFace 112x112 landmark template: left eye, right eye, nose, left mouth, right mouth
ARCFACE_TEMPLATE = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                             [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)

MODEL_FILES = {
    'yolox_m': 'yolox_m.onnx',
    'yolo11m': 'yolo11m.onnx',
    'scrfd': 'det_10g.onnx',
    'arcface': 'w600k_r50.onnx',
}


def _letterbox(img, size, pad):
    """Resize keeping aspect ratio, pad bottom/right. size is an int (square) or (h, w). Returns (img, scale)."""
    th, tw = (size, size) if isinstance(size, int) else size
    h, w = img.shape[:2]
    r = min(th / h, tw / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    out = np.full((th, tw, 3), pad, np.uint8)
    out[:nh, :nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    return out, r


def _nms(boxes_xyxy, scores, min_conf):
    if len(boxes_xyxy) == 0:
        return []
    xywh = [[float(b[0]), float(b[1]), float(b[2] - b[0]), float(b[3] - b[1])] for b in boxes_xyxy]
    keep = cv2.dnn.NMSBoxes(xywh, [float(s) for s in scores], min_conf, NMS_IOU)
    return [int(i) for i in np.array(keep).flatten()]


def clip_box(b, w, h):
    return [int(max(0, b[0])), int(max(0, b[1])), int(min(w, b[2])), int(min(h, b[3]))]


class InferenceBackendError(Exception):
    pass


class _OrtSession:
    def __init__(self, path):
        import onnxruntime as ort  # pylint: disable=import-outside-toplevel
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self._sess = ort.InferenceSession(path, opts, providers=['CPUExecutionProvider'])
        self.input_name = self._sess.get_inputs()[0].name
        self.input_shape = self._sess.get_inputs()[0].shape

    def run(self, blob):
        """Outputs in the ONNX model's order."""
        return self._sess.run(None, {self.input_name: blob})


class _OvSession:
    def __init__(self, core, path, device, precision, input_shape):
        model = core.read_model(path)
        if input_shape:
            # Some models have a dynamic input size (SCRFD); a fixed one is what we feed, and faster on the GPU
            model.reshape(list(input_shape))
        self.input_shape = [d.get_length() for d in model.inputs[0].get_partial_shape()]
        compiled = core.compile_model(model, device, {'PERFORMANCE_HINT': 'LATENCY',
                                                      'INFERENCE_PRECISION_HINT': precision})
        self._req = compiled.create_infer_request()
        self._outputs = compiled.outputs

    def run(self, blob):
        """Outputs in the ONNX model's order."""
        res = self._req.infer(blob)
        return [res[o] for o in self._outputs]


class CpuBackend:
    name = 'cpu'

    def __init__(self):
        self.description = 'CPU (onnxruntime)'

    def session(self, path, _precision, _input_shape=None):
        return _OrtSession(path)


class GpuBackend:
    name = 'gpu'

    def __init__(self, cache_dir=None):
        # OpenVINO sends usage telemetry to Google Analytics by default, from a child process (which, with Python
        # 3.14's forkserver, also re-imports the main module). Its import of openvino_telemetry is optional and
        # falls back to a no-op stub, so block it: this service is local only.
        if 'openvino_telemetry' not in sys.modules:
            sys.modules['openvino_telemetry'] = None
        try:
            import openvino as ov  # pylint: disable=import-outside-toplevel
        except ImportError as ex:
            raise InferenceBackendError(f"inference is 'gpu' but OpenVINO isn't installed ({ex}): "
                                        "make rebuild_deps") from ex
        self._core = ov.Core()
        devices = self._core.available_devices
        if 'GPU' not in devices:
            raise InferenceBackendError(
                f"inference is 'gpu' but OpenVINO finds no GPU (devices: {', '.join(devices) or 'none'}). Needs "
                "Intel's compute runtime and the service user in the GPU device's group: make setup_gpu, then "
                "restart; make check_gpu verifies it")
        if cache_dir:
            # Compiling for the GPU takes 2-4 s per model; the cache makes later starts fast
            os.makedirs(cache_dir, exist_ok=True)
            self._core.set_property({'CACHE_DIR': cache_dir})
        gpu = self._core.get_property('GPU', 'FULL_DEVICE_NAME')
        self.description = f'GPU (OpenVINO {ov.__version__}, {gpu}): detectors FP16, ArcFace FP32'

    def session(self, path, precision, input_shape=None):
        return _OvSession(self._core, path, 'GPU', precision, input_shape)


def _yolo_grids(size):
    grids, strides = [], []
    for s in (8, 16, 32):
        n = size // s
        yv, xv = np.meshgrid(np.arange(n), np.arange(n), indexing='ij')
        grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
        strides.append(np.full((n * n, 1), s))
    return np.concatenate(grids).astype(np.float32), np.concatenate(strides).astype(np.float32)


class YoloxPerson:
    """Megvii YOLOX official ONNX: BGR 0-255 input, raw (undecoded) grid outputs, COCO class 0 = person."""

    def __init__(self, path, backend):
        self.sess = backend.session(path, 'f16', (1, 3, PERSON_INPUT, PERSON_INPUT))
        self.grid, self.stride = _yolo_grids(PERSON_INPUT)

    def detect(self, img, min_conf):
        lb, r = _letterbox(img, PERSON_INPUT, 114)
        blob = lb.transpose(2, 0, 1)[None].astype(np.float32)
        out = self.sess.run(blob)[0][0]
        xy = (out[:, :2] + self.grid) * self.stride
        wh = np.exp(out[:, 2:4]) * self.stride
        scores = out[:, 4] * out[:, 5]
        m = scores >= min_conf
        xy, wh, scores = xy[m], wh[m], scores[m]
        boxes = np.concatenate([xy - wh / 2, xy + wh / 2], 1) / r
        return [(boxes[i], float(scores[i])) for i in _nms(boxes, scores, min_conf)]


class UltralyticsPerson:
    """Ultralytics YOLO11 ONNX export: RGB 0-1 input, output [1, 84, N] = cxcywh + 80 class scores."""

    def __init__(self, path, backend):
        self.sess = backend.session(path, 'f16')
        self.size = tuple(self.sess.input_shape[2:4])

    def detect(self, img, min_conf):
        lb, r = _letterbox(img, self.size, 114)
        blob = cv2.dnn.blobFromImage(lb, 1 / 255.0, swapRB=True)
        out = self.sess.run(blob)[0][0].T
        scores = out[:, 4]
        m = scores >= min_conf
        out, scores = out[m], scores[m]
        xy, wh = out[:, :2], out[:, 2:4]
        boxes = np.concatenate([xy - wh / 2, xy + wh / 2], 1) / r
        return [(boxes[i], float(scores[i])) for i in _nms(boxes, scores, min_conf)]


class ScrfdFace:
    """InsightFace SCRFD-10G: 3 strides x 2 anchors, distance-encoded boxes and landmarks."""

    def __init__(self, path, backend):
        self.sess = backend.session(path, 'f16', (1, 3, FACE_INPUT, FACE_INPUT))
        self.centers = {}
        for s in (8, 16, 32):
            n = FACE_INPUT // s
            c = np.stack(np.mgrid[:n, :n][::-1], axis=-1).astype(np.float32).reshape(-1, 2) * s
            self.centers[s] = np.repeat(c, 2, axis=0)

    def detect(self, img, min_conf=FACE_MIN_CONF):
        """Returns [(box xyxy, conf, 5 landmarks [[x, y], ...])]."""
        lb, r = _letterbox(img, FACE_INPUT, 0)
        blob = cv2.dnn.blobFromImage(lb, 1 / 128.0, (FACE_INPUT, FACE_INPUT), (127.5, 127.5, 127.5), swapRB=True)
        outs = self.sess.run(blob)
        all_boxes, all_scores, all_kps = [], [], []
        for i, s in enumerate((8, 16, 32)):
            scores = outs[i][:, 0]
            m = scores >= min_conf
            c = self.centers[s][m]
            d = outs[i + 3][m] * s
            k = outs[i + 6][m] * s
            all_boxes.append(np.concatenate([c - d[:, :2], c + d[:, 2:]], 1))
            all_scores.append(scores[m])
            all_kps.append((k.reshape(-1, 5, 2) + c[:, None, :]))
        boxes = np.concatenate(all_boxes) / r
        scores = np.concatenate(all_scores)
        kps = np.concatenate(all_kps) / r
        return [(boxes[i], float(scores[i]), kps[i].tolist()) for i in _nms(boxes, scores, min_conf)]


def l2_normalize(v):
    return v / (np.linalg.norm(v) + 1e-10)


def align_face(img, kps):
    """Warp a face to the 112x112 ArcFace template using its 5 SCRFD landmarks."""
    m, _ = cv2.estimateAffinePartial2D(np.array(kps, dtype=np.float32), ARCFACE_TEMPLATE, method=cv2.LMEDS)
    return cv2.warpAffine(img, m, (112, 112), borderValue=0)


class ArcFace:
    """insightface ArcFace: RGB, (x - 127.5) / 127.5, NCHW 112x112 -> L2-normalised 512-d embedding."""

    def __init__(self, path, backend):
        # FP32 on every backend: embeddings are stored and compared across sessions, and FP32 on the GPU is both
        # identical to the CPU and faster than FP16 there
        self.sess = backend.session(path, 'f32', (1, 3, 112, 112))

    def embed(self, aligned_bgr):
        blob = cv2.dnn.blobFromImage(aligned_bgr, 1 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True)
        return l2_normalize(self.sess.run(blob)[0].flatten()).astype(np.float32)


def _box_area(b):
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def _intersection(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def combine_persons(per_model, thr):
    """Merge person boxes >= thr from several models ({model: [{'box', 'conf'}]}, in order) into one list.

    Boxes from the same model are never merged (two real people can overlap). A box from a later model is
    the same person as a kept box if their intersection covers >= COMBINE_OVERLAP of the smaller box (plain
    IoU misses the upper-body vs whole-body boxes the two models produce for one person); the highest IoU
    wins, and each kept box absorbs at most one box per model."""
    kept = []
    for model, persons in per_model.items():
        claimed = set()
        for p in sorted((p for p in persons if p['conf'] >= thr), key=lambda p: -p['conf']):
            best, best_iou = None, -1
            for i, k in enumerate(kept):
                if i in claimed:
                    continue
                inter = _intersection(p['box'], k['box'])
                if inter < COMBINE_OVERLAP * min(_box_area(p['box']), _box_area(k['box'])):
                    continue
                iou = inter / (_box_area(p['box']) + _box_area(k['box']) - inter)
                if iou > best_iou:
                    best, best_iou = i, iou
            if best is None:
                kept.append({'box': p['box'], 'conf': p['conf'], 'sources': [model]})
                claimed.add(len(kept) - 1)
            else:
                kept[best]['conf'] = max(kept[best]['conf'], p['conf'])
                kept[best]['sources'].append(model)
                claimed.add(best)
    return kept


def missing_models(models_dir):
    return [f for f in MODEL_FILES.values() if not os.path.isfile(os.path.join(models_dir, f))]


class Models:
    """All models, loaded once and shared by every session. Not thread safe: callers serialise use.

    inference: "cpu" or "gpu" (see the module doc). Raises FileNotFoundError for missing model files and
    InferenceBackendError when the backend can't load or run the models."""

    def __init__(self, models_dir, inference='cpu', cache_dir=None):
        missing = missing_models(models_dir)
        if missing:
            raise FileNotFoundError(f"Missing models in {models_dir}: {', '.join(missing)} (run make download_models)")
        if inference == 'cpu':
            backend = CpuBackend()
        elif inference == 'gpu':
            backend = GpuBackend(cache_dir)
        else:
            raise InferenceBackendError(f"inference is '{inference}', must be 'cpu' or 'gpu'")
        self.inference = backend.name
        self.inference_description = backend.description
        p = lambda k: os.path.join(models_dir, MODEL_FILES[k])
        try:
            self.persons = {'yolox_m': YoloxPerson(p('yolox_m'), backend),
                            'yolo11m': UltralyticsPerson(p('yolo11m'), backend)}
            self.scrfd = ScrfdFace(p('scrfd'), backend)
            self.arcface = ArcFace(p('arcface'), backend)
            # Run each model once: a backend that loads but can't run fails here, not in the first session, and
            # the slow first inference (GPU kernel setup) happens now
            blank = np.zeros((480, 640, 3), np.uint8)
            self.detect_persons(blank, 0.5)
            self.scrfd.detect(blank)
            self.arcface.embed(np.zeros((112, 112, 3), np.uint8))
        except Exception as ex:
            raise InferenceBackendError(f"Can't run the models on {backend.description}: {ex}") from ex

    def detect_persons(self, frame, thr):
        h, w = frame.shape[:2]
        per_model = {name: [{'box': clip_box(b, w, h), 'conf': round(c, 3)} for b, c in m.detect(frame, thr)]
                     for name, m in self.persons.items()}
        return combine_persons(per_model, thr)
