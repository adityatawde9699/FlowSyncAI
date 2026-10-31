from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass
class TrafficObservation:
    intersection_id: str
    approach: str
    source: str
    confidence: float
    vehicle_counts: dict[str, int] = field(default_factory=dict)
    queue_estimate: int | None = None
    density: float | None = None
    timestamp_seconds: float | None = None


class Detector(Protocol):
    def detect(self, frame) -> list[Detection]: ...


class YoloOpenCVDNN:
    """YOLO-compatible ONNX detector using OpenCV DNN. A real weights file is mandatory."""
    def __init__(self, weights: str | Path, labels: list[str], input_size: int = 640,
                 confidence: float = .35, nms_iou: float = .45, use_gpu: bool = False,
                 output_format: str = "yolov8"):
        path = Path(weights)
        if not path.is_file(): raise FileNotFoundError(f"YOLO ONNX weights not found: {path}")
        try: import cv2
        except ImportError as exc: raise RuntimeError("Install OpenCV (opencv-python-headless) for video perception") from exc
        self.cv2 = cv2
        self.net = cv2.dnn.readNetFromONNX(str(path))
        if use_gpu:
            try:
                self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
                self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA)
            except Exception:
                self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
                self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        self.labels = labels
        self.input_size = input_size
        self.confidence = confidence
        self.nms_iou = nms_iou
        if output_format not in ("yolov5", "yolov8"): raise ValueError("output_format must be yolov5 or yolov8")
        self.output_format = output_format

    def detect(self, frame) -> list[Detection]:
        height, width = frame.shape[:2]
        blob = self.cv2.dnn.blobFromImage(frame, 1 / 255.0, (self.input_size, self.input_size), swapRB=True, crop=False)
        self.net.setInput(blob)
        output = self.net.forward(self.net.getUnconnectedOutLayersNames())
        rows = _normalize_output(output)
        boxes, scores, names = [], [], []
        scale_x, scale_y = width / self.input_size, height / self.input_size
        for row in rows:
            if len(row) < 6: continue
            # YOLOv5 includes objectness before class scores; YOLOv8 does not.
            objectness = float(row[4]) if self.output_format == "yolov5" else 1.0
            class_scores = row[5:] if self.output_format == "yolov5" else row[4:]
            if not len(class_scores): continue
            class_id = int(class_scores.argmax())
            score = objectness * float(class_scores[class_id])
            if score < self.confidence or class_id >= len(self.labels): continue
            cx, cy, box_w, box_h = map(float, row[:4])
            x1 = max(0, (cx - box_w / 2) * scale_x); y1 = max(0, (cy - box_h / 2) * scale_y)
            x2 = min(width, (cx + box_w / 2) * scale_x); y2 = min(height, (cy + box_h / 2) * scale_y)
            boxes.append([int(x1), int(y1), int(x2-x1), int(y2-y1)])
            scores.append(score); names.append(self.labels[class_id])
        indexes = self.cv2.dnn.NMSBoxes(boxes, scores, self.confidence, self.nms_iou)
        return [Detection(names[int(i)], scores[int(i)], boxes[int(i)][0], boxes[int(i)][1],
                          boxes[int(i)][0] + boxes[int(i)][2], boxes[int(i)][1] + boxes[int(i)][3])
                for i in _flatten_indices(indexes)]


def observation_from_simulation(state, intersection_id: str, approach: str) -> TrafficObservation:
    """Label telemetry as simulated; never present model confidence as an observed detection."""
    node = next((n for n in state.intersections if n.id == intersection_id), None)
    if node is None: raise ValueError(f"unknown intersection: {intersection_id}")
    vehicles = node.queues[approach]
    counts: dict[str, int] = {}
    for vehicle in vehicles: counts[vehicle.kind.value] = counts.get(vehicle.kind.value, 0) + 1
    return TrafficObservation(intersection_id, approach, "simulation", 1.0, counts, len(vehicles), None, float(state.time))


def process_video(path: str | Path, detector: Detector, estimator: QueueEstimator,
                  intersection_id: str, approach: str, roi: tuple[float, float, float, float],
                  frame_stride: int = 1):
    """Yield timestamped observations from a recorded file; raises instead of fabricating on decode failure."""
    try: import cv2
    except ImportError as exc: raise RuntimeError("Install OpenCV (opencv-python-headless) to read video") from exc
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened(): raise OSError(f"Unable to open video file: {path}")
    if frame_stride < 1: raise ValueError("frame_stride must be at least 1")
    fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
    frame_index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok: break
            if frame_index % frame_stride == 0:
                observation = estimator.update(detector.detect(frame), roi, intersection_id, approach, frame.shape[:2])
                observation.timestamp_seconds = frame_index/fps if fps > 0 else None
                yield observation
            frame_index += 1
    finally:
        capture.release()


def process_video(path: str | Path, detector: Detector, estimator: QueueEstimator,
                  intersection_id: str, approach: str, roi: tuple[float, float, float, float],
                  frame_stride: int = 1):
    """Yield timestamped observations from a recorded file; raises instead of fabricating on decode failure."""
    try: import cv2
    except ImportError as exc: raise RuntimeError("Install OpenCV (opencv-python-headless) to read video") from exc
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened(): raise OSError(f"Unable to open video file: {path}")
    if frame_stride < 1: raise ValueError("frame_stride must be at least 1")
    fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
    frame_index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok: break
            if frame_index % frame_stride == 0:
                observation = estimator.update(detector.detect(frame), roi, intersection_id, approach, frame.shape[:2])
                observation.timestamp_seconds = frame_index/fps if fps > 0 else None
                yield observation
            frame_index += 1
    finally:
        capture.release()


class QueueEstimator:
    """Lightweight IoU tracker; queue count requires stationary detections in a caller-provided ROI."""
    def __init__(self, stationary_frames: int = 3, motion_threshold_px: float = 4.0, max_iou_distance: float = .7):
        self.stationary_frames = stationary_frames
        self.motion_threshold_px = motion_threshold_px
        self.max_iou_distance = max_iou_distance
        self._tracks: dict[int, dict] = {}
        self._next_id = 0

    def update(self, detections: list[Detection], roi: tuple[float, float, float, float],
               intersection_id: str, approach: str, frame_shape: tuple[int, int]) -> TrafficObservation:
        matched: set[int] = set()
        for detection in detections:
            best_id, best_iou = None, 0.0
            for track_id, track in self._tracks.items():
                if track_id in matched or track["label"] != detection.label: continue
                iou = _iou(track["box"], detection)
                if iou > best_iou: best_id, best_iou = track_id, iou
            center = ((detection.x1+detection.x2)/2, (detection.y1+detection.y2)/2)
            if best_id is not None and 1 - best_iou <= self.max_iou_distance:
                track = self._tracks[best_id]
                old = track["center"]
                movement = ((center[0]-old[0])**2 + (center[1]-old[1])**2)**.5
                track["stationary"] = track["stationary"] + 1 if movement <= self.motion_threshold_px else 0
                track.update(box=detection, center=center, confidence=detection.confidence)
                matched.add(best_id)
            else:
                self._next_id += 1
                self._tracks[self._next_id] = {"box": detection, "center": center,
                    "label": detection.label, "stationary": 0, "confidence": detection.confidence}
                matched.add(self._next_id)
        stale = set(self._tracks) - matched
        for track_id in stale: self._tracks.pop(track_id, None)
        x1, y1, x2, y2 = roi
        height, width = frame_shape
        if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 1:
            x1, x2, y1, y2 = x1*width, x2*width, y1*height, y2*height
        in_roi = [track for track in self._tracks.values() if x1 <= track["center"][0] <= x2 and y1 <= track["center"][1] <= y2]
        counts: dict[str, int] = {}
        for track in in_roi: counts[track["label"]] = counts.get(track["label"], 0) + 1
        queued = [t for t in in_roi if t["stationary"] >= self.stationary_frames]
        roi_area = max(1.0, (x2-x1) * (y2-y1))
        confidence = sum(t["confidence"] for t in in_roi)/len(in_roi) if in_roi else 0.0
        return TrafficObservation(intersection_id, approach, "video:yolo-opencv", confidence,
            counts, len(queued), len(in_roi)*1_000_000/roi_area, None)


def _normalize_output(outputs):
    import numpy as np
    array = np.asarray(outputs[0])
    array = np.squeeze(array)
    if array.ndim != 2: raise ValueError(f"Unsupported YOLO output shape: {array.shape}")
    if array.shape[0] < array.shape[1] and array.shape[0] < 512: array = array.T
    return array


def _flatten_indices(indexes):
    if indexes is None: return []
    try: return [int(i[0]) if hasattr(i, "__len__") else int(i) for i in indexes]
    except TypeError: return []


def _iou(a: Detection, b: Detection) -> float:
    x1, y1 = max(a.x1, b.x1), max(a.y1, b.y1)
    x2, y2 = min(a.x2, b.x2), min(a.y2, b.y2)
    intersection = max(0, x2-x1) * max(0, y2-y1)
    area_a = max(0, a.x2-a.x1)*max(0, a.y2-a.y1)
    area_b = max(0, b.x2-b.x1)*max(0, b.y2-b.y1)
    return intersection / max(1e-6, area_a+area_b-intersection)
