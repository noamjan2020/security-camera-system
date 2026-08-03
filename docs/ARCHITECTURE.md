# Architecture

## Windows agent

- OpenCV capture thread
- capacity-one latest-frame queue
- adaptive inference thread
- optional YOLO ONNX detector
- optional YuNet/SFace local whitelist
- SQLite/WAL event store, nonces, receipts, pairings, upload queue
- FastAPI local authenticated API
- Supabase upload and command workers
- safe Windows audio playback and volume restoration
- optional lazy-loaded aiortc publisher
- tray/control desktop application

## Android app

- Kotlin/Jetpack Compose UI
- Android Keystore encrypted preferences
- Retrofit/OkHttp local client
- Supabase Auth/REST/Storage client
- FCM receiver and deep links
- AudioRecord WAV recorder
- cached protected event media
- system-WebView WebRTC receiver using an origin-scoped native message bridge

## Cloud

- Supabase Auth, PostgreSQL, RLS, private Storage
- notification, pairing, and stream-creation Edge Functions
- Firebase Cloud Messaging HTTP v1
- authenticated WSS signaling
- optional coturn-compatible ephemeral credentials

## Low-latency local path

```text
Camera -> capture thread -> latest-frame queue (1) -> inference thread
              |                                      |
              +-> latest preview                     +-> zones
                                                       -> visibility gate
                                                       -> best frame
                                                       -> local face decision
                                                       -> SQLite event
                                                       -> durable cloud queue
```

Stale frames are deliberately dropped. The system needs the newest view, not a delayed backlog.

## Remote alert path

```text
Windows -> private Storage -> owner-scoped event row -> Edge Function -> FCM -> Android
Android -> authenticated media fetch -> encrypted app-private cache
```

## Remote Live View

```text
Android -> create-stream Edge Function -> short-lived stream row + TURN credentials
                                     -> start_stream command
Windows outbound poll -> validates command -> lazy-loads aiortc -> WSS signaling
Android origin-locked WebView <- native OkHttp signaling bridge <- WSS
Windows camera -> WebRTC SRTP media -> direct path or TURN relay -> Android video
```

Signaling joins include the exact session device ID and role. One publisher and one viewer are allowed.

## Remote voice path

```text
Android explicit recording -> private voice bucket -> expiring command
Windows outbound poll -> owner/device/nonce/expiry/WAV checks
-> save volume -> play -> restore volume -> receipt -> delete temporary media
```

## Trust boundaries

1. Continuous frames and face embeddings stay on Windows.
2. Only event screenshots and user-recorded voice messages are uploaded.
3. RLS scopes rows/media to the authenticated owner.
4. Pairing credentials are unique and revocable.
5. Stream sessions are temporary and device-bound.
6. Emergency disable is local, persistent, and cannot be cleared remotely.
