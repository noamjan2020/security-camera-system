from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Detection:
    x: int
    y: int
    width: int
    height: int
    confidence: float


class DetectorBackend(Protocol):
    name: str

    def detect(self, frame: np.ndarray) -> list[Detection]: ...


class HogPersonDetector:
    name = "opencv-hog"

    def __init__(self, confidence_threshold: float = 0.55, inference_size: int = 640):
        self.confidence_threshold = confidence_threshold
        self.inference_size = inference_size
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        logger.warning("Using HOG fallback detector; install an ONNX model for better accuracy")

    def detect(self, frame: np.ndarray) -> list[Detection]:
        height, width = frame.shape[:2]
        scale = min(1.0, self.inference_size / max(width, height))
        resized = cv2.resize(frame, None, fx=scale, fy=scale) if scale < 1 else frame
        boxes, weights = self.hog.detectMultiScale(
            resized, winStride=(8, 8), padding=(8, 8), scale=1.05
        )
        results: list[Detection] = []
        for (x, y, w, h), weight in zip(boxes, weights):
            # HOG weights are margins, not calibrated probabilities. This mapping is
            # only used for thresholding/display and is deliberately conservative.
            normalized = float(1.0 / (1.0 + np.exp(-float(weight))))
            if normalized < self.confidence_threshold:
                continue
            inv = 1 / scale
            results.append(
                Detection(int(x * inv), int(y * inv), int(w * inv), int(h * inv), normalized)
            )
        return results


class YoloOnnxDetector:
    name = "yolo-onnx"

    def __init__(
        self,
        model_path: Path,
        confidence_threshold: float = 0.55,
        nms_threshold: float = 0.45,
        inference_size: int = 640,
    ):
        import onnxruntime as ort

        self.confidence_threshold = confidence_threshold
        self.nms_threshold = nms_threshold
        self.inference_size = inference_size
        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, min(4, (__import__("os").cpu_count() or 2) // 2))
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name
        logger.info("Loaded ONNX detector from %s", model_path)

    @staticmethod
    def _letterbox(frame: np.ndarray, size: int) -> tuple[np.ndarray, float, int, int]:
        height, width = frame.shape[:2]
        scale = min(size / width, size / height)
        resized_w, resized_h = int(round(width * scale)), int(round(height * scale))
        resized = cv2.resize(frame, (resized_w, resized_h), interpolation=cv2.INTER_LINEAR)
        pad_x = (size - resized_w) // 2
        pad_y = (size - resized_h) // 2
        canvas = np.full((size, size, 3), 114, dtype=np.uint8)
        canvas[pad_y : pad_y + resized_h, pad_x : pad_x + resized_w] = resized
        return canvas, scale, pad_x, pad_y

    def detect(self, frame: np.ndarray) -> list[Detection]:
        image, scale, pad_x, pad_y = self._letterbox(frame, self.inference_size)
        blob = cv2.dnn.blobFromImage(image, 1 / 255.0, swapRB=True)
        output = np.asarray(self.session.run(None, {self.input_name: blob})[0])
        predictions = np.squeeze(output)
        if predictions.ndim != 2:
            raise RuntimeError(f"Unsupported YOLO output shape: {output.shape}")
        if predictions.shape[0] < predictions.shape[1] and predictions.shape[0] <= 128:
            predictions = predictions.T

        boxes_xywh: list[list[int]] = []
        scores: list[float] = []
        original_h, original_w = frame.shape[:2]
        for row in predictions:
            if row.shape[0] < 5:
                continue
            # Ultralytics detection exports use [cx,cy,w,h,class_scores...].
            class_scores = row[4:]
            person_score = float(class_scores[0])
            if person_score < self.confidence_threshold:
                continue
            cx, cy, width, height = map(float, row[:4])
            x = int((cx - width / 2 - pad_x) / scale)
            y = int((cy - height / 2 - pad_y) / scale)
            w = int(width / scale)
            h = int(height / scale)
            x = max(0, min(x, original_w - 1))
            y = max(0, min(y, original_h - 1))
            w = max(1, min(w, original_w - x))
            h = max(1, min(h, original_h - y))
            boxes_xywh.append([x, y, w, h])
            scores.append(person_score)

        if not boxes_xywh:
            return []
        indices = cv2.dnn.NMSBoxes(
            boxes_xywh, scores, self.confidence_threshold, self.nms_threshold
        )
        return [Detection(*boxes_xywh[int(index)], scores[int(index)]) for index in np.array(indices).flatten()]


class PersonDetector:
    """Selects ONNX when available and falls back to the lightweight HOG detector."""

    def __init__(
        self,
        confidence_threshold: float = 0.55,
        *,
        backend: str = "auto",
        model_path: Path | None = None,
        nms_threshold: float = 0.45,
        inference_size: int = 640,
    ):
        self.backend: DetectorBackend
        should_try_onnx = backend in {"auto", "onnx"}
        if should_try_onnx and model_path and model_path.exists():
            try:
                self.backend = YoloOnnxDetector(
                    model_path, confidence_threshold, nms_threshold, inference_size
                )
            except Exception:
                if backend == "onnx":
                    raise
                logger.exception("ONNX detector failed to initialize; falling back to HOG")
                self.backend = HogPersonDetector(confidence_threshold, inference_size)
        elif backend == "onnx":
            raise FileNotFoundError(f"ONNX detector model not found: {model_path}")
        else:
            self.backend = HogPersonDetector(confidence_threshold, inference_size)
        logger.info("Detector backend selected: %s", self.backend.name)

    @property
    def name(self) -> str:
        return self.backend.name

    def detect(self, frame: np.ndarray) -> list[Detection]:
        return self.backend.detect(frame)
