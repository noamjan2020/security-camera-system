from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
import logging
import time

import cv2
import numpy as np

from .app_state import AppStateStore
from .detector import Detection, PersonDetector
from .event_service import EventService
from .face_whitelist import OpenCvFaceEngine
from .models import FaceResult

logger = logging.getLogger(__name__)


class CameraService:
    """Low-latency camera pipeline with decoupled capture and inference.

    The queue stores only the newest frame, preventing slow inference from creating
    latency or unbounded memory growth.
    """

    def __init__(
        self,
        camera_index: int,
        detector: PersonDetector,
        events: EventService,
        state_store: AppStateStore,
        visible_seconds: float,
        cooldown_seconds: int,
        max_fps: int,
        inference_fps: float,
        *,
        width: int = 1280,
        height: int = 720,
        jpeg_quality: int = 86,
        face_engine: OpenCvFaceEngine | None = None,
        record_whitelisted_events: bool = True,
        detection_zone: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0),
        exclusion_zones: list[tuple[float, float, float, float]] | None = None,
        on_event: Callable[[str], None] | None = None,
        capture_factory: Callable[[int], cv2.VideoCapture] | None = None,
    ):
        self.camera_index = camera_index
        self.detector = detector
        self.events = events
        self.state_store = state_store
        self.visible_seconds = visible_seconds
        self.cooldown_seconds = cooldown_seconds
        self.max_fps = max_fps
        self.inference_fps_target = inference_fps
        self.width = width
        self.height = height
        self.jpeg_quality = jpeg_quality
        self.face_engine = face_engine
        self.record_whitelisted_events = record_whitelisted_events
        self.detection_zone = detection_zone
        self.exclusion_zones = list(exclusion_zones or [])
        self.on_event = on_event
        self.capture_factory = capture_factory or self._default_capture

        self._shutdown = Event()
        self._capture_thread: Thread | None = None
        self._detection_thread: Thread | None = None
        self._frame_queue: Queue[tuple[float, np.ndarray]] = Queue(maxsize=1)
        self._frame_lock = Lock()
        self._latest_frame: np.ndarray | None = None
        self.active = False
        self.last_error: str | None = None
        self.last_frame_at: datetime | None = None
        self.last_event_at: datetime | None = None
        self.fps = 0.0
        self.inference_fps = 0.0

    def _default_capture(self, camera_index: int) -> cv2.VideoCapture:
        backend = cv2.CAP_DSHOW if __import__("platform").system() == "Windows" else cv2.CAP_ANY
        return cv2.VideoCapture(camera_index, backend)

    def start(self) -> None:
        if self._capture_thread and self._capture_thread.is_alive():
            return
        self._shutdown.clear()
        self._capture_thread = Thread(target=self._capture_loop, name="camera-capture", daemon=True)
        self._detection_thread = Thread(target=self._detection_loop, name="camera-inference", daemon=True)
        self._capture_thread.start()
        self._detection_thread.start()
        logger.info("Camera service threads started", extra={"camera_index": self.camera_index})

    def shutdown(self) -> None:
        self._shutdown.set()
        for thread in (self._capture_thread, self._detection_thread):
            if thread:
                thread.join(timeout=6)
        self.active = False
        logger.info("Camera service stopped", extra={"camera_index": self.camera_index})

    def pause(self) -> None:
        self.state_store.set_privacy_paused(True)
        self.active = False
        logger.warning("Camera privacy pause enabled", extra={"camera_index": self.camera_index})

    def resume(self) -> None:
        self.state_store.set_privacy_paused(False)
        logger.warning("Camera privacy pause cleared", extra={"camera_index": self.camera_index})

    def emergency_disable(self, reason: str = "Local emergency button") -> None:
        self.state_store.emergency_disable(reason)
        self.active = False
        with self._frame_lock:
            self._latest_frame = None
        self._drain_queue()

    def clear_emergency_locally(self) -> None:
        self.state_store.clear_emergency_locally()

    def snapshot_frame(self) -> np.ndarray | None:
        state = self.state_store.snapshot()
        if state.privacy_paused or state.emergency_disabled:
            return None
        with self._frame_lock:
            return self._latest_frame.copy() if self._latest_frame is not None else None

    def snapshot_jpeg(self) -> bytes | None:
        frame = self.snapshot_frame()
        if frame is None:
            return None
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        return encoded.tobytes() if ok else None

    def _capture_loop(self) -> None:
        frame_interval = 1 / max(self.max_fps, 1)
        reconnect_delay = 1.0
        while not self._shutdown.is_set():
            state = self.state_store.snapshot()
            if state.privacy_paused or state.emergency_disabled:
                self.active = False
                self._shutdown.wait(0.25)
                continue

            capture = self.capture_factory(self.camera_index)
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not capture.isOpened():
                self.last_error = f"Camera {self.camera_index} unavailable"
                logger.error("%s; retrying in %.1fs", self.last_error, reconnect_delay)
                capture.release()
                self._shutdown.wait(reconnect_delay)
                reconnect_delay = min(10.0, reconnect_delay * 1.5)
                continue

            reconnect_delay = 1.0
            self.active = True
            self.last_error = None
            logger.info("Camera opened", extra={"camera_index": self.camera_index})
            frames = 0
            fps_started = time.monotonic()
            try:
                while not self._shutdown.is_set():
                    state = self.state_store.snapshot()
                    if state.privacy_paused or state.emergency_disabled:
                        break
                    started = time.monotonic()
                    ok, frame = capture.read()
                    if not ok or frame is None:
                        self.last_error = "Camera read failed"
                        logger.warning("Camera read failed; reconnecting", extra={"camera_index": self.camera_index})
                        break
                    timestamp = time.monotonic()
                    with self._frame_lock:
                        self._latest_frame = frame.copy()
                    self.last_frame_at = datetime.now(timezone.utc)
                    self._offer_latest((timestamp, frame))
                    frames += 1
                    elapsed = timestamp - fps_started
                    if elapsed >= 2:
                        self.fps = frames / elapsed
                        frames = 0
                        fps_started = timestamp
                    delay = frame_interval - (time.monotonic() - started)
                    if delay > 0:
                        self._shutdown.wait(delay)
            except Exception:
                self.last_error = "Camera capture loop exception"
                logger.exception("Camera capture loop failed", extra={"camera_index": self.camera_index})
            finally:
                capture.release()
                self.active = False
                logger.info("Camera released", extra={"camera_index": self.camera_index})
            if not self._shutdown.is_set():
                self._shutdown.wait(0.5)

    def _detection_loop(self) -> None:
        person_first_seen: float | None = None
        last_alert_monotonic = -1e9
        inference_interval = 1 / max(self.inference_fps_target, 0.1)
        last_inference_at = -1e9
        inferences = 0
        inference_started = time.monotonic()
        best_frame: np.ndarray | None = None
        best_detection: Detection | None = None
        best_score = -1.0

        while not self._shutdown.is_set():
            try:
                captured_at, frame = self._frame_queue.get(timeout=0.5)
            except Empty:
                continue
            state = self.state_store.snapshot()
            if state.privacy_paused or state.emergency_disabled:
                person_first_seen = None
                best_frame = None
                continue
            if captured_at - last_inference_at < inference_interval:
                continue
            last_inference_at = captured_at
            started = time.monotonic()
            try:
                detections = [
                    detection
                    for detection in self.detector.detect(frame)
                    if self._detection_allowed(detection, frame.shape[1], frame.shape[0])
                ]
            except Exception:
                logger.exception("Person inference failed")
                self.last_error = "Person detector failed"
                continue
            duration_ms = int((time.monotonic() - started) * 1000)
            inferences += 1
            elapsed = time.monotonic() - inference_started
            if elapsed >= 2:
                self.inference_fps = inferences / elapsed
                inferences = 0
                inference_started = time.monotonic()
            logger.debug("Inference completed with %d detections", len(detections), extra={"duration_ms": duration_ms})

            now = time.monotonic()
            if detections:
                strongest = max(detections, key=lambda item: item.confidence)
                person_first_seen = person_first_seen or now
                clarity = self._clarity_score(frame, strongest)
                score = clarity * (0.5 + strongest.confidence)
                if score > best_score:
                    best_frame = frame.copy()
                    best_detection = strongest
                    best_score = score
                visible_for = now - person_first_seen
                cooldown_ok = now - last_alert_monotonic >= self.cooldown_seconds
                if visible_for >= self.visible_seconds and cooldown_ok and best_frame is not None:
                    try:
                        detection = best_detection or strongest
                        match = self.face_engine.recognize(best_frame, detection) if self.face_engine else None
                        whitelisted = bool(match and match.matched)
                        face_result = (
                            FaceResult.WHITELISTED
                            if whitelisted
                            else FaceResult.UNKNOWN
                            if match and match.usable_face
                            else FaceResult.NO_FACE
                        )
                        logger.info(
                            "Face decision completed",
                            extra={
                                "face_result": face_result.value,
                                "person_name": match.person_name if match else None,
                                "similarity": round(match.similarity, 4) if match else 0.0,
                            },
                        )
                        event = None
                        if not whitelisted or self.record_whitelisted_events:
                            event = self.events.create_person_event(
                                best_frame,
                                detection.confidence,
                                detection,
                                face_result=face_result,
                                person_name=match.person_name if match else None,
                                remote_alert=not whitelisted,
                            )
                            self.last_event_at = event.timestamp
                        last_alert_monotonic = now
                        if whitelisted:
                            logger.info(
                                "Whitelisted person suppressed remote alert",
                                extra={"event_id": event.id if event else None, "person_name": match.person_name},
                            )
                        elif event is not None:
                            logger.info(
                                "Detection promoted to alert after %.2fs visible",
                                visible_for,
                                extra={"event_id": event.id},
                            )
                            if self.on_event:
                                self.on_event(event.id)
                    except Exception:
                        logger.exception("Failed creating person event")
                    best_frame = None
                    best_detection = None
                    best_score = -1.0
            else:
                person_first_seen = None
                best_frame = None
                best_detection = None
                best_score = -1.0

    def _offer_latest(self, item: tuple[float, np.ndarray]) -> None:
        try:
            self._frame_queue.put_nowait(item)
        except Full:
            try:
                self._frame_queue.get_nowait()
            except Empty:
                pass
            try:
                self._frame_queue.put_nowait(item)
            except Full:
                pass

    def _drain_queue(self) -> None:
        while True:
            try:
                self._frame_queue.get_nowait()
            except Empty:
                return


    def _detection_allowed(self, detection: Detection, frame_width: int, frame_height: int) -> bool:
        """Use the person's center point against normalized include/exclude zones."""
        center_x = (detection.x + detection.width / 2) / max(frame_width, 1)
        center_y = (detection.y + detection.height / 2) / max(frame_height, 1)
        if not self._point_in_zone(center_x, center_y, self.detection_zone):
            return False
        return not any(self._point_in_zone(center_x, center_y, zone) for zone in self.exclusion_zones)

    @staticmethod
    def _point_in_zone(
        x: float, y: float, zone: tuple[float, float, float, float]
    ) -> bool:
        zone_x, zone_y, width, height = zone
        return zone_x <= x <= zone_x + width and zone_y <= y <= zone_y + height

    @staticmethod
    def _clarity_score(frame: np.ndarray, detection: Detection) -> float:
        x1 = max(0, detection.x)
        y1 = max(0, detection.y)
        x2 = min(frame.shape[1], detection.x + detection.width)
        y2 = min(frame.shape[0], detection.y + detection.height)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            crop = frame
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())
