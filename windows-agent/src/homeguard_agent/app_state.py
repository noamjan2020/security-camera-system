from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RuntimeState:
    privacy_paused: bool = False
    emergency_disabled: bool = False
    emergency_disabled_at: str | None = None
    emergency_reason: str | None = None


class AppStateStore:
    """Atomic persistent state for privacy and emergency controls."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._state = self._load()

    def snapshot(self) -> RuntimeState:
        with self._lock:
            return RuntimeState(**asdict(self._state))

    def set_privacy_paused(self, paused: bool) -> RuntimeState:
        with self._lock:
            if self._state.emergency_disabled and not paused:
                raise PermissionError("Emergency disable can only be cleared locally")
            self._state.privacy_paused = paused
            self._save_locked()
            logger.warning("Privacy state changed", extra={"event_id": "privacy_pause" if paused else "privacy_resume"})
            return self.snapshot()

    def emergency_disable(self, reason: str = "Local emergency button") -> RuntimeState:
        with self._lock:
            self._state.emergency_disabled = True
            self._state.privacy_paused = True
            self._state.emergency_disabled_at = datetime.now(timezone.utc).isoformat()
            self._state.emergency_reason = reason[:200]
            self._save_locked()
            logger.critical("Emergency disable activated", extra={"event_id": "emergency_disable"})
            return self.snapshot()

    def clear_emergency_locally(self) -> RuntimeState:
        with self._lock:
            self._state.emergency_disabled = False
            self._state.privacy_paused = False
            self._state.emergency_disabled_at = None
            self._state.emergency_reason = None
            self._save_locked()
            logger.warning("Emergency disable cleared locally", extra={"event_id": "emergency_clear"})
            return self.snapshot()

    def _load(self) -> RuntimeState:
        if not self.path.exists():
            return RuntimeState()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return RuntimeState(
                privacy_paused=bool(raw.get("privacy_paused", False)),
                emergency_disabled=bool(raw.get("emergency_disabled", False)),
                emergency_disabled_at=raw.get("emergency_disabled_at"),
                emergency_reason=raw.get("emergency_reason"),
            )
        except (OSError, ValueError, TypeError):
            logger.exception("State file was unreadable; starting in safe paused mode")
            return RuntimeState(privacy_paused=True)

    def _save_locked(self) -> None:
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(self._state), indent=2), encoding="utf-8")
        try:
            temp.chmod(0o600)
        except OSError:
            pass
        os.replace(temp, self.path)
