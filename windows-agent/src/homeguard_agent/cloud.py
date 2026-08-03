from __future__ import annotations

import logging
import random
import time
import uuid
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from urllib.parse import quote

import httpx

from .config import Settings
from .database import EventDatabase
from .models import EventRecord, UploadStatus

logger = logging.getLogger(__name__)


class SupabaseCloudClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base = settings.supabase_url.rstrip("/")
        self.headers = {
            "apikey": settings.supabase_anon_key,
            "Authorization": f"Bearer {settings.supabase_access_token}",
        }
        self.client = httpx.Client(
            timeout=settings.cloud_timeout_seconds,
            event_hooks={"request": [self._log_request], "response": [self._log_response]},
        )


    @staticmethod
    def _log_request(request: httpx.Request) -> None:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request.headers["X-Request-ID"] = request_id
        request.extensions["homeguard_started"] = time.monotonic()
        logger.debug(
            "Cloud request started",
            extra={"request_id": request_id, "method": request.method, "path": request.url.path},
        )

    @staticmethod
    def _log_response(response: httpx.Response) -> None:
        started = response.request.extensions.get("homeguard_started")
        duration_ms = int((time.monotonic() - started) * 1000) if isinstance(started, float) else None
        logger.info(
            "Cloud request completed",
            extra={
                "request_id": response.request.headers.get("X-Request-ID"),
                "method": response.request.method,
                "path": response.request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )

    def close(self) -> None:
        self.client.close()

    def register_windows_device(self) -> None:
        """Upsert the agent identity and heartbeat using only owner-scoped credentials."""
        payload = {
            "id": self.settings.device_id,
            "owner_id": self.settings.owner_id,
            "name": f"HomeGuard - {self.settings.camera_name}"[:100],
            "device_type": "windows_agent",
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }
        response = self.client.post(
            f"{self.base}/rest/v1/devices?on_conflict=id",
            headers={
                **self.headers,
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
            json=payload,
        )
        if response.status_code not in {200, 201, 204}:
            raise RuntimeError(f"Windows device heartbeat failed ({response.status_code}): {response.text[:300]}")
        logger.debug("Windows cloud heartbeat sent", extra={"device_id": self.settings.device_id})

    def register_push_token(self, device_id: str, device_name: str, push_token: str) -> None:
        device_payload = {
            "id": device_id,
            "owner_id": self.settings.owner_id,
            "name": device_name[:100],
            "device_type": "android",
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }
        response = self.client.post(
            f"{self.base}/rest/v1/devices",
            headers={
                **self.headers,
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
            json=device_payload,
        )
        if response.status_code not in {200, 201, 204}:
            raise RuntimeError(f"Device registration failed ({response.status_code}): {response.text[:300]}")
        response = self.client.post(
            f"{self.base}/rest/v1/push_tokens?on_conflict=token",
            headers={
                **self.headers,
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
            json={
                "owner_id": self.settings.owner_id,
                "device_id": device_id,
                "token": push_token,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        if response.status_code not in {200, 201, 204}:
            raise RuntimeError(f"Push token registration failed ({response.status_code}): {response.text[:300]}")
        logger.info("Push token registered", extra={"device_id": device_id})

    def upload_event(self, event: EventRecord) -> UploadStatus:
        if not event.screenshot_path.exists():
            raise FileNotFoundError(event.screenshot_path)
        media_path = f"{self.settings.owner_id}/{self.settings.device_id}/{event.id}.jpg"
        upload_url = f"{self.base}/storage/v1/object/event-media/{quote(media_path, safe='/')}"
        payload = event.screenshot_path.read_bytes()
        response = self.client.post(
            upload_url,
            headers={**self.headers, "Content-Type": "image/jpeg", "x-upsert": "false"},
            content=payload,
        )
        # Duplicate media after a crash is safe: the event insert below is idempotent.
        if response.status_code not in {200, 201, 409}:
            raise RuntimeError(f"Media upload failed ({response.status_code}): {response.text[:300]}")

        expires_at = event.timestamp + timedelta(minutes=self.settings.retention_minutes)
        event_payload = {
            "id": event.id,
            "owner_id": self.settings.owner_id,
            "device_id": self.settings.device_id,
            "camera_id": self.settings.camera_id or None,
            "occurred_at": event.timestamp.isoformat(),
            "expires_at": expires_at.isoformat(),
            "person_confidence": event.person_confidence,
            "face_result": event.face_result.value,
            "person_name": event.person_name,
            "media_path": media_path,
        }
        response = self.client.post(
            f"{self.base}/rest/v1/events",
            headers={
                **self.headers,
                "Content-Type": "application/json",
                "Prefer": "resolution=ignore-duplicates,return=minimal",
            },
            json=event_payload,
        )
        if response.status_code not in {200, 201, 204, 409}:
            raise RuntimeError(f"Event insert failed ({response.status_code}): {response.text[:300]}")

        if not self.settings.notify_function_url:
            return UploadStatus.UPLOADED
        response = self.client.post(
            self.settings.notify_function_url,
            headers={**self.headers, "Content-Type": "application/json"},
            json={"event_id": event.id},
        )
        if response.status_code not in {200, 201, 202, 204}:
            raise RuntimeError(f"Notification dispatch failed ({response.status_code}): {response.text[:300]}")
        return UploadStatus.NOTIFIED

    def fetch_pending_command(self) -> dict | None:
        """Atomically claim the oldest pending command addressed to this Windows device."""
        select = "id,command_type,payload,nonce,expires_at,status"
        url = (
            f"{self.base}/rest/v1/remote_commands"
            f"?select={quote(select, safe=',')}"
            f"&target_device_id=eq.{quote(self.settings.device_id)}"
            "&status=eq.pending&order=created_at.asc&limit=1"
        )
        response = self.client.get(url, headers=self.headers)
        if response.status_code != 200:
            raise RuntimeError(f"Command poll failed ({response.status_code}): {response.text[:300]}")
        rows = response.json()
        if not rows:
            return None
        command = rows[0]
        claim = self.client.patch(
            f"{self.base}/rest/v1/remote_commands?id=eq.{quote(command['id'])}&status=eq.pending",
            headers={
                **self.headers,
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            json={"status": "received", "updated_at": datetime.now(timezone.utc).isoformat()},
        )
        if claim.status_code not in {200, 204}:
            raise RuntimeError(f"Command claim failed ({claim.status_code}): {claim.text[:300]}")
        claimed_rows = claim.json() if claim.content else []
        return claimed_rows[0] if claimed_rows else None

    def fetch_voice_message(self, voice_message_id: str) -> dict:
        url = (
            f"{self.base}/rest/v1/voice_messages"
            f"?select=id,storage_path,duration_ms,size_bytes,status,expires_at,target_device_id"
            f"&id=eq.{quote(voice_message_id)}&target_device_id=eq.{quote(self.settings.device_id)}&limit=1"
        )
        response = self.client.get(url, headers=self.headers)
        if response.status_code != 200:
            raise RuntimeError(f"Voice lookup failed ({response.status_code}): {response.text[:300]}")
        rows = response.json()
        if not rows:
            raise RuntimeError("Voice message was not found or is not authorized for this PC")
        return rows[0]

    def download_voice_message(self, storage_path: str) -> bytes:
        url = f"{self.base}/storage/v1/object/authenticated/voice-media/{quote(storage_path, safe='/')}"
        response = self.client.get(url, headers=self.headers)
        if response.status_code != 200:
            raise RuntimeError(f"Voice download failed ({response.status_code}): {response.text[:300]}")
        if len(response.content) > self.settings.audio_max_bytes:
            raise RuntimeError("Voice message exceeds the configured maximum size")
        return response.content

    def update_remote_command(self, command_id: str, status: str, detail: str = "") -> None:
        response = self.client.patch(
            f"{self.base}/rest/v1/remote_commands?id=eq.{quote(command_id)}&target_device_id=eq.{quote(self.settings.device_id)}",
            headers={**self.headers, "Content-Type": "application/json", "Prefer": "return=minimal"},
            json={"status": status, "updated_at": datetime.now(timezone.utc).isoformat()},
        )
        if response.status_code not in {200, 204}:
            raise RuntimeError(f"Command update failed ({response.status_code}): {response.text[:300]}")
        receipt_status = "executing" if status == "executing" else status
        if receipt_status in {"received", "executing", "completed", "stopped", "failed", "expired"}:
            receipt = self.client.post(
                f"{self.base}/rest/v1/command_receipts?on_conflict=command_id,status",
                headers={
                    **self.headers,
                    "Content-Type": "application/json",
                    "Prefer": "resolution=ignore-duplicates,return=minimal",
                },
                json={
                    "owner_id": self.settings.owner_id,
                    "command_id": command_id,
                    "device_id": self.settings.device_id,
                    "status": receipt_status,
                    "detail": detail[:1000],
                },
            )
            if receipt.status_code not in {200, 201, 204, 409}:
                logger.warning(
                    "Command receipt insert failed",
                    extra={"command_id": command_id, "status_code": receipt.status_code},
                )

    def update_voice_message(self, voice_message_id: str, status: str) -> None:
        response = self.client.patch(
            f"{self.base}/rest/v1/voice_messages?id=eq.{quote(voice_message_id)}&target_device_id=eq.{quote(self.settings.device_id)}",
            headers={**self.headers, "Content-Type": "application/json", "Prefer": "return=minimal"},
            json={"status": status, "updated_at": datetime.now(timezone.utc).isoformat()},
        )
        if response.status_code not in {200, 204}:
            raise RuntimeError(f"Voice status update failed ({response.status_code}): {response.text[:300]}")


class UploadWorker:
    def __init__(
        self,
        database: EventDatabase,
        cloud: SupabaseCloudClient,
        settings: Settings,
        *,
        close_cloud_on_stop: bool = True,
    ):
        self.database = database
        self.cloud = cloud
        self.settings = settings
        self._stop = Event()
        self._wake = Event()
        self._thread: Thread | None = None
        self.close_cloud_on_stop = close_cloud_on_stop

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="cloud-upload-worker", daemon=True)
        self._thread.start()
        logger.info("Cloud upload worker started")

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=10)
        if self.close_cloud_on_stop:
            self.cloud.close()
        logger.info("Cloud upload worker stopped")

    def notify(self) -> None:
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            job = self.database.claim_due_upload()
            if job is None:
                self._wake.wait(2)
                self._wake.clear()
                continue
            event = self.database.get_event(job.event_id)
            if event is None:
                logger.error("Dropping upload job for missing event", extra={"job_id": job.id})
                self.database.complete_upload(job.id)
                continue
            try:
                self.database.update_event_status(event.id, UploadStatus.UPLOADING)
                final_status = self.cloud.upload_event(event)
                self.database.update_event_status(event.id, final_status)
                self.database.complete_upload(job.id)
                logger.info("Cloud event delivery completed", extra={"event_id": event.id, "job_id": job.id})
            except Exception as exc:
                attempts = job.attempts + 1
                delay = min(
                    self.settings.upload_retry_max_seconds,
                    self.settings.upload_retry_base_seconds * (2 ** min(attempts - 1, 8)),
                )
                delay = max(1, int(delay * random.uniform(0.8, 1.2)))
                retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
                self.database.fail_upload(job.id, str(exc), retry_at)
                self.database.update_event_status(event.id, UploadStatus.FAILED)
                logger.exception(
                    "Cloud upload failed; retry scheduled in %ss",
                    delay,
                    extra={"event_id": event.id, "job_id": job.id},
                )
