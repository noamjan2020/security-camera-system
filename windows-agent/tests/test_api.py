from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient

from homeguard_agent.api import create_app
from homeguard_agent.app_state import AppStateStore
from homeguard_agent.audio import AudioPlaybackService
from homeguard_agent.database import EventDatabase
from homeguard_agent.event_service import EventService
from homeguard_agent.maintenance import MaintenanceService
from homeguard_agent.pairing import PairingService
from homeguard_agent.config import Settings


@dataclass
class FakeCamera:
    active: bool = True
    last_frame_at = None
    fps: float = 10.0
    inference_fps: float = 4.0

    def snapshot_jpeg(self):
        return b"jpeg"

    def pause(self):
        self.state.set_privacy_paused(True)

    def resume(self):
        self.state.set_privacy_paused(False)


def make_client(tmp_path: Path, push_token_registrar=None):
    settings = Settings(data_dir=tmp_path)
    settings.ensure_directories()
    db = EventDatabase(settings.database_path)
    state = AppStateStore(settings.state_path)
    camera = FakeCamera()
    camera.state = state
    events = EventService(db, settings.media_dir, "Test")
    maintenance = MaintenanceService(db, events, settings)
    pairing = PairingService(db, settings.api_port, ttl_seconds=120, base_url="http://192.168.1.5:8765")
    app = create_app(
        db,
        events,
        camera,  # type: ignore[arg-type]
        AudioPlaybackService(),
        state,
        maintenance,
        pairing,
        "secret-token",
        settings.audio_dir,
        settings.logs_dir,
        cloud_enabled=False,
        audio_max_bytes=1_000_000,
        audio_max_seconds=30,
        push_token_registrar=push_token_registrar,
    )
    return TestClient(app), db, state, pairing


def test_auth_and_request_id(tmp_path: Path):
    client, db, _, _ = make_client(tmp_path)
    assert client.get("/health").status_code == 401
    response = client.get("/health", headers={"Authorization": "Bearer secret-token"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert response.json()["camera_active"] is True
    db.close()


def test_emergency_blocks_remote_resume(tmp_path: Path):
    client, db, state, _ = make_client(tmp_path)
    headers = {"Authorization": "Bearer secret-token"}
    state.emergency_disable("test")
    response = client.post("/privacy/resume", headers=headers)
    assert response.status_code == 423
    assert client.post("/emergency/disable", headers=headers).status_code == 403
    db.close()


def test_one_time_pairing_and_revocation(tmp_path: Path):
    from urllib.parse import parse_qs, urlparse

    client, db, _, pairing = make_client(tmp_path)
    offer = pairing.create_offer()
    code = parse_qs(urlparse(offer.uri).query)["code"][0]
    claim = client.post("/pair/claim", json={"code": code, "device_name": "Noam phone"})
    assert claim.status_code == 200
    payload = claim.json()
    device_headers = {"Authorization": f"Bearer {payload['token']}"}
    assert client.get("/health", headers=device_headers).status_code == 200

    reused = client.post("/pair/claim", json={"code": code, "device_name": "Second phone"})
    assert reused.status_code == 400

    owner_headers = {"Authorization": "Bearer secret-token"}
    assert client.delete(f"/devices/{payload['device_id']}", headers=owner_headers).status_code == 204
    assert client.get("/health", headers=device_headers).status_code == 403
    db.close()


def test_paired_phone_can_register_push_token(tmp_path: Path):
    from urllib.parse import parse_qs, urlparse

    registrations = []
    client, db, _, pairing = make_client(
        tmp_path,
        push_token_registrar=lambda device_id, name, token: registrations.append((device_id, name, token)),
    )
    offer = pairing.create_offer()
    code = parse_qs(urlparse(offer.uri).query)["code"][0]
    claim = client.post("/pair/claim", json={"code": code, "device_name": "Noam phone"}).json()
    response = client.post(
        "/push/register",
        headers={"Authorization": f"Bearer {claim['token']}"},
        json={"token": "f" * 64, "device_name": "Noam Android"},
    )
    assert response.status_code == 200
    assert registrations == [(claim["device_id"], "Noam Android", "f" * 64)]
    assert client.post(
        "/push/register",
        headers={"Authorization": "Bearer secret-token"},
        json={"token": "f" * 64, "device_name": "owner"},
    ).status_code == 400
    db.close()
