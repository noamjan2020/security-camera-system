# Performance profile

HomeGuard prioritizes low latency and low resource use.

## Default lightweight settings

- camera: 1280×720 at up to 12 capture FPS;
- AI inference: 4 FPS;
- inference input: 640×640;
- queue capacity: one frame;
- JPEG quality: 86;
- face recognition: only after a confirmed person event;
- remote polling: two seconds;
- cloud retries: exponential backoff with jitter.

## Why it remains responsive

- Capture and inference do not block each other.
- Old frames are dropped instead of queued.
- Face recognition does not run on every frame.
- Detection/exclusion zones are center-point checks with negligible cost.
- SQLite uses WAL and indexed retention/upload queries.
- Android event images are cached.
- Release APK builds enable code shrinking and resource shrinking.

## Tuning for a weak PC

```env
HOMEGUARD_CAMERA_WIDTH=960
HOMEGUARD_CAMERA_HEIGHT=540
HOMEGUARD_MAX_FPS=8
HOMEGUARD_INFERENCE_FPS=2
HOMEGUARD_INFERENCE_SIZE=416
```

Higher accuracy may justify a slightly heavier ONNX model or inference rate. Change one setting at a time and inspect capture FPS, inference FPS and CPU use in the dashboard/logs.
