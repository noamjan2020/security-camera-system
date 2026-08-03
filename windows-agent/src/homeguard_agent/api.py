from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections.abc import Callable
import logging
import shutil
import time
import uuid

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from .app_state import AppStateStore
from .audio import AudioPlaybackService, validate_wave_file
from .camera_service import CameraService
from .database import EventDatabase
from .event_service import EventService
from .logging_config import reset_request_id, set_request_id
from .maintenance import MaintenanceService
from .pairing import PairingService
from .models import (
    FaceEnrollmentRequest, HealthResponse, PairClaimRequest, PairClaimResponse, PairedDeviceResponse,
    PlaybackReceipt, PlaybackRequest, PushRegistrationRequest, StateResponse,
)
from .security import TokenGuard, validate_command_window

logger = logging.getLogger(__name__)


def create_app(
    database: EventDatabase,
    events_service: EventService,
    camera: CameraService,
    audio: AudioPlaybackService,
    state_store: AppStateStore,
    maintenance: MaintenanceService,
    pairing: PairingService,
    token: str,
    audio_dir: Path,
    logs_dir: Path,
    *,
    cloud_enabled: bool,
    audio_max_bytes: int,
    audio_max_seconds: int,
    push_token_registrar: Callable[[str, str, str], None] | None = None,
    face_engine=None,
    face_whitelist=None,
    webrtc=None,
    version: str = "0.4.0",
) -> FastAPI:
    app = FastAPI(title="HomeGuard Agent API", version=version)
    guard = TokenGuard(token, database)
    owner_guard = TokenGuard(token, database, owner_only=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        token_ctx = set_request_id(request_id)
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Unhandled API request failure: %s %s", request.method, request.url.path)
            response = JSONResponse(status_code=500, content={"detail": "Internal server error", "request_id": request_id})
        duration_ms = int((time.monotonic() - started) * 1000)
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store"
        logger.info(
            "%s %s -> %s",
            request.method,
            request.url.path,
            response.status_code,
            extra={"request_id": request_id, "duration_ms": duration_ms},
        )
        reset_request_id(token_ctx)
        return response

    @app.post("/pair/claim", response_model=PairClaimResponse)
    def claim_pairing(request: PairClaimRequest, http_request: Request) -> PairClaimResponse:
        try:
            claimed = pairing.claim(request.code, request.device_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        base_url = str(http_request.base_url).rstrip("/")
        return PairClaimResponse(device_id=claimed.device_id, token=claimed.token, api_url=base_url)

    @app.get("/devices", response_model=list[PairedDeviceResponse], dependencies=[Depends(owner_guard)])
    def paired_devices():
        return database.list_paired_devices()

    @app.delete("/devices/{device_id}", dependencies=[Depends(owner_guard)])
    def revoke_device(device_id: str):
        if not database.revoke_paired_device(device_id):
            raise HTTPException(status_code=404, detail="Device not found or already revoked")
        logger.warning("Paired device revoked", extra={"device_id": device_id})
        return Response(status_code=204)

    @app.post("/push/register")
    def register_push_token(request: PushRegistrationRequest, principal: str = Depends(guard)):
        if principal == "owner":
            raise HTTPException(status_code=400, detail="A paired Android credential is required")
        if push_token_registrar is None:
            raise HTTPException(status_code=503, detail="Cloud notifications are not configured")
        try:
            push_token_registrar(principal, request.device_name, request.token)
        except Exception as exc:
            logger.exception("Push token registration failed", extra={"device_id": principal})
            raise HTTPException(status_code=502, detail="Cloud push registration failed") from exc
        return {"registered": True, "device_id": principal}

    @app.get("/whitelist", dependencies=[Depends(owner_guard)])
    def whitelist_people():
        if face_whitelist is None:
            return {"enabled": False, "people": {}}
        return {
            "enabled": bool(face_engine and face_engine.available),
            "reason": getattr(face_engine, "unavailable_reason", None),
            "people": face_whitelist.people(),
        }

    @app.post("/whitelist/enroll-current", dependencies=[Depends(owner_guard)])
    def enroll_current_face(request: FaceEnrollmentRequest):
        if face_engine is None or not face_engine.available or face_whitelist is None:
            raise HTTPException(status_code=503, detail="Face models are not installed")
        frame = camera.snapshot_frame()
        if frame is None:
            raise HTTPException(status_code=503, detail="Camera frame unavailable")
        embedding = face_engine.extract_embedding(frame)
        if embedding is None:
            raise HTTPException(status_code=422, detail="No clear face found in the current frame")
        count = face_whitelist.enroll(request.name, embedding)
        return {"name": request.name.strip(), "samples": count}

    @app.post("/whitelist/test-current", dependencies=[Depends(owner_guard)])
    def test_current_face():
        if face_engine is None or not face_engine.available:
            raise HTTPException(status_code=503, detail="Face models are not installed")
        frame = camera.snapshot_frame()
        if frame is None:
            raise HTTPException(status_code=503, detail="Camera frame unavailable")
        match = face_engine.recognize(frame)
        return {
            "matched": match.matched,
            "person_name": match.person_name,
            "similarity": match.similarity,
            "usable_face": match.usable_face,
        }

    @app.delete("/whitelist/{person_name}", dependencies=[Depends(owner_guard)])
    def remove_whitelisted_person(person_name: str):
        if face_whitelist is None or not face_whitelist.remove(person_name):
            raise HTTPException(status_code=404, detail="Whitelisted person not found")
        return Response(status_code=204)

    @app.get("/health", response_model=HealthResponse, dependencies=[Depends(guard)])
    def health() -> HealthResponse:
        latest = database.list_events(limit=1)
        state = state_store.snapshot()
        disk_free = maintenance.disk_free_mb
        if disk_free <= 0:
            disk_free = int(shutil.disk_usage(database.path.parent).free / 1024 / 1024)
        return HealthResponse(
            status="ok" if not state.emergency_disabled else "emergency_disabled",
            version=version,
            camera_active=camera.active,
            privacy_paused=state.privacy_paused,
            emergency_disabled=state.emergency_disabled,
            last_frame_at=camera.last_frame_at,
            last_event_at=latest[0].timestamp if latest else None,
            fps=camera.fps,
            inference_fps=camera.inference_fps,
            upload_queue_depth=database.upload_queue_depth(),
            cloud_enabled=cloud_enabled,
            disk_free_mb=disk_free,
            webrtc_available=bool(webrtc and webrtc.available),
            webrtc_active=bool(webrtc and webrtc.active),
            webrtc_session_id=webrtc.session_id if webrtc else None,
            webrtc_last_error=webrtc.last_error if webrtc else "",
        )

    @app.get("/state", response_model=StateResponse, dependencies=[Depends(guard)])
    def state() -> StateResponse:
        return StateResponse(**asdict(state_store.snapshot()))

    @app.get("/events", dependencies=[Depends(guard)])
    def events(
        minutes: int = Query(default=15, ge=1, le=525600),
        limit: int = Query(default=100, ge=1, le=500),
    ):
        since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        return database.list_events(limit=limit, since=since)

    @app.get("/events/{event_id}", dependencies=[Depends(guard)])
    def event_detail(event_id: str):
        event = database.get_event(event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        return event

    @app.post("/events/{event_id}/viewed", dependencies=[Depends(guard)])
    def mark_event_viewed(event_id: str):
        if not database.mark_viewed(event_id):
            raise HTTPException(status_code=404, detail="Event not found")
        return {"viewed": True}

    @app.delete("/events/{event_id}", dependencies=[Depends(guard)])
    def delete_event(event_id: str):
        if not events_service.delete_event(event_id):
            raise HTTPException(status_code=404, detail="Event not found")
        return Response(status_code=204)

    @app.get("/events/{event_id}/image", dependencies=[Depends(guard)])
    def event_image(event_id: str):
        event = database.get_event(event_id)
        if not event or not event.screenshot_path.exists():
            raise HTTPException(status_code=404, detail="Event media not found")
        database.mark_viewed(event_id)
        return FileResponse(
            event.screenshot_path,
            media_type="image/jpeg",
            filename=event.screenshot_path.name,
            headers={"Cache-Control": "private, max-age=60"},
        )

    @app.get("/snapshot", dependencies=[Depends(guard)])
    def snapshot():
        image = camera.snapshot_jpeg()
        if image is None:
            raise HTTPException(status_code=503, detail="Camera frame unavailable or privacy disabled")
        return Response(content=image, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.post("/audio/upload", dependencies=[Depends(guard)])
    async def upload_audio(file: UploadFile = File(...)):
        if file.content_type not in {"audio/wav", "audio/x-wav", "application/octet-stream"}:
            raise HTTPException(status_code=415, detail="WAV audio required")
        audio_id = uuid.uuid4().hex
        target = audio_dir / f"{audio_id}.wav"
        temp = audio_dir / f".{audio_id}.upload"
        total = 0
        try:
            with temp.open("wb") as handle:
                while chunk := await file.read(64 * 1024):
                    total += len(chunk)
                    if total > audio_max_bytes:
                        raise HTTPException(status_code=413, detail="Audio exceeds configured size limit")
                    handle.write(chunk)
            temp.replace(target)
            metadata = validate_wave_file(
                target, max_seconds=audio_max_seconds, max_bytes=audio_max_bytes
            )
        except Exception:
            temp.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            raise
        finally:
            await file.close()
        logger.info("Audio uploaded and validated", extra={"event_id": audio_id})
        return {
            "file_name": target.name,
            "size": total,
            "duration_seconds": metadata.duration_seconds,
            "sample_rate": metadata.sample_rate,
        }

    @app.post("/audio/play", response_model=PlaybackReceipt, dependencies=[Depends(guard)])
    def play_audio(request: PlaybackRequest) -> PlaybackReceipt:
        state = state_store.snapshot()
        if state.emergency_disabled:
            raise HTTPException(status_code=423, detail="Emergency disable is active")
        try:
            validate_command_window(request.issued_at, request.expires_at)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not database.consume_nonce(request.nonce, request.expires_at):
            raise HTTPException(status_code=409, detail="Replay detected")
        target = audio_dir / Path(request.file_name).name
        if target.parent != audio_dir or not target.exists():
            raise HTTPException(status_code=404, detail="Audio file not found")
        validate_wave_file(target, max_seconds=audio_max_seconds, max_bytes=audio_max_bytes)
        command_id = request.command_id or uuid.uuid4().hex
        database.set_playback_receipt(command_id, "received")
        audio.play_async(
            target,
            repeat_count=request.repeat_count,
            volume=request.volume,
            restore_volume=request.restore_volume,
            command_id=command_id,
            delete_after=True,
        )
        return PlaybackReceipt(accepted=True, status="received", command_id=command_id)

    @app.get("/audio/receipt/{command_id}", dependencies=[Depends(guard)])
    def audio_receipt(command_id: str):
        receipt = database.get_playback_receipt(command_id)
        if not receipt:
            raise HTTPException(status_code=404, detail="Receipt not found")
        return receipt

    @app.post("/audio/stop", response_model=PlaybackReceipt, dependencies=[Depends(guard)])
    def stop_audio() -> PlaybackReceipt:
        command_id = audio.current_command_id
        audio.stop()
        return PlaybackReceipt(accepted=True, status="stopped", command_id=command_id)

    @app.post("/privacy/pause", dependencies=[Depends(guard)])
    def pause_camera():
        camera.pause()
        return StateResponse(**asdict(state_store.snapshot()))

    @app.post("/privacy/resume", dependencies=[Depends(guard)])
    def resume_camera():
        try:
            camera.resume()
        except PermissionError as exc:
            raise HTTPException(status_code=423, detail=str(exc)) from exc
        return StateResponse(**asdict(state_store.snapshot()))

    @app.post("/emergency/disable", dependencies=[Depends(guard)])
    def reject_remote_emergency_change():
        raise HTTPException(status_code=403, detail="Emergency controls are local-only")

    @app.get("/logs/tail", dependencies=[Depends(guard)])
    def logs_tail(lines: int = Query(default=200, ge=10, le=2000)):
        path = logs_dir / "homeguard.log"
        if not path.exists():
            return {"lines": []}
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            data = handle.readlines()[-lines:]
        return {"lines": [line.rstrip("\n") for line in data]}

    return app
