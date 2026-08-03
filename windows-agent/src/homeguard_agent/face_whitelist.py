from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import base64
import json
import logging
from threading import RLock

import cv2
import numpy as np

from .detector import Detection
from .security import protect_local_bytes, unprotect_local_bytes

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class FaceMatch:
    matched: bool
    person_name: str | None
    similarity: float
    usable_face: bool


class FaceWhitelist:
    """Encrypted local face-embedding store. Raw enrollment photos are not retained."""

    def __init__(self, store_path: Path, threshold: float = 0.50):
        self.store_path = store_path
        self.threshold = threshold
        self._embeddings: dict[str, list[np.ndarray]] = {}
        self._lock = RLock()
        self.load()

    def load(self) -> None:
        if not self.store_path.exists():
            return
        try:
            payload = json.loads(unprotect_local_bytes(self.store_path.read_bytes()).decode("utf-8"))
            with self._lock:
                self._embeddings = {
                    name: [
                        np.frombuffer(base64.b64decode(item), dtype=np.float32).copy()
                        for item in vectors
                    ]
                    for name, vectors in payload.get("people", {}).items()
                    if isinstance(name, str) and isinstance(vectors, list)
                }
            logger.info("Face whitelist loaded", extra={"people_count": len(self._embeddings)})
        except Exception:
            logger.exception("Face whitelist could not be loaded; failing closed")
            with self._lock:
                self._embeddings = {}

    def save(self) -> None:
        with self._lock:
            payload = {
                "version": 1,
                "people": {
                    name: [base64.b64encode(vector.astype(np.float32).tobytes()).decode("ascii") for vector in vectors]
                    for name, vectors in self._embeddings.items()
                },
            }
        raw = protect_local_bytes(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.store_path.with_suffix(self.store_path.suffix + ".tmp")
        temp.write_bytes(raw)
        try:
            temp.chmod(0o600)
        except OSError:
            pass
        temp.replace(self.store_path)
        logger.info("Face whitelist saved", extra={"people_count": len(payload["people"])})

    def people(self) -> dict[str, int]:
        with self._lock:
            return {name: len(vectors) for name, vectors in sorted(self._embeddings.items())}

    def enroll(self, name: str, embedding: np.ndarray) -> int:
        normalized_name = " ".join(name.strip().split())[:100]
        if not normalized_name:
            raise ValueError("Person name is required")
        vector = self._normalize(embedding)
        with self._lock:
            vectors = self._embeddings.setdefault(normalized_name, [])
            if len(vectors) >= 12:
                raise ValueError("A person can have at most 12 enrollment samples")
            vectors.append(vector)
            count = len(vectors)
        self.save()
        logger.info("Face sample enrolled", extra={"person_name": normalized_name, "sample_count": count})
        return count

    def remove(self, name: str) -> bool:
        with self._lock:
            removed = self._embeddings.pop(name, None) is not None
        if removed:
            self.save()
            logger.warning("Whitelisted person removed", extra={"person_name": name})
        return removed

    def match(self, embedding: np.ndarray | None) -> FaceMatch:
        if embedding is None:
            return FaceMatch(False, None, 0.0, False)
        candidate = self._normalize(embedding)
        best_name: str | None = None
        best_score = -1.0
        with self._lock:
            items = list(self._embeddings.items())
        for name, vectors in items:
            for vector in vectors:
                score = float(np.dot(candidate, vector))
                if score > best_score:
                    best_name, best_score = name, score
        matched = best_name is not None and best_score >= self.threshold
        return FaceMatch(matched, best_name if matched else None, max(0.0, best_score), True)

    @staticmethod
    def _normalize(embedding: np.ndarray) -> np.ndarray:
        vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
        if vector.size < 16 or not np.isfinite(vector).all():
            raise ValueError("Invalid face embedding")
        norm = float(np.linalg.norm(vector))
        if norm <= 1e-8:
            raise ValueError("Empty face embedding")
        return vector / norm


class OpenCvFaceEngine:
    """Optional YuNet + SFace provider using the already-installed OpenCV runtime."""

    def __init__(
        self,
        detector_model: Path,
        recognizer_model: Path,
        whitelist: FaceWhitelist,
        *,
        detection_threshold: float = 0.90,
    ):
        self.whitelist = whitelist
        self.available = detector_model.exists() and recognizer_model.exists()
        self.unavailable_reason: str | None = None
        self._lock = RLock()
        self._detector = None
        self._recognizer = None
        if not self.available:
            self.unavailable_reason = "YuNet/SFace model files are missing"
            logger.warning("Face recognition disabled: %s", self.unavailable_reason)
            return
        try:
            self._detector = cv2.FaceDetectorYN.create(
                str(detector_model), "", (320, 320), detection_threshold, 0.3, 1000
            )
            self._recognizer = cv2.FaceRecognizerSF.create(str(recognizer_model), "")
            logger.info("OpenCV face recognition models loaded")
        except Exception as exc:
            self.available = False
            self.unavailable_reason = str(exc)
            logger.exception("Face recognition model initialization failed")

    def recognize(self, frame: np.ndarray, person: Detection | None = None) -> FaceMatch:
        embedding = self.extract_embedding(frame, person)
        return self.whitelist.match(embedding)

    def extract_embedding(self, frame: np.ndarray, person: Detection | None = None) -> np.ndarray | None:
        if not self.available or self._detector is None or self._recognizer is None:
            return None
        crop, offset_x, offset_y = self._person_crop(frame, person)
        if crop.size == 0 or crop.shape[0] < 40 or crop.shape[1] < 40:
            return None
        try:
            with self._lock:
                self._detector.setInputSize((crop.shape[1], crop.shape[0]))
                _, faces = self._detector.detect(crop)
                if faces is None or len(faces) == 0:
                    return None
                face = max(faces, key=lambda item: float(item[2] * item[3]) * float(item[-1]))
                aligned = self._recognizer.alignCrop(crop, face)
                feature = self._recognizer.feature(aligned)
            logger.debug(
                "Usable face extracted",
                extra={
                    "face_score": float(face[-1]),
                    "face_x": int(face[0] + offset_x),
                    "face_y": int(face[1] + offset_y),
                },
            )
            return np.asarray(feature, dtype=np.float32).reshape(-1)
        except Exception:
            logger.exception("Face embedding extraction failed")
            return None

    @staticmethod
    def _person_crop(frame: np.ndarray, person: Detection | None) -> tuple[np.ndarray, int, int]:
        if person is None:
            return frame, 0, 0
        margin_x = int(person.width * 0.12)
        margin_y = int(person.height * 0.08)
        x1 = max(0, person.x - margin_x)
        y1 = max(0, person.y - margin_y)
        x2 = min(frame.shape[1], person.x + person.width + margin_x)
        y2 = min(frame.shape[0], person.y + person.height + margin_y)
        return frame[y1:y2, x1:x2], x1, y1
