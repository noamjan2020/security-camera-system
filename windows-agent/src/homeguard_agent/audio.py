from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Callable
import logging
import platform
import subprocess
import time
import wave

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AudioMetadata:
    duration_seconds: float
    channels: int
    sample_rate: int
    sample_width: int


def validate_wave_file(path: Path, *, max_seconds: int, max_bytes: int) -> AudioMetadata:
    if max_seconds <= 0 or max_bytes <= 44:
        raise ValueError("Audio limits must be positive")
    size = path.stat().st_size
    if size <= 44 or size > max_bytes:
        raise ValueError(f"Invalid WAV size: {size} bytes")
    try:
        with wave.open(str(path), "rb") as audio:
            channels = audio.getnchannels()
            sample_rate = audio.getframerate()
            sample_width = audio.getsampwidth()
            frames = audio.getnframes()
    except (wave.Error, EOFError) as exc:
        raise ValueError("Invalid WAV container") from exc
    if channels not in {1, 2}:
        raise ValueError("WAV must be mono or stereo")
    if not 8000 <= sample_rate <= 48000:
        raise ValueError("Unsupported WAV sample rate")
    if sample_width not in {1, 2, 3, 4}:
        raise ValueError("Unsupported WAV sample width")
    duration = frames / sample_rate if sample_rate else 0
    if duration <= 0 or duration > max_seconds + 0.25:
        raise ValueError(f"WAV duration must be between 0 and {max_seconds} seconds")
    return AudioMetadata(duration, channels, sample_rate, sample_width)


class WindowsVolumeController:
    def get_volume(self) -> float | None:
        if platform.system() != "Windows":
            return None
        try:
            from pycaw.pycaw import AudioUtilities

            endpoint = AudioUtilities.GetSpeakers().EndpointVolume
            return float(endpoint.GetMasterVolumeLevelScalar())
        except Exception:
            logger.exception("Unable to read Windows speaker volume")
            return None

    def set_volume(self, scalar: float) -> bool:
        if platform.system() != "Windows":
            return False
        try:
            from pycaw.pycaw import AudioUtilities

            endpoint = AudioUtilities.GetSpeakers().EndpointVolume
            endpoint.SetMasterVolumeLevelScalar(max(0.0, min(1.0, scalar)), None)
            return True
        except Exception:
            logger.exception("Unable to set Windows speaker volume")
            return False


class AudioPlaybackService:
    def __init__(
        self,
        *,
        volume_controller: WindowsVolumeController | None = None,
        status_callback: Callable[[str, str, str], None] | None = None,
    ):
        self._stop = Event()
        self._lock = Lock()
        self._worker: Thread | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self.volume_controller = volume_controller or WindowsVolumeController()
        self.status_callback = status_callback
        self.current_command_id: str | None = None
        self.status = "idle"

    def play_async(
        self,
        path: Path,
        *,
        repeat_count: int = 1,
        volume: int = 100,
        restore_volume: bool = True,
        command_id: str = "local",
        delete_after: bool = False,
    ) -> None:
        if not path.exists():
            raise FileNotFoundError(path)
        self.stop()
        self._stop.clear()
        self.current_command_id = command_id
        self._worker = Thread(
            target=self._play_worker,
            kwargs={
                "path": path,
                "repeat_count": repeat_count,
                "volume": volume,
                "restore_volume": restore_volume,
                "command_id": command_id,
                "delete_after": delete_after,
            },
            name=f"audio-playback-{command_id[:12]}",
            daemon=True,
        )
        self._worker.start()

    def _set_status(self, command_id: str, status: str, detail: str = "") -> None:
        self.status = status
        logger.info("Audio status: %s (%s)", status, detail, extra={"command_id": command_id})
        if self.status_callback:
            try:
                self.status_callback(command_id, status, detail)
            except Exception:
                logger.exception("Audio status callback failed", extra={"command_id": command_id})

    def _play_worker(
        self,
        *,
        path: Path,
        repeat_count: int,
        volume: int,
        restore_volume: bool,
        command_id: str,
        delete_after: bool,
    ) -> None:
        previous = self.volume_controller.get_volume()
        changed = self.volume_controller.set_volume(volume / 100.0)
        self._set_status(command_id, "playing")
        try:
            with self._lock:
                for _ in range(repeat_count):
                    if self._stop.is_set():
                        self._set_status(command_id, "stopped")
                        return
                    self._play_once(path)
            self._set_status(command_id, "completed")
        except Exception as exc:
            self._set_status(command_id, "failed", str(exc))
            logger.exception("Audio playback failed", extra={"command_id": command_id})
        finally:
            if restore_volume and changed and previous is not None:
                self.volume_controller.set_volume(previous)
            if delete_after:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.exception("Failed deleting temporary audio", extra={"command_id": command_id})
            self.current_command_id = None

    def _play_once(self, path: Path) -> None:
        if platform.system() == "Windows":
            import winsound

            winsound.PlaySound(str(path), winsound.SND_FILENAME)
            return
        for player in (["aplay", str(path)], ["afplay", str(path)]):
            try:
                self._process = subprocess.Popen(
                    player, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                while self._process.poll() is None:
                    if self._stop.wait(0.05):
                        self._process.terminate()
                        self._process.wait(timeout=2)
                        return
                if self._process.returncode == 0:
                    return
            except FileNotFoundError:
                continue
        # Test/development fallback: emulate duration without output hardware.
        metadata = validate_wave_file(path, max_seconds=120, max_bytes=25_000_000)
        logger.warning("No audio player found; emulating %.2fs playback", metadata.duration_seconds)
        self._stop.wait(metadata.duration_seconds)

    def stop(self) -> None:
        self._stop.set()
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
            except OSError:
                pass
        if platform.system() == "Windows":
            try:
                import winsound

                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                logger.debug("Windows audio purge was unavailable", exc_info=True)
        worker = self._worker
        if worker and worker.is_alive() and worker is not __import__("threading").current_thread():
            worker.join(timeout=3)
        if self.current_command_id:
            self._set_status(self.current_command_id, "stopped")
        self.status = "idle"
