from __future__ import annotations

import logging
import sys
from pathlib import Path

from .api import create_app
from .app_state import AppStateStore
from .audio import AudioPlaybackService
from .camera_service import CameraService
from .cloud import SupabaseCloudClient, UploadWorker
from .config import Settings
from .database import EventDatabase
from .detector import PersonDetector
from .event_service import EventService
from .face_whitelist import FaceWhitelist, OpenCvFaceEngine
from .maintenance import MaintenanceService
from .pairing import PairingService
from .remote_commands import RemoteCommandWorker
from .security import generate_token, load_token, save_token
from .webrtc import WebRtcPublisherManager

logger = logging.getLogger(__name__)


class Runtime:
    VERSION = "0.4.0"

    def __init__(self, settings: Settings):
        self.settings = settings
        settings.ensure_directories()
        legacy_token_path = settings.data_dir / "api-token.txt"
        if settings.api_token:
            self.token = settings.api_token
        elif settings.token_path.exists():
            self.token = load_token(settings.token_path)
        elif legacy_token_path.exists():
            self.token = load_token(legacy_token_path)
            save_token(settings.token_path, self.token)
            legacy_token_path.unlink(missing_ok=True)
            logger.info("Migrated legacy API token into protected storage")
        else:
            self.token = generate_token()
            save_token(settings.token_path, self.token)

        self.database = EventDatabase(settings.database_path)
        if not self.database.integrity_check():
            raise RuntimeError("HomeGuard database failed integrity check")
        self.state_store = AppStateStore(settings.state_path)
        self.pairing = PairingService(
            self.database,
            settings.api_port,
            settings.pairing_code_ttl_seconds,
            settings.pairing_base_url,
        )
        self.detector = PersonDetector(
            settings.detection_confidence,
            backend=settings.detector_backend,
            model_path=self._resolve_model_path(settings.detector_model_path),
            nms_threshold=settings.nms_threshold,
            inference_size=settings.inference_size,
        )
        self.face_whitelist = FaceWhitelist(settings.face_whitelist_path, settings.face_match_threshold)
        self.face_engine = OpenCvFaceEngine(
            self._resolve_model_path(settings.face_detector_model_path),
            self._resolve_model_path(settings.face_recognizer_model_path),
            self.face_whitelist,
            detection_threshold=settings.face_detection_confidence,
        ) if settings.face_whitelist_enabled else None
        self.events = EventService(
            self.database,
            settings.media_dir,
            settings.camera_name,
            queue_remote_uploads=settings.remote_enabled,
            jpeg_quality=settings.jpeg_quality,
        )
        self.cloud: SupabaseCloudClient | None = None
        self.upload_worker: UploadWorker | None = None
        self.remote_command_worker: RemoteCommandWorker | None = None
        if settings.remote_enabled:
            self.cloud = SupabaseCloudClient(settings)
            self.upload_worker = UploadWorker(self.database, self.cloud, settings, close_cloud_on_stop=False)

        self.audio = AudioPlaybackService(status_callback=self._on_audio_status)
        self.webrtc: WebRtcPublisherManager | None = None
        self.camera = CameraService(
            settings.camera_index,
            self.detector,
            self.events,
            self.state_store,
            settings.visible_seconds,
            settings.cooldown_seconds,
            settings.max_fps,
            settings.inference_fps,
            width=settings.camera_width,
            height=settings.camera_height,
            jpeg_quality=settings.jpeg_quality,
            face_engine=self.face_engine,
            record_whitelisted_events=settings.record_whitelisted_events,
            detection_zone=settings.detection_zone,
            exclusion_zones=settings.exclusion_zones,
            on_event=self._on_event,
        )
        if self.cloud and settings.webrtc_enabled:
            self.webrtc = WebRtcPublisherManager(
                frame_provider=self.camera.snapshot_frame,
                enabled_provider=lambda: not (
                    self.state_store.snapshot().privacy_paused
                    or self.state_store.snapshot().emergency_disabled
                ),
                access_token=settings.supabase_access_token,
                device_id=settings.device_id,
                max_width=settings.webrtc_max_width,
                max_height=settings.webrtc_max_height,
                max_session_seconds=settings.webrtc_max_session_seconds,
            )
        if self.cloud:
            self.remote_command_worker = RemoteCommandWorker(
                self.database,
                self.cloud,
                self.audio,
                self.state_store,
                settings,
                stream_manager=self.webrtc,
            )
        self.maintenance = MaintenanceService(self.database, self.events, settings)
        self.app = create_app(
            self.database,
            self.events,
            self.camera,
            self.audio,
            self.state_store,
            self.maintenance,
            self.pairing,
            self.token,
            settings.audio_dir,
            settings.logs_dir,
            cloud_enabled=settings.remote_enabled,
            audio_max_bytes=settings.audio_max_bytes,
            audio_max_seconds=settings.audio_max_seconds,
            push_token_registrar=self.cloud.register_push_token if self.cloud else None,
            face_engine=self.face_engine,
            face_whitelist=self.face_whitelist,
            webrtc=self.webrtc,
            version=self.VERSION,
        )
        self._started = False
        self._closed = False


    def _resolve_model_path(self, configured: Path) -> Path:
        if configured.is_absolute() and configured.exists():
            return configured
        candidates = [
            configured,
            self.settings.data_dir / "models" / configured.name,
            Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "models" / configured.name,
            Path(sys.executable).parent / "models" / configured.name,
        ]
        return next((path for path in candidates if path.exists()), candidates[1])

    def reload_face_engine(self) -> None:
        self.face_engine = OpenCvFaceEngine(
            self._resolve_model_path(self.settings.face_detector_model_path),
            self._resolve_model_path(self.settings.face_recognizer_model_path),
            self.face_whitelist,
            detection_threshold=self.settings.face_detection_confidence,
        ) if self.settings.face_whitelist_enabled else None
        self.camera.face_engine = self.face_engine
        logger.info("Face recognition engine reloaded", extra={"available": bool(self.face_engine and self.face_engine.available)})


    def _on_audio_status(self, command_id: str, status: str, detail: str) -> None:
        self.database.set_playback_receipt(command_id, status, detail)
        if self.remote_command_worker:
            self.remote_command_worker.notify_audio_status(command_id, status, detail)

    def _on_event(self, event_id: str) -> None:
        logger.info("Runtime received event callback", extra={"event_id": event_id})
        if self.upload_worker:
            self.upload_worker.notify()

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self.maintenance.start()
        self.camera.start()
        if self.upload_worker:
            self.upload_worker.start()
        if self.remote_command_worker:
            self.remote_command_worker.start()
        logger.info("HomeGuard runtime started")

    def stop(self) -> None:
        if self._closed:
            return
        if not self._started:
            # Runtime can still own open resources during setup or CLI commands.
            if self.webrtc:
                self.webrtc.stop()
            self.audio.stop()
            if self.cloud:
                self.cloud.close()
            self.database.close()
            self._closed = True
            return
        if self.remote_command_worker:
            self.remote_command_worker.stop()
        if self.webrtc:
            self.webrtc.stop()
        self.audio.stop()
        self.camera.shutdown()
        if self.upload_worker:
            self.upload_worker.stop()
        if self.cloud:
            self.cloud.close()
        self.maintenance.stop()
        self.database.close()
        self._started = False
        self._closed = True
        logger.info("HomeGuard runtime stopped")
