from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import struct
import wave

from homeguard_agent.app_state import AppStateStore
from homeguard_agent.config import Settings
from homeguard_agent.database import EventDatabase
from homeguard_agent.remote_commands import RemoteCommandWorker


def wav_bytes(path: Path) -> bytes:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"".join(struct.pack("<h", 0) for _ in range(800)))
    return path.read_bytes()


class FakeCloud:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.command_updates: list[tuple[str, str, str]] = []
        self.voice_updates: list[tuple[str, str]] = []

    def fetch_voice_message(self, voice_message_id: str):
        return {
            "id": voice_message_id,
            "storage_path": "owner/phone/message.wav",
            "size_bytes": len(self.payload),
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
        }

    def download_voice_message(self, storage_path: str) -> bytes:
        return self.payload

    def update_remote_command(self, command_id: str, status: str, detail: str = ""):
        self.command_updates.append((command_id, status, detail))

    def update_voice_message(self, voice_message_id: str, status: str):
        self.voice_updates.append((voice_message_id, status))


class FakeAudio:
    def __init__(self):
        self.played = None
        self.stopped = False

    def play_async(self, path: Path, **kwargs):
        self.played = (path, kwargs)

    def stop(self, session_id=None):
        self.stopped = session_id or True
        return True



class FakeStreamManager:
    def __init__(self):
        self.started = None
        self.stopped = False

    def start(self, payload):
        self.started = payload
        return type("Request", (), {"session_id": payload["session_id"]})()

    def stop(self, session_id=None):
        self.stopped = session_id or True
        return True

def make_worker(tmp_path: Path, payload: bytes, stream=None):
    settings = Settings(data_dir=tmp_path)
    settings.ensure_directories()
    db = EventDatabase(settings.database_path)
    cloud = FakeCloud(payload)
    audio = FakeAudio()
    worker = RemoteCommandWorker(
        db,
        cloud,  # type: ignore[arg-type]
        audio,  # type: ignore[arg-type]
        AppStateStore(settings.state_path),
        settings,
        stream_manager=stream,
    )
    return worker, db, cloud, audio


def command(command_type: str = "play_audio", nonce: str = "nonce-1"):
    return {
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "command_type": command_type,
        "nonce": nonce,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
        "payload": {
            "voice_message_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "volume": 85,
            "repeat_count": 1,
            "restore_volume": True,
        },
    }


def test_remote_play_validates_and_starts_audio(tmp_path: Path):
    payload = wav_bytes(tmp_path / "source.wav")
    worker, db, cloud, audio = make_worker(tmp_path, payload)
    worker._handle(command())
    assert audio.played is not None
    assert audio.played[1]["volume"] == 85
    assert ("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "received") in cloud.voice_updates
    assert any(status == "executing" for _, status, _ in cloud.command_updates)
    db.close()


def test_remote_replay_is_rejected(tmp_path: Path):
    payload = wav_bytes(tmp_path / "source.wav")
    worker, db, cloud, _ = make_worker(tmp_path, payload)
    worker._handle(command())
    worker._handle(command())
    assert cloud.command_updates[-1][1] == "failed"
    assert "Replay" in cloud.command_updates[-1][2]
    db.close()


def test_emergency_disable_rejects_remote_command(tmp_path: Path):
    payload = wav_bytes(tmp_path / "source.wav")
    worker, db, cloud, audio = make_worker(tmp_path, payload)
    worker.state_store.emergency_disable("test")
    worker._handle(command())
    assert audio.played is None
    assert cloud.command_updates[-1][1] == "failed"
    assert "Emergency" in cloud.command_updates[-1][2]
    db.close()


def test_remote_stop_command_stops_audio(tmp_path: Path):
    payload = wav_bytes(tmp_path / "source.wav")
    worker, db, cloud, audio = make_worker(tmp_path, payload)
    worker._handle(command("stop_audio", nonce="nonce-stop"))
    assert audio.stopped is True
    assert cloud.command_updates[-1][1] == "completed"
    db.close()


def test_remote_start_stream_uses_optional_manager(tmp_path: Path):
    payload = wav_bytes(tmp_path / "source.wav")
    stream = FakeStreamManager()
    worker, db, cloud, _ = make_worker(tmp_path, payload, stream=stream)
    request = command("start_stream", nonce="nonce-stream")
    request["payload"] = {
        "session_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "signaling_url": "wss://signal.example.com",
        "ice_servers": [],
        "max_fps": 15,
    }
    worker._handle(request)
    assert stream.started == request["payload"]
    assert cloud.command_updates[-1][1] == "completed"
    db.close()


def test_remote_stop_stream_stops_optional_manager(tmp_path: Path):
    payload = wav_bytes(tmp_path / "source.wav")
    stream = FakeStreamManager()
    worker, db, cloud, _ = make_worker(tmp_path, payload, stream=stream)
    request = command("stop_stream", nonce="nonce-stop-stream")
    request["payload"] = {"session_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}
    worker._handle(request)
    assert stream.stopped == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert cloud.command_updates[-1][1] == "completed"
    db.close()


def test_cloud_heartbeat_failure_is_rate_limited_and_nonfatal(tmp_path: Path):
    payload = wav_bytes(tmp_path / "source.wav")
    worker, db, cloud, _ = make_worker(tmp_path, payload)
    calls = {"count": 0}

    def fail_heartbeat():
        calls["count"] += 1
        raise RuntimeError("offline")

    cloud.register_windows_device = fail_heartbeat  # type: ignore[attr-defined]
    worker._send_heartbeat_if_due()
    worker._send_heartbeat_if_due()
    assert calls["count"] == 1
    assert worker._next_heartbeat_at > 0
    db.close()
