import json
import logging
from pathlib import Path

from homeguard_agent.logging_config import configure_logging, set_request_id, reset_request_id


def test_rotating_json_logs_include_request_context(tmp_path: Path):
    configure_logging(tmp_path, debug=True, max_bytes=500, backup_count=2)
    token = set_request_id("request-123")
    try:
        logger = logging.getLogger("test")
        for index in range(30):
            logger.debug("line %s %s", index, "x" * 50)
        logger.info("hello", extra={"event_id": "event-1"})
    finally:
        reset_request_id(token)
    active = tmp_path / "homeguard.jsonl"
    assert active.exists()
    files = list(tmp_path.glob("homeguard.jsonl*"))
    assert 1 <= len(files) <= 3
    parsed = []
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            parsed.append(json.loads(line))
    hello = next(item for item in parsed if item["message"] == "hello")
    assert hello["request_id"] == "request-123"
    assert hello["event_id"] == "event-1"
