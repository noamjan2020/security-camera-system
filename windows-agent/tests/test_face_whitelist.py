from pathlib import Path

import numpy as np

from homeguard_agent.face_whitelist import FaceWhitelist


def test_face_whitelist_enroll_match_persist_and_remove(tmp_path: Path):
    path = tmp_path / "faces.bin"
    whitelist = FaceWhitelist(path, threshold=0.8)
    vector = np.arange(128, dtype=np.float32) + 1
    assert whitelist.enroll("Noam Jan", vector) == 1
    match = whitelist.match(vector * 2)
    assert match.matched is True
    assert match.person_name == "Noam Jan"
    assert match.usable_face is True

    restored = FaceWhitelist(path, threshold=0.8)
    assert restored.people() == {"Noam Jan": 1}
    assert restored.match(vector).matched is True
    assert restored.remove("Noam Jan") is True
    assert restored.match(vector).matched is False


def test_missing_or_invalid_face_is_never_whitelisted(tmp_path: Path):
    whitelist = FaceWhitelist(tmp_path / "faces.bin")
    match = whitelist.match(None)
    assert match.matched is False
    assert match.usable_face is False
    try:
        whitelist.enroll("Bad", np.zeros(128, dtype=np.float32))
    except ValueError:
        pass
    else:
        raise AssertionError("Zero embedding should be rejected")
