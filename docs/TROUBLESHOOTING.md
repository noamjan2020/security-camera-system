# Troubleshooting

## Camera unavailable

Close other webcam apps, change `HOMEGUARD_CAMERA_INDEX`, reconnect USB cameras, then inspect `homeguard.log` for camera-open/read/reconnect entries.

## High CPU

```env
HOMEGUARD_CAMERA_WIDTH=960
HOMEGUARD_CAMERA_HEIGHT=540
HOMEGUARD_MAX_FPS=8
HOMEGUARD_INFERENCE_FPS=2
HOMEGUARD_INFERENCE_SIZE=416
HOMEGUARD_WEBRTC_MAX_FPS=10
```

Face recognition runs only after confirmed detections. WebRTC loads only during Live View.

## Too many alerts

Increase visible time/cooldown, raise confidence carefully, configure zones, and use YOLO ONNX. Do not weaken face matching merely to hide alerts.

## Phone cannot pair

Use the same private LAN, allow HomeGuard through Windows Firewall on private networks, generate a fresh QR, and do not use a public HTTP host. Pre-0.4 phones must pair again.

## Notifications fail

Grant permission, include `google-services.json`, verify the notification Edge Function/Firebase secrets, inspect push-delivery logs, and refresh the FCM token.

## Remote Live View fails

- Confirm Android is signed into cloud and paired.
- Confirm migration `002_hardening.sql` is applied.
- Deploy `create-stream` and the signaling server behind WSS.
- Install Windows `requirements-webrtc.txt`.
- Configure a valid Windows UUID and owner access token.
- Inspect `stream_sessions`, `remote_commands`, signaling JSON logs, Windows `webrtc` logs, and Android `WebRTC` logs.
- If direct media fails, verify TURN URLs/shared-secret/firewall ports.

## Voice fails

Check microphone permission, 30-second/5 MB bounds, active Windows device, `voice_messages`, `remote_commands`, receipts, logs, and emergency state.

## Emergency disable will not clear remotely

Intentional. Use the local Windows control.
