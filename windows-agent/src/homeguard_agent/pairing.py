from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import secrets
import socket
from urllib.parse import urlencode
import uuid

from .database import EventDatabase
from .security import generate_token

logger = logging.getLogger(__name__)


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def discover_lan_ip() -> str:
    """Best-effort LAN address discovery without sending application data."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return str(sock.getsockname()[0])
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        sock.close()


@dataclass(slots=True, frozen=True)
class PairingOffer:
    uri: str
    expires_at: datetime
    base_url: str


@dataclass(slots=True, frozen=True)
class ClaimedDevice:
    device_id: str
    token: str


class PairingService:
    def __init__(self, database: EventDatabase, api_port: int, ttl_seconds: int = 120, base_url: str = ""):
        self.database = database
        self.api_port = api_port
        self.ttl_seconds = ttl_seconds
        self.base_url = base_url.rstrip("/")

    def create_offer(self) -> PairingOffer:
        code = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds)
        self.database.create_pairing_challenge(token_hash(code), expires_at)
        base_url = self.base_url or f"http://{discover_lan_ip()}:{self.api_port}"
        query = urlencode({"url": base_url, "code": code})
        uri = f"homeguard://pair?{query}"
        logger.info("Temporary pairing offer created", extra={"expires_at": expires_at.isoformat()})
        return PairingOffer(uri=uri, expires_at=expires_at, base_url=base_url)

    def claim(self, code: str, device_name: str) -> ClaimedDevice:
        normalized_name = " ".join(device_name.strip().split())[:100]
        if not normalized_name:
            raise ValueError("Device name is required")
        if len(code) < 32 or not self.database.consume_pairing_challenge(token_hash(code)):
            logger.warning("Pairing claim rejected")
            raise ValueError("Pairing code is invalid, expired, or already used")
        token = generate_token()
        device_id = str(uuid.uuid4())
        self.database.register_paired_device(device_id, normalized_name, token_hash(token))
        logger.info("Phone paired", extra={"device_id": device_id, "device_name": normalized_name})
        return ClaimedDevice(device_id=device_id, token=token)
