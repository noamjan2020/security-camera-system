from pathlib import Path
import struct
import wave

import pytest

from homeguard_agent.audio import AudioPlaybackService, validate_wave_file


def create_wav(path: Path, seconds: float = 0.1, rate: int = 8000) -> None:
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(b"".join(struct.pack("<h", 0) for _ in range(frames)))


class FakeVolume:
    def __init__(self):
        self.values = []

    def get_volume(self):
        return 0.25

    def set_volume(self, scalar: float):
        self.values.append(scalar)
        return True


def test_wave_validation(tmp_path: Path):
    path = tmp_path / "valid.wav"
    create_wav(path)
    metadata = validate_wave_file(path, max_seconds=1, max_bytes=100_000)
    assert 0.09 <= metadata.duration_seconds <= 0.11

    with pytest.raises(ValueError):
        validate_wave_file(path, max_seconds=0, max_bytes=100_000)


def test_volume_is_restored_after_playback(tmp_path: Path):
    path = tmp_path / "valid.wav"
    create_wav(path)
    volume = FakeVolume()
    statuses = []
    service = AudioPlaybackService(
        volume_controller=volume,
        status_callback=lambda command_id, status, detail: statuses.append(status),
    )
    service._play_once = lambda _: None  # type: ignore[method-assign]
    service.play_async(path, volume=80, command_id="cmd")
    service._worker.join(timeout=2)
    assert volume.values == [0.8, 0.25]
    assert statuses[:2] == ["playing", "completed"]
