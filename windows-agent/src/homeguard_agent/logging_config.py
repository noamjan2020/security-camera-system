from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_request_id: ContextVar[str] = ContextVar("homeguard_request_id", default="-")


class JsonFormatter(logging.Formatter):
    """Compact JSON-lines formatter suitable for support bundles and parsing."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "thread": record.threadName,
            "request_id": getattr(record, "request_id", _request_id.get()),
            "message": record.getMessage(),
        }
        for key in ("event_id", "device_id", "camera_index", "job_id", "command_id", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class HumanFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        request_id = getattr(record, "request_id", _request_id.get())
        record.request_id = request_id
        return super().format(record)


def set_request_id(value: str):
    return _request_id.set(value)


def reset_request_id(token) -> None:
    _request_id.reset(token)


def configure_logging(
    log_dir: Path,
    *,
    debug: bool = False,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if debug else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(
        HumanFormatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s")
    )

    json_file = logging.handlers.RotatingFileHandler(
        log_dir / "homeguard.jsonl",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    json_file.setLevel(level)
    json_file.setFormatter(JsonFormatter())

    text_file = logging.handlers.RotatingFileHandler(
        log_dir / "homeguard.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    text_file.setLevel(level)
    text_file.setFormatter(
        HumanFormatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s")
    )

    root.addHandler(console)
    root.addHandler(json_file)
    root.addHandler(text_file)

    # Reduce noisy third-party logs unless full debug is explicitly requested.
    if not debug:
        for name in ("httpx", "httpcore", "multipart", "PIL"):
            logging.getLogger(name).setLevel(logging.WARNING)

    logging.captureWarnings(True)
    logging.getLogger(__name__).info(
        "Logging configured",
        extra={"duration_ms": 0},
    )


def install_exception_hooks() -> None:
    logger = logging.getLogger("homeguard.crash")

    def handle_exception(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical("Unhandled process exception", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception

    if hasattr(os, "register_at_fork"):
        # No hook needed; this branch only documents that fork-aware runtimes are tolerated.
        pass
