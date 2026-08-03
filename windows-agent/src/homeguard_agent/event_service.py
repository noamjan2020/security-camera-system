from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import logging
import uuid

import cv2
import numpy as np

from .database import EventDatabase
from .detector import Detection
from .models import EventRecord, FaceResult, UploadStatus

logger = logging.getLogger(__name__)


class EventService:
    def __init__(
        self,
        database: EventDatabase,
        media_dir: Path,
        camera_name: str,
        *,
        queue_remote_uploads: bool = False,
        jpeg_quality: int = 86,
    ):
        self.database = database
        self.media_dir = media_dir
        self.camera_name = camera_name
        self.queue_remote_uploads = queue_remote_uploads
        self.jpeg_quality = jpeg_quality
        self.media_dir.mkdir(parents=True, exist_ok=True)

    def create_person_event(
        self,
        frame: np.ndarray,
        confidence: float,
        detection: Detection | None = None,
        *,
        face_result: FaceResult = FaceResult.NO_FACE,
        person_name: str | None = None,
        remote_alert: bool = True,
    ) -> EventRecord:
        event_id = uuid.uuid4().hex
        timestamp = datetime.now(timezone.utc)
        file_name = f"{timestamp.strftime('%Y%m%dT%H%M%S')}_{event_id}.jpg"
        path = self.media_dir / file_name
        if not cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]):
            logger.error("Failed to write event screenshot", extra={"event_id": event_id})
            raise RuntimeError("Failed to write event screenshot")
        queue_upload = self.queue_remote_uploads and remote_alert
        event = EventRecord(
            id=event_id,
            timestamp=timestamp,
            camera_name=self.camera_name,
            screenshot_path=path,
            person_confidence=min(1.0, max(0.0, confidence)),
            face_result=face_result,
            person_name=person_name,
            notification_status=(UploadStatus.QUEUED.value if queue_upload else UploadStatus.LOCAL_ONLY.value),
            bbox_x=detection.x if detection else None,
            bbox_y=detection.y if detection else None,
            bbox_width=detection.width if detection else None,
            bbox_height=detection.height if detection else None,
        )
        self.database.add_event(event, queue_upload=queue_upload)
        logger.info(
            "Person event created",
            extra={"event_id": event.id, "face_result": face_result.value, "remote_alert": remote_alert},
        )
        return event

    def create_unknown_event(
        self,
        frame: np.ndarray,
        confidence: float,
        detection: Detection | None = None,
    ) -> EventRecord:
        return self.create_person_event(
            frame,
            confidence,
            detection,
            face_result=FaceResult.UNKNOWN,
            remote_alert=True,
        )

    def cleanup(self, retention_minutes: int) -> int:
        paths = self.database.delete_expired(retention_minutes)
        removed = 0
        for path in paths:
            try:
                path.unlink(missing_ok=True)
                removed += 1
            except OSError:
                logger.exception("Failed deleting expired event media", extra={"event_id": path.name})
        if paths:
            logger.info("Retention cleanup removed %d of %d files", removed, len(paths))
        return removed

    def delete_event(self, event_id: str) -> bool:
        path = self.database.delete_event(event_id)
        if path is None:
            return False
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.exception("Event row deleted but media cleanup failed", extra={"event_id": event_id})
        logger.info("Event deleted", extra={"event_id": event_id})
        return True
