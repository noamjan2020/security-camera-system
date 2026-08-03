from __future__ import annotations

from pathlib import Path
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)

FACE_MODELS = {
    "face_detection_yunet_2023mar.onnx": (
        "https://github.com/opencv/opencv_zoo/raw/refs/heads/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        200_000,
    ),
    "face_recognition_sface_2021dec.onnx": (
        "https://github.com/opencv/opencv_zoo/raw/refs/heads/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        30_000_000,
    ),
}


def install_face_models(target_dir: Path, *, timeout_seconds: int = 120) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    installed: list[Path] = []
    for name, (url, minimum_size) in FACE_MODELS.items():
        target = target_dir / name
        if target.exists() and target.stat().st_size >= minimum_size:
            logger.info("Face model already installed", extra={"model": name, "bytes": target.stat().st_size})
            installed.append(target)
            continue
        temp = target.with_suffix(target.suffix + ".download")
        temp.unlink(missing_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": "HomeGuard/0.3"})
        logger.info("Downloading face model", extra={"model": name})
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response, temp.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            size = temp.stat().st_size
            if size < minimum_size:
                raise RuntimeError(f"Downloaded {name} is unexpectedly small ({size} bytes)")
            os.replace(temp, target)
            installed.append(target)
            logger.info("Face model installed", extra={"model": name, "bytes": size})
        except Exception:
            temp.unlink(missing_ok=True)
            logger.exception("Face model download failed", extra={"model": name})
            raise
    return installed
