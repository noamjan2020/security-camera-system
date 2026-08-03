# Build guide

## Windows

Requirements:

- Windows 11 x64
- Python 3.12 x64
- Inno Setup 6 for installer output
- optional ONNX model/runtime
- optional aiortc/WebSocket packages for remote Live View

```powershell
.\scripts\build-windows.ps1 -WithOnnx -WithWebRtc
```

The script compiles Python, runs all Windows tests, builds the portable folder, optionally builds `HomeGuard-Setup.exe`, and writes SHA-256 hashes.

## Android

Requirements:

- JDK 17
- Android SDK platform 37
- Android Build Tools 36.0.0
- Gradle 9.5.0 or compatible Android Studio
- `google-services.json` for real FCM
- release keystore environment variables for a signed release

Build-time public cloud values:

```powershell
$env:HOMEGUARD_SUPABASE_URL="https://PROJECT.supabase.co"
$env:HOMEGUARD_SUPABASE_ANON_KEY="PUBLIC_ANON_KEY"
```

Debug:

```powershell
.\scripts\build-android.ps1
```

Signed release:

```powershell
.\scripts\build-android.ps1 -Release
```

## CI

`.github/workflows/build-artifacts.yml` runs static/security checks, Python tests, signaling tests/build, Deno Edge Function checks, Android tests/lint/APK, and Windows EXE/installer packaging on platform-native runners.
