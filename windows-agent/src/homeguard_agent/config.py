from __future__ import annotations

from pathlib import Path
import os
import platform
import uuid
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_data_dir() -> Path:
    if platform.system() == "Windows":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "HomeGuard"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "homeguard"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="HOMEGUARD_",
        extra="ignore",
        validate_default=True,
    )

    data_dir: Path = Field(default_factory=default_data_dir)
    camera_index: int = Field(default=0, ge=0, le=32)
    camera_name: str = Field(default="Main Camera", min_length=1, max_length=100)
    camera_width: int = Field(default=1280, ge=320, le=3840)
    camera_height: int = Field(default=720, ge=240, le=2160)
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8765, ge=1024, le=65535)
    pairing_base_url: str = ""
    pairing_code_ttl_seconds: int = Field(default=120, ge=30, le=600)

    detector_backend: str = "auto"
    detector_model_path: Path = Path("./models/yolo11n.onnx")
    detection_confidence: float = Field(default=0.55, ge=0.1, le=0.99)
    nms_threshold: float = Field(default=0.45, ge=0.1, le=0.9)
    inference_size: int = Field(default=640, ge=320, le=1280)
    inference_fps: float = Field(default=4.0, ge=0.5, le=30)
    visible_seconds: float = Field(default=1.5, ge=0.1, le=30)
    cooldown_seconds: int = Field(default=60, ge=0, le=86400)
    detection_zone: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    exclusion_zones: list[tuple[float, float, float, float]] = Field(default_factory=list)
    max_fps: int = Field(default=12, ge=1, le=60)
    jpeg_quality: int = Field(default=86, ge=40, le=100)

    face_whitelist_enabled: bool = True
    face_detector_model_path: Path = Path("./models/face_detection_yunet_2023mar.onnx")
    face_recognizer_model_path: Path = Path("./models/face_recognition_sface_2021dec.onnx")
    face_detection_confidence: float = Field(default=0.90, ge=0.5, le=0.99)
    face_match_threshold: float = Field(default=0.50, ge=0.2, le=0.95)
    record_whitelisted_events: bool = True

    retention_minutes: int = Field(default=60, ge=15, le=525600)
    cleanup_interval_seconds: int = Field(default=300, ge=30, le=86400)
    disk_warning_mb: int = Field(default=512, ge=64, le=102400)

    api_token: str = ""
    remote_enabled: bool = False
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_access_token: str = ""
    owner_id: str = ""
    device_id: str = ""
    camera_id: str = ""
    notify_function_url: str = ""
    cloud_timeout_seconds: float = Field(default=15.0, ge=2, le=120)
    upload_retry_base_seconds: int = Field(default=5, ge=1, le=3600)
    upload_retry_max_seconds: int = Field(default=300, ge=10, le=86400)

    # Optional WebRTC is lazy-loaded only for an active remote Live View session.
    webrtc_enabled: bool = True
    webrtc_max_fps: int = Field(default=15, ge=2, le=30)
    webrtc_max_width: int = Field(default=1280, ge=320, le=1920)
    webrtc_max_height: int = Field(default=720, ge=240, le=1080)
    webrtc_max_session_seconds: int = Field(default=330, ge=30, le=900)

    audio_max_bytes: int = Field(default=5_000_000, ge=100_000, le=25_000_000)
    audio_max_seconds: int = Field(default=30, ge=1, le=120)
    debug: bool = False

    @field_validator("detection_zone")
    @classmethod
    def validate_detection_zone(cls, value: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        return cls._validate_zone(value, "detection_zone")

    @field_validator("exclusion_zones")
    @classmethod
    def validate_exclusion_zones(
        cls, value: list[tuple[float, float, float, float]]
    ) -> list[tuple[float, float, float, float]]:
        if len(value) > 16:
            raise ValueError("At most 16 exclusion zones are supported")
        return [cls._validate_zone(zone, "exclusion_zones") for zone in value]

    @staticmethod
    def _validate_zone(
        value: tuple[float, float, float, float], field_name: str
    ) -> tuple[float, float, float, float]:
        x, y, width, height = (float(item) for item in value)
        if not all(0.0 <= item <= 1.0 for item in (x, y, width, height)):
            raise ValueError(f"{field_name} values must be normalized between 0 and 1")
        if width <= 0 or height <= 0 or x + width > 1.000001 or y + height > 1.000001:
            raise ValueError(f"{field_name} must fit inside the frame and have positive size")
        return (x, y, width, height)

    @field_validator("detector_backend")
    @classmethod
    def validate_detector_backend(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"auto", "onnx", "hog"}:
            raise ValueError("detector_backend must be auto, onnx, or hog")
        return normalized

    @model_validator(mode="after")
    def validate_remote_configuration(self) -> "Settings":
        if self.remote_enabled:
            required = {
                "supabase_url": self.supabase_url,
                "supabase_anon_key": self.supabase_anon_key,
                "supabase_access_token": self.supabase_access_token,
                "owner_id": self.owner_id,
                "device_id": self.device_id,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(f"Remote mode missing: {', '.join(missing)}")
            for name in ("owner_id", "device_id"):
                try:
                    uuid.UUID(str(getattr(self, name)))
                except (ValueError, AttributeError) as exc:
                    raise ValueError(f"{name} must be a UUID in remote mode") from exc
            if self.camera_id:
                try:
                    uuid.UUID(str(self.camera_id))
                except (ValueError, AttributeError) as exc:
                    raise ValueError("camera_id must be a UUID when configured") from exc
        return self

    @property
    def database_path(self) -> Path:
        return self.data_dir / "events.db"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def state_path(self) -> Path:
        return self.data_dir / "state.json"

    @property
    def token_path(self) -> Path:
        return self.data_dir / "api-token.bin"

    @property
    def face_whitelist_path(self) -> Path:
        return self.data_dir / "face-whitelist.bin"

    def ensure_directories(self) -> None:
        for path in (self.data_dir, self.media_dir, self.audio_dir, self.logs_dir):
            path.mkdir(parents=True, exist_ok=True)
