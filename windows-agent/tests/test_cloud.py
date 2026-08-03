from datetime import datetime, timezone
from pathlib import Path
import time

import httpx

from homeguard_agent.cloud import SupabaseCloudClient, UploadWorker
from homeguard_agent.config import Settings
from homeguard_agent.database import EventDatabase
from homeguard_agent.models import EventRecord, FaceResult, UploadStatus


def remote_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        remote_enabled=True,
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon",
        supabase_access_token="access",
        owner_id="11111111-1111-1111-1111-111111111111",
        device_id="22222222-2222-2222-2222-222222222222",
        camera_id="33333333-3333-3333-3333-333333333333",
        notify_function_url="https://project.supabase.co/functions/v1/notify-event",
        upload_retry_base_seconds=1,
        upload_retry_max_seconds=10,
    )


def make_event(tmp_path: Path) -> EventRecord:
    image = tmp_path / "event.jpg"
    image.write_bytes(b"jpeg")
    return EventRecord(
        id="44444444-4444-4444-4444-444444444444",
        timestamp=datetime.now(timezone.utc),
        camera_name="Test",
        screenshot_path=image,
        person_confidence=0.9,
        face_result=FaceResult.UNKNOWN,
    )


def test_cloud_register_and_upload_pipeline(tmp_path: Path):
    settings = remote_settings(tmp_path)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json={})

    cloud = SupabaseCloudClient(settings)
    cloud.client.close()
    cloud.client = httpx.Client(transport=httpx.MockTransport(handler))
    cloud.register_windows_device()
    cloud.register_push_token("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "Noam phone", "f" * 64)
    assert cloud.upload_event(make_event(tmp_path)) == UploadStatus.NOTIFIED
    urls = [str(request.url) for request in requests]
    assert sum("/rest/v1/devices" in url for url in urls) >= 2
    assert any("/rest/v1/push_tokens?on_conflict=token" in url for url in urls)
    assert any("/storage/v1/object/event-media/" in url for url in urls)
    assert any("/rest/v1/events" in url for url in urls)
    assert any("/functions/v1/notify-event" in url for url in urls)
    cloud.close()


class FakeCloud:
    def __init__(self):
        self.calls = 0
        self.closed = False

    def upload_event(self, event: EventRecord) -> UploadStatus:
        self.calls += 1
        return UploadStatus.UPLOADED

    def close(self) -> None:
        self.closed = True


def test_upload_worker_completes_durable_job(tmp_path: Path):
    settings = remote_settings(tmp_path)
    db = EventDatabase(tmp_path / "events.db")
    event = make_event(tmp_path)
    db.add_event(event, queue_upload=True)
    cloud = FakeCloud()
    worker = UploadWorker(db, cloud, settings)  # type: ignore[arg-type]
    worker.start()
    worker.notify()
    deadline = time.monotonic() + 3
    while db.upload_queue_depth() and time.monotonic() < deadline:
        time.sleep(0.02)
    worker.stop()
    assert db.upload_queue_depth() == 0
    assert db.get_event(event.id).notification_status == UploadStatus.UPLOADED.value
    assert cloud.calls == 1
    assert cloud.closed is True
    db.close()


def test_cloud_claims_and_downloads_remote_voice(tmp_path: Path):
    settings = remote_settings(tmp_path)
    command_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    voice_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path.endswith("/remote_commands") and request.method == "GET":
            return httpx.Response(
                200,
                json=[{
                    "id": command_id,
                    "command_type": "play_audio",
                    "payload": {"voice_message_id": voice_id},
                    "nonce": "nonce",
                    "expires_at": "2099-01-01T00:00:00+00:00",
                    "status": "pending",
                }],
            )
        if path.endswith("/remote_commands") and request.method == "PATCH":
            return httpx.Response(
                200,
                json=[{
                    "id": command_id,
                    "command_type": "play_audio",
                    "payload": {"voice_message_id": voice_id},
                    "nonce": "nonce",
                    "expires_at": "2099-01-01T00:00:00+00:00",
                    "status": "received",
                }],
            )
        if path.endswith("/voice_messages") and request.method == "GET":
            return httpx.Response(200, json=[{
                "id": voice_id,
                "storage_path": "owner/phone/voice.wav",
                "size_bytes": 4,
                "duration_ms": 100,
                "status": "uploaded",
                "expires_at": "2099-01-01T00:00:00+00:00",
                "target_device_id": settings.device_id,
            }])
        if "/storage/v1/object/authenticated/voice-media/" in path:
            return httpx.Response(200, content=b"wave")
        if path.endswith("/command_receipts"):
            return httpx.Response(201, json={})
        return httpx.Response(204)

    cloud = SupabaseCloudClient(settings)
    cloud.client.close()
    cloud.client = httpx.Client(transport=httpx.MockTransport(handler))
    command = cloud.fetch_pending_command()
    assert command and command["status"] == "received"
    voice = cloud.fetch_voice_message(voice_id)
    assert voice["storage_path"].endswith("voice.wav")
    assert cloud.download_voice_message(voice["storage_path"]) == b"wave"
    cloud.update_remote_command(command_id, "executing", "validated")
    cloud.update_voice_message(voice_id, "received")
    assert any(request.method == "PATCH" and request.url.path.endswith("/remote_commands") for request in requests)
    assert any(request.url.path.endswith("/command_receipts") for request in requests)
    cloud.close()
