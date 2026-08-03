# Optional local AI models

HomeGuard runs without downloaded models by using OpenCV HOG, but the fallback is less accurate.
For the recommended lightweight configuration, place these files here or in the HomeGuard data-folder `models` directory:

- `yolo11n.onnx` — person detection through ONNX Runtime
- `face_detection_yunet_2023mar.onnx` — local face detection
- `face_recognition_sface_2021dec.onnx` — local face embeddings

Run `scripts/download-models.ps1` to install the two OpenCV face models. HomeGuard never uploads face embeddings.
The YOLO ONNX file must be supplied/exported separately because model licensing and redistribution terms can differ by source.
