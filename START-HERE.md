# Start here

**For exact build, installation, and physical test steps, read [`TESTING-GUIDE.md`](TESTING-GUIDE.md). Use [`TEST-REPORT-TEMPLATE.md`](TEST-REPORT-TEMPLATE.md) while testing.**

## 1. Run the Windows agent

Open PowerShell in the workspace root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\first-setup.ps1 -WithOnnx -WithWebRtc
.\scripts\download-models.ps1
.\scripts\dev-run.ps1
```

Use `-WithOnnx` for the faster/more accurate optional person detector and `-WithWebRtc` for remote Live View. Without them, the agent remains lighter and local monitoring still works.

The desktop app remains in the system tray. Generate a temporary QR code under **Pair phone**, then scan it in the Android app. Pairing codes expire and can be claimed once.

## 2. Configure detection

Edit `windows-agent\.env`:

```env
HOMEGUARD_CAMERA_INDEX=0
HOMEGUARD_MAX_FPS=12
HOMEGUARD_INFERENCE_FPS=4
HOMEGUARD_VISIBLE_SECONDS=1.5
HOMEGUARD_COOLDOWN_SECONDS=60
```

For a weak PC, use 960×540, 8 capture FPS, 2 inference FPS, and inference size 416.

## 3. Build installable files

Windows portable app and Inno Setup installer:

```powershell
.\scripts\build-windows.ps1 -WithOnnx -WithWebRtc
```

Android debug APK:

```powershell
.\scripts\build-android.ps1
```

Signed Android release APK:

```powershell
$env:HOMEGUARD_ANDROID_KEYSTORE_PATH="C:\secure\homeguard.jks"
$env:HOMEGUARD_ANDROID_KEYSTORE_PASSWORD="..."
$env:HOMEGUARD_ANDROID_KEY_ALIAS="homeguard"
$env:HOMEGUARD_ANDROID_KEY_PASSWORD="..."
.\scripts\build-android.ps1 -Release
```

## 4. Enable remote operation

1. Create a Supabase project.
2. Apply every SQL migration in numeric order.
3. Deploy `notify-event`, `pair-device`, and `create-stream`.
4. Deploy the signaling service behind WSS.
5. Configure STUN/TURN; set `TURN_SHARED_SECRET` only in backend secrets.
6. Create the Firebase Android app and add `google-services.json` only at build time.
7. Configure the Windows agent’s public Supabase values and owner session in `.env`.
8. Build the Android app with the public Supabase URL and anon key.

## 5. Debug logs

Windows:

```text
%LOCALAPPDATA%\HomeGuard\logs\homeguard.log
%LOCALAPPDATA%\HomeGuard\logs\homeguard.jsonl
```

Android app-private storage:

```text
files/logs/homeguard.log
files/logs/homeguard.jsonl
```

Logs rotate automatically and include request/session/command IDs. Passwords, bearer tokens, audio contents, and authorization headers are not intentionally logged.
