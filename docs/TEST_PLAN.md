# Test plan

## Automated locally in this workspace

### Windows/Python

- database migration/WAL/integrity/retention
- durable upload retries
- token protection, expiration, nonce replay
- one-time pairing and revocation
- persistent privacy/emergency state
- API auth, request IDs, health diagnostics
- audio bounds, command windows, stop, receipts, volume restoration
- remote audio expiry/replay/emergency flows
- detector preprocessing, adaptive latest-frame queue
- detection/exclusion zones
- encrypted/protected face whitelist behavior
- log rotation
- cloud event/push/command paths
- secure WebRTC request parsing and command start/stop behavior

### Signaling/Node

- rate limiting
- two-peer room cap and cleanup
- duplicate role rejection

### Android pure Kotlin

- private-LAN URL policy
- WSS-only signaling URL policy
- userinfo/invalid scheme rejection
- pairing URI parsing

### Static/security

- XML/JSON/SQL validity
- version consistency
- cache/secret hygiene
- origin-locked WebView bridge
- no `addJavascriptInterface`
- mixed-content/file access disabled
- device-bound stream joins
- optional WebRTC inclusion in CI/package scripts

## CI-only until toolchains are available

- full Android Kotlin/Compose compile
- Android unit tests/lint/APK
- TypeScript build with installed dependencies
- Deno Edge Function type-check
- PyInstaller and Inno Setup packaging

## Physical acceptance before v1.0

- multiple webcams and weak/midrange PCs
- Android 8 through current supported versions
- FCM while locked/backgrounded
- Wi-Fi/mobile data/offline recovery
- second-account RLS attacks
- token/device revocation
- WSS/TURN WebRTC on restrictive networks
- speaker changes and volume restoration
- camera unplug/use by another app
- whitelisted/unknown/obscured/similar faces
- installer upgrade/uninstall/startup
- 24-hour CPU/memory/disk soak
