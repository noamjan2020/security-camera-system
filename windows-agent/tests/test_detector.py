import numpy as np

from homeguard_agent.detector import YoloOnnxDetector


def test_letterbox_preserves_aspect_ratio():
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    image, scale, pad_x, pad_y = YoloOnnxDetector._letterbox(frame, 640)
    assert image.shape == (640, 640, 3)
    assert scale == 0.5
    assert pad_x == 0
    assert pad_y == 140
