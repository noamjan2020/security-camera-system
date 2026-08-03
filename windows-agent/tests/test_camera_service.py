from pathlib import Path

import numpy as np

from homeguard_agent.app_state import AppStateStore
from homeguard_agent.camera_service import CameraService
from homeguard_agent.detector import Detection


class FakeDetector:
    name = "fake"

    def detect(self, frame):
        return []


class FakeEvents:
    pass


def make_service(tmp_path: Path) -> CameraService:
    return CameraService(
        0,
        FakeDetector(),  # type: ignore[arg-type]
        FakeEvents(),  # type: ignore[arg-type]
        AppStateStore(tmp_path / "state.json"),
        visible_seconds=1,
        cooldown_seconds=60,
        max_fps=10,
        inference_fps=4,
    )


def test_latest_frame_queue_never_grows(tmp_path: Path):
    service = make_service(tmp_path)
    first = np.zeros((8, 8, 3), dtype=np.uint8)
    latest = np.ones((8, 8, 3), dtype=np.uint8)
    service._offer_latest((1.0, first))
    service._offer_latest((2.0, latest))
    assert service._frame_queue.qsize() == 1
    timestamp, frame = service._frame_queue.get_nowait()
    assert timestamp == 2.0
    assert np.array_equal(frame, latest)


def test_clarity_score_is_bounded_and_finite(tmp_path: Path):
    frame = np.zeros((80, 80, 3), dtype=np.uint8)
    frame[20:60, 20:60] = 255
    score = make_service(tmp_path)._clarity_score(frame, Detection(10, 10, 60, 60, 0.9))
    assert score >= 0
    assert np.isfinite(score)


def test_detection_zone_filters_by_person_center(tmp_path: Path):
    service = CameraService(
        0,
        FakeDetector(),  # type: ignore[arg-type]
        FakeEvents(),  # type: ignore[arg-type]
        AppStateStore(tmp_path / "state-zone.json"),
        visible_seconds=1,
        cooldown_seconds=60,
        max_fps=10,
        inference_fps=4,
        detection_zone=(0.0, 0.0, 0.5, 1.0),
        exclusion_zones=[(0.0, 0.0, 0.2, 1.0)],
    )
    assert not service._detection_allowed(Detection(0, 10, 20, 20, 0.9), 100, 100)
    assert service._detection_allowed(Detection(20, 10, 20, 20, 0.9), 100, 100)
    assert not service._detection_allowed(Detection(70, 10, 20, 20, 0.9), 100, 100)
