from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
import logging
import time
import uuid
from typing import TYPE_CHECKING

from .app_state import AppStateStore
from .audio import AudioPlaybackService, validate_wave_file
from .cloud import SupabaseCloudClient
from .database import EventDatabase
from .config import Settings

if TYPE_CHECKING:
    from .webrtc import WebRtcPublisherManager

logger = logging.getLogger(__name__)


class RemoteCommandWorker:
    """Polls authenticated Supabase commands without exposing inbound PC ports."""

    def __init__(
        self,
        database: EventDatabase,
        cloud: SupabaseCloudClient,
        audio: AudioPlaybackService,
        state_store: AppStateStore,
        settings: Settings,
        stream_manager: "WebRtcPublisherManager | None" = None,
    ):
        self.database = database
        self.cloud = cloud
        self.audio = audio
        self.state_store = state_store
        self.settings = settings
        self.stream_manager = stream_manager
        self._stop = Event()
        self._wake = Event()
        self._thread: Thread | None = None
        self._statuses: Queue[tuple[str, str, str]] = Queue(maxsize=100)
        self._voice_by_command: dict[str, str] = {}
        self._next_heartbeat_at = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="remote-command-worker", daemon=True)
        self._thread.start()
        logger.info("Remote command worker started")

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=8)
        logger.info("Remote command worker stopped")

    def notify_audio_status(self, command_id: str, status: str, detail: str = "") -> None:
        if command_id not in self._voice_by_command:
            return
        try:
            self._statuses.put_nowait((command_id, status, detail))
            self._wake.set()
        except Exception:
            logger.exception("Remote audio status queue is full", extra={"command_id": command_id})

    def _run(self) -> None:
        while not self._stop.is_set():
            self._flush_statuses()
            self._send_heartbeat_if_due()
            try:
                command = self.cloud.fetch_pending_command()
                if command:
                    self._handle(command)
            except Exception:
                logger.exception("Remote command poll failed")
            self._wake.wait(2)
            self._wake.clear()
        self._flush_statuses()

    def _send_heartbeat_if_due(self) -> None:
        now = time.monotonic()
        if now < self._next_heartbeat_at:
            return
        # Advance the deadline even on failure so a backend outage cannot create a hot retry loop.
        self._next_heartbeat_at = now + 30.0
        try:
            self.cloud.register_windows_device()
        except Exception:
            logger.exception("Windows cloud heartbeat failed")

    def _handle(self, command: dict) -> None:
        command_id = str(command.get("id", ""))
        command_type = str(command.get("command_type", ""))
        nonce = str(command.get("nonce", ""))
        expires_at = self._parse_time(str(command.get("expires_at", "")))
        logger.info(
            "Remote command claimed",
            extra={"command_id": command_id, "command_type": command_type},
        )
        if not command_id:
            raise ValueError("Cloud command is missing an ID")
        self.cloud.update_remote_command(command_id, "received", "Claimed by Windows agent")
        if not nonce or expires_at <= datetime.now(timezone.utc):
            self.cloud.update_remote_command(command_id, "expired", "Command expired before execution")
            return
        if not self.database.consume_nonce(nonce, expires_at):
            self.cloud.update_remote_command(command_id, "failed", "Replay nonce rejected")
            return
        if self.state_store.snapshot().emergency_disabled:
            self.cloud.update_remote_command(command_id, "failed", "Emergency disable is active")
            return
        if command_type == "stop_audio":
            self.audio.stop()
            self.cloud.update_remote_command(command_id, "completed", "Audio stopped")
            return
        if command_type == "stop_stream":
            session_id = str((command.get("payload") or {}).get("session_id", ""))
            stopped = bool(self.stream_manager and self.stream_manager.stop(session_id or None))
            self.cloud.update_remote_command(
                command_id,
                "completed",
                "Live stream stopped" if stopped else "No matching live stream was active",
            )
            return
        if command_type == "start_stream":
            if not self.stream_manager:
                self.cloud.update_remote_command(command_id, "failed", "WebRTC Live View is unavailable")
                return
            try:
                request = self.stream_manager.start(command.get("payload") or {})
                self.cloud.update_remote_command(
                    command_id,
                    "completed",
                    f"WebRTC publisher started for session {request.session_id}",
                )
            except Exception as exc:
                logger.exception("Remote WebRTC start failed", extra={"command_id": command_id})
                self.cloud.update_remote_command(command_id, "failed", str(exc))
            return
        if command_type != "play_audio":
            self.cloud.update_remote_command(command_id, "failed", "Unsupported command type")
            return
        self._play_audio(command_id, command.get("payload") or {})

    def _play_audio(self, command_id: str, payload: dict) -> None:
        voice_message_id = str(payload.get("voice_message_id", ""))
        if not voice_message_id:
            self.cloud.update_remote_command(command_id, "failed", "voice_message_id is required")
            return
        try:
            voice = self.cloud.fetch_voice_message(voice_message_id)
            expires_at = self._parse_time(str(voice.get("expires_at", "")))
            if expires_at <= datetime.now(timezone.utc):
                self.cloud.update_voice_message(voice_message_id, "expired")
                self.cloud.update_remote_command(command_id, "expired", "Voice message expired")
                return
            payload_bytes = self.cloud.download_voice_message(str(voice["storage_path"]))
            path = self.settings.audio_dir / f"remote-{uuid.uuid4().hex}.wav"
            path.write_bytes(payload_bytes)
            metadata = validate_wave_file(
                path,
                max_seconds=self.settings.audio_max_seconds,
                max_bytes=self.settings.audio_max_bytes,
            )
            expected_size = int(voice.get("size_bytes") or 0)
            if expected_size and expected_size != len(payload_bytes):
                path.unlink(missing_ok=True)
                raise ValueError("Downloaded voice-message size does not match metadata")
            volume = max(0, min(100, int(payload.get("volume", 100))))
            repeat_count = max(1, min(3, int(payload.get("repeat_count", 1))))
            restore = bool(payload.get("restore_volume", True))
            self._voice_by_command[command_id] = voice_message_id
            self.cloud.update_voice_message(voice_message_id, "received")
            self.cloud.update_remote_command(
                command_id,
                "executing",
                f"Validated {metadata.duration_seconds:.2f}s WAV",
            )
            self.audio.play_async(
                path,
                repeat_count=repeat_count,
                volume=volume,
                restore_volume=restore,
                command_id=command_id,
                delete_after=True,
            )
        except Exception as exc:
            logger.exception("Remote voice playback preparation failed", extra={"command_id": command_id})
            self.cloud.update_remote_command(command_id, "failed", str(exc))
            run_voice_id = self._voice_by_command.pop(command_id, voice_message_id)
            if run_voice_id:
                try:
                    self.cloud.update_voice_message(run_voice_id, "failed")
                except Exception:
                    logger.exception("Voice failure status update failed", extra={"voice_message_id": run_voice_id})

    def _flush_statuses(self) -> None:
        while True:
            try:
                command_id, status, detail = self._statuses.get_nowait()
            except Empty:
                return
            voice_id = self._voice_by_command.get(command_id)
            if not voice_id:
                continue
            command_status = "executing" if status == "playing" else status
            voice_status = status if status in {"playing", "completed", "stopped", "failed"} else "received"
            try:
                self.cloud.update_voice_message(voice_id, voice_status)
                self.cloud.update_remote_command(command_id, command_status, detail)
                if status in {"completed", "stopped", "failed"}:
                    self._voice_by_command.pop(command_id, None)
            except Exception:
                logger.exception(
                    "Remote playback status delivery failed",
                    extra={"command_id": command_id, "status": status},
                )

    @staticmethod
    def _parse_time(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
