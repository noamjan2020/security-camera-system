from pathlib import Path

import pytest

from homeguard_agent.app_state import AppStateStore


def test_emergency_state_persists_and_blocks_remote_resume(tmp_path: Path):
    path = tmp_path / "state.json"
    store = AppStateStore(path)
    store.emergency_disable("test")

    restored = AppStateStore(path)
    state = restored.snapshot()
    assert state.emergency_disabled is True
    assert state.privacy_paused is True
    with pytest.raises(PermissionError):
        restored.set_privacy_paused(False)

    restored.clear_emergency_locally()
    final = AppStateStore(path).snapshot()
    assert final.emergency_disabled is False
    assert final.privacy_paused is False


def test_corrupt_state_fails_safe(tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text("not json", encoding="utf-8")
    assert AppStateStore(path).snapshot().privacy_paused is True
