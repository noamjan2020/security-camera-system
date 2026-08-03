# Completion checklist

## Implemented in source

- [x] split capture/inference pipeline with one-frame queue
- [x] adaptive inference and bounded memory/latency
- [x] HOG fallback and optional YOLO ONNX
- [x] visibility/cooldown/best-frame logic
- [x] detection and exclusion zones
- [x] SQLite/WAL events, retention, disk checks, durable upload queue
- [x] fail-closed local face whitelist
- [x] persistent local privacy and emergency controls
- [x] one-time QR pairing and per-phone revocation
- [x] authenticated API, replay protection, request IDs
- [x] five-section Compose Android UI
- [x] Android Keystore encrypted credentials
- [x] FCM receiver, deep links, protected screenshot previews
- [x] Supabase event/image fallback
- [x] cloud sign-in, sign-up, and password reset request
- [x] local/cloud Talk-to-PC flow
- [x] bounded WAV validation, stop, receipts, volume restoration
- [x] rotating Windows/Android structured debug logs
- [x] device-bound signaling with two-peer/role limits and rate limiting
- [x] optional Windows aiortc publisher
- [x] origin-locked Android WebView WebRTC viewer
- [x] short-lived stream/TURN session creation
- [x] Windows/Android build scripts and CI

## Still requires real platform/deployment verification

- [ ] Android Gradle compile, lint, unit tests, APK installation
- [ ] Windows PyInstaller/installer build and clean install/uninstall
- [ ] real camera detection on several webcams
- [ ] real FCM delivery while locked/backgrounded
- [ ] real Supabase RLS negative tests with a second account
- [ ] WSS signaling plus TURN over mobile data
- [ ] remote voice playback across the internet
- [ ] camera unplug/reconnect and long soak test
- [ ] installer upgrade/start-with-Windows test
- [ ] code signing and store publication

## Deferred product features

- [ ] biometric app unlock
- [ ] drag-to-draw Windows zone editor
- [ ] multi-camera runtime/UI
- [ ] automatic Windows cloud refresh-token enrollment
- [ ] Ogg Opus voice compression
