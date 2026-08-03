from __future__ import annotations

import ctypes
import hmac
import hashlib
import logging
import platform
import secrets
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .database import EventDatabase

from fastapi import Header, HTTPException, status

logger = logging.getLogger(__name__)


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[DATA_BLOB, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _dpapi_protect(data: bytes) -> bytes:
    in_blob, keepalive = _blob(data)
    out_blob = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptProtectData(
        ctypes.byref(in_blob), "HomeGuard secret", None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)
        del keepalive


def _dpapi_unprotect(data: bytes) -> bytes:
    in_blob, keepalive = _blob(data)
    out_blob = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)
        del keepalive



def protect_local_bytes(data: bytes) -> bytes:
    if platform.system() == "Windows":
        return b"DPAPI\0" + _dpapi_protect(data)
    logger.warning("DPAPI unavailable on this platform; using owner-only file permissions")
    return b"PLAIN\0" + data


def unprotect_local_bytes(data: bytes) -> bytes:
    if data.startswith(b"DPAPI\0"):
        if platform.system() != "Windows":
            raise RuntimeError("DPAPI data can only be decrypted on Windows")
        return _dpapi_unprotect(data[6:])
    if data.startswith(b"PLAIN\0"):
        return data[6:]
    return data

def generate_token() -> str:
    return secrets.token_urlsafe(48)


def save_token(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = protect_local_bytes(token.encode("utf-8"))
    path.write_bytes(raw)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    logger.info("API credential stored securely for this platform")


def load_token(path: Path) -> str:
    raw = path.read_bytes()
    return unprotect_local_bytes(raw).decode("utf-8").strip()


class TokenGuard:
    def __init__(self, expected_token: str, database: "EventDatabase | None" = None, *, owner_only: bool = False):
        if not expected_token:
            raise ValueError("API token cannot be empty")
        self.expected_token = expected_token
        self.database = database
        self.owner_only = owner_only

    def __call__(self, authorization: str | None = Header(default=None)) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            logger.warning("API request rejected: missing bearer token")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
        supplied = authorization.removeprefix("Bearer ").strip()
        if hmac.compare_digest(supplied, self.expected_token):
            return "owner"
        if not self.owner_only and self.database is not None:
            device_id = self.database.authenticate_paired_device(hashlib.sha256(supplied.encode("utf-8")).hexdigest())
            if device_id:
                return device_id
        logger.warning("API request rejected: invalid or revoked bearer token")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or revoked bearer token")


def validate_command_window(issued_at: datetime, expires_at: datetime, max_age_seconds: int = 120) -> None:
    now = datetime.now(timezone.utc)
    if issued_at.tzinfo is None or expires_at.tzinfo is None:
        raise ValueError("Command timestamps must be timezone-aware")
    if expires_at <= now:
        raise ValueError("Command expired")
    if issued_at > now + timedelta(seconds=5):
        raise ValueError("Command timestamp is in the future")
    if (now - issued_at).total_seconds() > max_age_seconds:
        raise ValueError("Command is too old")
    if expires_at <= issued_at:
        raise ValueError("Invalid command expiry")
    if (expires_at - issued_at).total_seconds() > max_age_seconds + 30:
        raise ValueError("Command validity window is too long")
