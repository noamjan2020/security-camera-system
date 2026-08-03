from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock

from .models import EventRecord, FaceResult, UploadJob, UploadStatus

logger = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    camera_name TEXT NOT NULL,
    screenshot_path TEXT NOT NULL,
    person_confidence REAL NOT NULL,
    face_result TEXT NOT NULL,
    person_name TEXT,
    notification_status TEXT NOT NULL,
    viewed INTEGER NOT NULL DEFAULT 0,
    bbox_x INTEGER,
    bbox_y INTEGER,
    bbox_width INTEGER,
    bbox_height INTEGER
);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(notification_status, timestamp);
CREATE TABLE IF NOT EXISTS used_nonces (
    nonce TEXT PRIMARY KEY,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS upload_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE REFERENCES events(id) ON DELETE CASCADE,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT,
    locked_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_upload_jobs_due ON upload_jobs(next_attempt_at, locked_at);
CREATE TABLE IF NOT EXISTS pairing_challenges (
    code_hash TEXT PRIMARY KEY,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    claimed_at TEXT
);
CREATE TABLE IF NOT EXISTS paired_devices (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_seen_at TEXT,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_paired_devices_token ON paired_devices(token_hash, revoked_at);
CREATE TABLE IF NOT EXISTS playback_receipts (
    command_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
"""


class EventDatabase:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(path, check_same_thread=False, timeout=15)
        self._connection.row_factory = sqlite3.Row
        with self._connection:
            self._connection.executescript(SCHEMA)
        self._migrate_legacy_columns()
        logger.info("Database opened", extra={"event_id": "database_open"})

    def _migrate_legacy_columns(self) -> None:
        columns = {row[1] for row in self._connection.execute("PRAGMA table_info(events)")}
        additions = {
            "bbox_x": "INTEGER",
            "bbox_y": "INTEGER",
            "bbox_width": "INTEGER",
            "bbox_height": "INTEGER",
        }
        with self._connection:
            for name, kind in additions.items():
                if name not in columns:
                    self._connection.execute(f"ALTER TABLE events ADD COLUMN {name} {kind}")
                    logger.info("Applied database migration", extra={"event_id": f"add_{name}"})

    def close(self) -> None:
        with self._lock:
            self._connection.close()
        logger.info("Database closed")

    def integrity_check(self) -> bool:
        with self._lock:
            result = self._connection.execute("PRAGMA quick_check").fetchone()[0]
        ok = result == "ok"
        (logger.info if ok else logger.error)("Database integrity check: %s", result)
        return ok

    def add_event(self, event: EventRecord, queue_upload: bool = False) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO events (
                    id,timestamp,camera_name,screenshot_path,person_confidence,face_result,
                    person_name,notification_status,viewed,bbox_x,bbox_y,bbox_width,bbox_height
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.id,
                    event.timestamp.isoformat(),
                    event.camera_name,
                    str(event.screenshot_path),
                    event.person_confidence,
                    event.face_result.value,
                    event.person_name,
                    event.notification_status,
                    int(event.viewed),
                    event.bbox_x,
                    event.bbox_y,
                    event.bbox_width,
                    event.bbox_height,
                ),
            )
            if queue_upload:
                self._connection.execute(
                    "INSERT OR IGNORE INTO upload_jobs(event_id,next_attempt_at,created_at) VALUES(?,?,?)",
                    (event.id, now, now),
                )
        logger.info("Event stored", extra={"event_id": event.id})

    def list_events(self, limit: int = 50, since: datetime | None = None) -> list[EventRecord]:
        query = "SELECT * FROM events"
        params: list[object] = []
        if since is not None:
            query += " WHERE timestamp >= ?"
            params.append(since.isoformat())
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(min(max(limit, 1), 500))
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [self._to_event(row) for row in rows]

    def get_event(self, event_id: str) -> EventRecord | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return self._to_event(row) if row else None

    def mark_viewed(self, event_id: str) -> bool:
        with self._lock, self._connection:
            cur = self._connection.execute("UPDATE events SET viewed = 1 WHERE id = ?", (event_id,))
        return cur.rowcount == 1

    def update_event_status(self, event_id: str, status: UploadStatus | str) -> None:
        value = status.value if isinstance(status, UploadStatus) else status
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE events SET notification_status = ? WHERE id = ?", (value, event_id)
            )
        logger.debug("Event status changed to %s", value, extra={"event_id": event_id})

    def delete_event(self, event_id: str) -> Path | None:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT screenshot_path FROM events WHERE id = ?", (event_id,)
            ).fetchone()
            if row:
                self._connection.execute("DELETE FROM events WHERE id = ?", (event_id,))
        return Path(row[0]) if row else None

    def delete_expired(self, retention_minutes: int) -> list[Path]:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=retention_minutes)
        with self._lock:
            rows = self._connection.execute(
                "SELECT screenshot_path FROM events WHERE timestamp < ?", (cutoff.isoformat(),)
            ).fetchall()
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM events WHERE timestamp < ?", (cutoff.isoformat(),))
        return [Path(row[0]) for row in rows]

    def consume_nonce(self, nonce: str, expires_at: datetime) -> bool:
        now = datetime.now(timezone.utc)
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM used_nonces WHERE expires_at < ?", (now.isoformat(),))
            try:
                self._connection.execute(
                    "INSERT INTO used_nonces(nonce, expires_at) VALUES (?, ?)",
                    (nonce, expires_at.isoformat()),
                )
                return True
            except sqlite3.IntegrityError:
                logger.warning("Replay nonce rejected")
                return False

    def queue_upload(self, event_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO upload_jobs(event_id,next_attempt_at,created_at) VALUES(?,?,?)",
                (event_id, now, now),
            )
            self._connection.execute(
                "UPDATE events SET notification_status=? WHERE id=?",
                (UploadStatus.QUEUED.value, event_id),
            )

    def claim_due_upload(self, lock_seconds: int = 120) -> UploadJob | None:
        now = datetime.now(timezone.utc)
        stale = now - timedelta(seconds=lock_seconds)
        with self._lock, self._connection:
            row = self._connection.execute(
                """SELECT * FROM upload_jobs
                   WHERE next_attempt_at <= ? AND (locked_at IS NULL OR locked_at < ?)
                   ORDER BY next_attempt_at, id LIMIT 1""",
                (now.isoformat(), stale.isoformat()),
            ).fetchone()
            if not row:
                return None
            self._connection.execute(
                "UPDATE upload_jobs SET locked_at=? WHERE id=?", (now.isoformat(), row["id"])
            )
        return UploadJob(
            id=row["id"],
            event_id=row["event_id"],
            attempts=row["attempts"],
            next_attempt_at=datetime.fromisoformat(row["next_attempt_at"]),
            last_error=row["last_error"],
        )

    def complete_upload(self, job_id: int) -> None:
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM upload_jobs WHERE id=?", (job_id,))

    def fail_upload(self, job_id: int, error: str, retry_at: datetime) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """UPDATE upload_jobs
                   SET attempts=attempts+1,next_attempt_at=?,last_error=?,locked_at=NULL
                   WHERE id=?""",
                (retry_at.isoformat(), error[:1000], job_id),
            )

    def upload_queue_depth(self) -> int:
        with self._lock:
            return int(self._connection.execute("SELECT COUNT(*) FROM upload_jobs").fetchone()[0])

    def create_pairing_challenge(self, code_hash: str, expires_at: datetime) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM pairing_challenges WHERE expires_at < ? OR claimed_at IS NOT NULL", (now,))
            self._connection.execute(
                "INSERT OR REPLACE INTO pairing_challenges(code_hash,expires_at,created_at,claimed_at) VALUES(?,?,?,NULL)",
                (code_hash, expires_at.isoformat(), now),
            )

    def consume_pairing_challenge(self, code_hash: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM pairing_challenges WHERE expires_at < ?", (now,))
            cursor = self._connection.execute(
                "UPDATE pairing_challenges SET claimed_at=? WHERE code_hash=? AND claimed_at IS NULL AND expires_at>=?",
                (now, code_hash, now),
            )
        return cursor.rowcount == 1

    def register_paired_device(self, device_id: str, name: str, token_hash: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO paired_devices(id,name,token_hash,created_at,last_seen_at) VALUES(?,?,?,?,?)",
                (device_id, name, token_hash, now, now),
            )

    def authenticate_paired_device(self, token_hash: str) -> str | None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT id FROM paired_devices WHERE token_hash=? AND revoked_at IS NULL", (token_hash,)
            ).fetchone()
            if row:
                self._connection.execute("UPDATE paired_devices SET last_seen_at=? WHERE id=?", (now, row["id"]))
        return str(row["id"]) if row else None

    def list_paired_devices(self) -> list[dict[str, str | None]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id,name,created_at,last_seen_at,revoked_at FROM paired_devices ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def revoke_paired_device(self, device_id: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE paired_devices SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                (datetime.now(timezone.utc).isoformat(), device_id),
            )
        return cursor.rowcount == 1

    def set_playback_receipt(self, command_id: str, status: str, detail: str = "") -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO playback_receipts(command_id,status,detail,updated_at)
                   VALUES(?,?,?,?) ON CONFLICT(command_id) DO UPDATE SET
                   status=excluded.status,detail=excluded.detail,updated_at=excluded.updated_at""",
                (command_id, status, detail[:1000], datetime.now(timezone.utc).isoformat()),
            )

    def get_playback_receipt(self, command_id: str) -> dict[str, str] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT command_id,status,detail,updated_at FROM playback_receipts WHERE command_id=?",
                (command_id,),
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _to_event(row: sqlite3.Row) -> EventRecord:
        return EventRecord(
            id=row["id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            camera_name=row["camera_name"],
            screenshot_path=Path(row["screenshot_path"]),
            person_confidence=row["person_confidence"],
            face_result=FaceResult(row["face_result"]),
            person_name=row["person_name"],
            notification_status=row["notification_status"],
            viewed=bool(row["viewed"]),
            bbox_x=row["bbox_x"],
            bbox_y=row["bbox_y"],
            bbox_width=row["bbox_width"],
            bbox_height=row["bbox_height"],
        )
