from pathlib import Path

import numpy as np

from homeguard_agent.database import EventDatabase
from homeguard_agent.event_service import EventService
from homeguard_agent.models import FaceResult, UploadStatus


def test_whitelisted_event_is_local_only(tmp_path: Path):
    db = EventDatabase(tmp_path / "events.db")
    service = EventService(db, tmp_path / "media", "Camera", queue_remote_uploads=True)
    event = service.create_person_event(
        np.zeros((32, 32, 3), dtype=np.uint8),
        0.9,
        face_result=FaceResult.WHITELISTED,
        person_name="Noam",
        remote_alert=False,
    )
    assert event.notification_status == UploadStatus.LOCAL_ONLY.value
    assert db.upload_queue_depth() == 0
    db.close()


def test_unknown_event_is_queued_when_cloud_enabled(tmp_path: Path):
    db = EventDatabase(tmp_path / "events.db")
    service = EventService(db, tmp_path / "media", "Camera", queue_remote_uploads=True)
    event = service.create_person_event(
        np.zeros((32, 32, 3), dtype=np.uint8),
        0.9,
        face_result=FaceResult.NO_FACE,
        remote_alert=True,
    )
    assert event.notification_status == UploadStatus.QUEUED.value
    assert db.upload_queue_depth() == 1
    db.close()
