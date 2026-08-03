from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from pydantic import BaseModel, Field


class FaceResult(StrEnum):
    UNKNOWN = "unknown"
    WHITELISTED = "whitelisted"
    NO_FACE = "no_face"


class UploadStatus(StrEnum):
    LOCAL_ONLY = "local_only"
    QUEUED = "queued"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    NOTIFIED = "notified"
    FAILED = "failed"


class EventRecord(BaseModel):
    id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    camera_name: str
    screenshot_path: Path
    person_confidence: float = Field(ge=0, le=1)
    face_result: FaceResult = FaceResult.NO_FACE
    person_name: str | None = None
    notification_status: str = UploadStatus.LOCAL_ONLY.value
    viewed: bool = False
    bbox_x: int | None = None
    bbox_y: int | None = None
    bbox_width: int | None = None
    bbox_height: int | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    camera_active: bool
    privacy_paused: bool
    emergency_disabled: bool
    last_frame_at: datetime | None
    last_event_at: datetime | None
    fps: float
    inference_fps: float
    upload_queue_depth: int
    cloud_enabled: bool
    disk_free_mb: int
    webrtc_available: bool = False
    webrtc_active: bool = False
    webrtc_session_id: str | None = None
    webrtc_last_error: str = ""


class PlaybackRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=180)
    nonce: str = Field(min_length=16, max_length=128)
    issued_at: datetime
    expires_at: datetime
    volume: int = Field(default=100, ge=0, le=100)
    repeat_count: int = Field(default=1, ge=1, le=3)
    command_id: str | None = Field(default=None, max_length=100)
    restore_volume: bool = True


class PlaybackReceipt(BaseModel):
    accepted: bool
    status: str
    detail: str = ""
    command_id: str | None = None


class UploadJob(BaseModel):
    id: int
    event_id: str
    attempts: int
    next_attempt_at: datetime
    last_error: str | None = None


class StateResponse(BaseModel):
    privacy_paused: bool
    emergency_disabled: bool
    emergency_disabled_at: str | None = None
    emergency_reason: str | None = None


class PairClaimRequest(BaseModel):
    code: str = Field(min_length=32, max_length=256)
    device_name: str = Field(min_length=1, max_length=100)


class PairClaimResponse(BaseModel):
    device_id: str
    token: str
    api_url: str


class PairedDeviceResponse(BaseModel):
    id: str
    name: str
    created_at: str
    last_seen_at: str | None = None
    revoked_at: str | None = None


class PushRegistrationRequest(BaseModel):
    token: str = Field(min_length=32, max_length=4096)
    device_name: str = Field(default="Android phone", min_length=1, max_length=100)


class FaceEnrollmentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
