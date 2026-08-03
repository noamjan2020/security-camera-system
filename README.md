# HomeGuard 0.4

HomeGuard is a privacy-first personal security-camera workspace with:

- a lightweight Windows 11 camera agent;
- a polished native Android app;
- Supabase migrations and Edge Functions;
- a device-bound WebRTC signaling service;
- repeatable Windows and Android build pipelines.

## What is implemented

The Windows agent uses separate capture and inference threads with a one-frame queue, so slow AI never creates an ever-growing video backlog. It supports a zero-download OpenCV HOG fallback, optional YOLO ONNX detection, local YuNet/SFace face whitelisting, SQLite/WAL event storage, rotating JSON/text debug logs, automatic retention, durable cloud retries, persistent emergency disable, one-time QR pairing, remote voice playback, and an optional lazy-loaded aiortc publisher.

The Android app uses Jetpack Compose with Home, Events, Live, Talk, and Settings sections. Credentials are encrypted with Android Keystore. It supports FCM deep links and image previews, local-LAN control, Supabase account/cloud fallback, protected event images, voice commands, and a lightweight WebView-based WebRTC viewer whose signaling token never enters JavaScript.

## Performance approach

- Capture queue capacity: **one frame**.
- Default capture: **1280×720 / 12 FPS**.
- Default inference: **4 FPS**.
- Face recognition runs only after a confirmed person event.
- WebRTC dependencies load only while remote Live View is active.
- Android release builds enable code and resource shrinking.

## Start

Read `START-HERE.md`, then run on Windows:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\first-setup.ps1 -WithOnnx -WithWebRtc
.\scripts\dev-run.ps1
```

## Security warning

Never port-forward the Windows API. Private-LAN HTTP is accepted only for numeric private addresses; public communication must use HTTPS/WSS and authenticated cloud services. Never place a Supabase service-role key, Firebase service-account JSON, TURN shared secret, or signing password inside either client.

## Honest release status

The source implementation and all tests runnable in this Linux session are passing. Android SDK/Gradle, Windows packaging tools, physical devices, Supabase/Firebase credentials, and a deployed TURN service are unavailable here, so installable APK/EXE/installer and real-device end-to-end acceptance cannot honestly be claimed yet. See `BUILD-STATUS.txt` and `docs/KNOWN_LIMITATIONS.md`.
# security-camera-system
# security-camera-system
