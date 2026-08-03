from datetime import datetime, timedelta, timezone
from pathlib import Path

from homeguard_agent.database import EventDatabase
from homeguard_agent.models import EventRecord, FaceResult, UploadStatus


def make_event(tmp_path: Path, event_id: str = "event-1") -> EventRecord:
    image = tmp_path / f"{event_id}.jpg"
    image.write_bytes(b"jpeg")
    return EventRecord(
        id=event_id,
        timestamp=datetime.now(timezone.utc),
        camera_name="Test",
        screenshot_path=image,
        person_confidence=0.8,
        face_result=FaceResult.UNKNOWN,
        notification_status=UploadStatus.QUEUED.value,
        bbox_x=1,
        bbox_y=2,
        bbox_width=3,
        bbox_height=4,
    )


def test_upload_queue_claim_retry_and_complete(tmp_path: Path):
    db = EventDatabase(tmp_path / "events.db")
    event = make_event(tmp_path)
    db.add_event(event, queue_upload=True)
    assert db.upload_queue_depth() == 1

    job = db.claim_due_upload()
    assert job is not None
    assert job.event_id == event.id
    db.fail_upload(job.id, "offline", datetime.now(timezone.utc) - timedelta(seconds=1))

    retry = db.claim_due_upload()
    assert retry is not None
    assert retry.attempts == 1
    db.complete_upload(retry.id)
    assert db.upload_queue_depth() == 0


def test_receipts_and_delete(tmp_path: Path):
    db = EventDatabase(tmp_path / "events.db")
    event = make_event(tmp_path)
    db.add_event(event)
    db.set_playback_receipt("cmd", "playing", "ok")
    assert db.get_playback_receipt("cmd")["status"] == "playing"
    assert db.delete_event(event.id) == event.screenshot_path
    assert db.get_event(event.id) is None


def test_pairing_challenge_is_one_time_and_device_can_be_revoked(tmp_path: Path):
    from homeguard_agent.pairing import token_hash

    db = EventDatabase(tmp_path / "events.db")
    expires = datetime.now(timezone.utc) + timedelta(minutes=2)
    db.create_pairing_challenge(token_hash("code"), expires)
    assert db.consume_pairing_challenge(token_hash("code")) is True
    assert db.consume_pairing_challenge(token_hash("code")) is False

    db.register_paired_device("phone-1", "Noam phone", token_hash("device-token"))
    assert db.authenticate_paired_device(token_hash("device-token")) == "phone-1"
    assert db.revoke_paired_device("phone-1") is True
    assert db.authenticate_paired_device(token_hash("device-token")) is None
    db.close()
