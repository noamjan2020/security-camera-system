from datetime import datetime, timedelta, timezone
import pytest

from homeguard_agent.security import validate_command_window


def test_valid_command_window():
    now = datetime.now(timezone.utc)
    validate_command_window(now - timedelta(seconds=2), now + timedelta(seconds=30))


def test_expired_command_rejected():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="expired"):
        validate_command_window(now - timedelta(minutes=1), now - timedelta(seconds=1))
