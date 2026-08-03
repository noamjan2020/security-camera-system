from datetime import datetime, timedelta, timezone
from pathlib import Path

from homeguard_agent.database import EventDatabase
from homeguard_agent.models import EventRecord, FaceResult


def event(event_id: str, at: datetime, image: Path) -> EventRecord:
    return EventRecord(
        id=event_id,
        timestamp=at,
        camera_name="Test",
        screenshot_path=image,
        person_confidence=0.9,
        face_result=FaceResult.UNKNOWN,
    )


def test_add_list_and_retention(tmp_path):
    db = EventDatabase(tmp_path / "events.db")
    old = tmp_path / "old.jpg"; old.write_bytes(b"old")
    fresh = tmp_path / "fresh.jpg"; fresh.write_bytes(b"fresh")
    now = datetime.now(timezone.utc)
    db.add_event(event("old", now - timedelta(hours=2), old))
    db.add_event(event("fresh", now, fresh))
    assert [item.id for item in db.list_events()] == ["fresh", "old"]
    removed = db.delete_expired(60)
    assert removed == [old]
    assert [item.id for item in db.list_events()] == ["fresh"]


def test_nonce_replay_is_rejected(tmp_path):
    db = EventDatabase(tmp_path / "events.db")
    expires = datetime.now(timezone.utc) + timedelta(minutes=1)
    assert db.consume_nonce("a" * 16, expires) is True
    assert db.consume_nonce("a" * 16, expires) is False
