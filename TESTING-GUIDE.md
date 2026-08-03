# HomeGuard 0.4 — exact build and testing guide

This guide covers the workspace, Windows agent, installer, Android APK, local pairing, cloud alerts, remote voice, WebRTC Live View, security, performance, logs, and failure recovery.

## What you need

### Required for basic local testing

- A Windows 11 x64 PC with a webcam and speakers.
- An Android phone running Android 8 or newer.
- PC and phone connected to the same private Wi-Fi network.
- Python 3.12 x64.
- PowerShell.
- About 4 GB free disk space for dependencies and builds.

### Required to build the Windows packages

- Inno Setup 6 for `HomeGuard-Setup.exe`.
- Optional ONNX dependencies for improved detection.
- Optional WebRTC dependencies for remote Live View.

### Required to build the Android APK locally

- JDK 17.
- Android Studio or Android SDK command-line tools.
- Android SDK platform 37.
- Android Build Tools 36.0.0.
- Gradle 9.5.0 when not building through Android Studio.
- Android Platform Tools (`adb`) for USB installation and log collection.

### Required for full remote testing

- A Supabase project.
- A Firebase Android project for `com.noamjan.homeguard`.
- A deployed WSS signaling server.
- A TURN server.
- A real email account for Supabase authentication.
- Mobile data on the Android phone.

---

# Part 1 — fastest way to obtain the APK and EXE

The easiest reliable path is the included GitHub Actions workflow because it builds Windows and Android on the correct operating systems.

## 1. Create a private GitHub repository

1. Extract the test-kit ZIP.
2. Open `security-camera-system`.
3. Create an empty **private** GitHub repository named `homeguard`.
4. Do not initialize it with a README or `.gitignore`.
5. Open PowerShell inside `security-camera-system` and run:

```powershell
git init
git add .
git commit -m "HomeGuard 0.4 test build"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/homeguard.git
git push -u origin main
```

If Git asks you to sign in, complete the browser sign-in.

## 2. Run the build workflow

1. Open the repository on GitHub.
2. Open **Actions**.
3. Select **Test and build HomeGuard**.
4. Select **Run workflow**.
5. Wait until the `quality`, `windows`, `signaling`, `supabase-functions`, and `android` jobs finish.
6. A green check means the workflow passed. A red X means you must open the failed job and save its complete log.

## 3. Download the build artifacts

At the bottom of the completed workflow run, download:

- `HomeGuard-Windows`
- `HomeGuard-Android-APK`

Expected files:

```text
dist/HomeGuardAgent/HomeGuardAgent.exe
dist/HomeGuard-Setup.exe
dist/SHA256SUMS-Windows.txt
app-debug.apk
```

Rename `app-debug.apk` to `HomeGuard-debug.apk` if desired.

## 4. Cloud-enabled CI build

The debug APK can build without cloud secrets, but FCM and cloud history will not work. For cloud testing, add these repository secrets under **Settings → Secrets and variables → Actions**:

```text
HOMEGUARD_SUPABASE_URL
HOMEGUARD_SUPABASE_ANON_KEY
HOMEGUARD_GOOGLE_SERVICES_JSON_B64
```

Create the Firebase JSON Base64 value in PowerShell:

```powershell
[Convert]::ToBase64String(
    [IO.File]::ReadAllBytes("C:\path\to\google-services.json")
) | Set-Clipboard
```

Paste the clipboard value into `HOMEGUARD_GOOGLE_SERVICES_JSON_B64`, then run the workflow again.

---

# Part 2 — test the workspace before packaging

Open PowerShell as a normal user inside `security-camera-system`.

## 1. Check prerequisites

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\check-test-prerequisites.ps1
```

Fix every item marked `MISSING` that belongs to the build you want to run.

## 2. Run all source-level checks

```powershell
.\scripts\test-all.ps1
```

Expected minimum results:

```text
Static checks: PASS
Windows tests: 44 passed
Signaling tests: 3 passed
Android pure Kotlin security checks: PASS
TypeScript syntax checks: PASS
```

The Android Gradle stage may be skipped unless the Android SDK and Gradle are installed.

## 3. Run the Windows diagnostic command

```powershell
cd windows-agent
.\.venv\Scripts\python.exe -m homeguard_agent.cli doctor
cd ..
```

Expected:

- Database integrity: `OK`
- Detector is listed.
- Emergency status is shown.
- No traceback.

---

# Part 3 — run the Windows agent from source

Use this before testing the EXE. It gives the clearest logs when something breaks.

## 1. Install and initialize

From the workspace root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\first-setup.ps1 -WithOnnx -WithWebRtc
.\scripts\download-models.ps1
```

If you want the lightest possible first run, omit both switches:

```powershell
.\scripts\first-setup.ps1
```

## 2. Enable verbose logs

Edit `windows-agent\.env` and set:

```env
HOMEGUARD_DEBUG=true
HOMEGUARD_CAMERA_INDEX=0
HOMEGUARD_MAX_FPS=12
HOMEGUARD_INFERENCE_FPS=4
HOMEGUARD_VISIBLE_SECONDS=1.5
HOMEGUARD_COOLDOWN_SECONDS=60
HOMEGUARD_REMOTE_ENABLED=false
```

For a weak PC, use:

```env
HOMEGUARD_CAMERA_WIDTH=960
HOMEGUARD_CAMERA_HEIGHT=540
HOMEGUARD_MAX_FPS=8
HOMEGUARD_INFERENCE_FPS=2
HOMEGUARD_INFERENCE_SIZE=416
```

## 3. Allow local phone access through Windows Firewall

Run PowerShell as Administrator once:

```powershell
New-NetFirewallRule `
  -DisplayName "HomeGuard Local API" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 8765 `
  -Action Allow `
  -Profile Private
```

Do not allow this rule on the Public profile. Never port-forward TCP 8765 on your router.

## 4. Start the agent

```powershell
.\scripts\dev-run.ps1
```

Expected:

- HomeGuard window opens.
- Camera changes to active.
- Capture FPS and AI FPS become greater than zero.
- A tray icon appears.
- Closing the window hides it instead of stopping the agent.
- `http://127.0.0.1:8765/docs` opens locally.

If the camera does not open, close Zoom, Discord, OBS, Camera, or any app using the webcam, then retry.

---

# Part 4 — install and test the Windows EXE and installer

## Portable EXE test

1. Extract `HomeGuard-Windows`.
2. Open `HomeGuardAgent`.
3. Run `HomeGuardAgent.exe`.
4. If Windows SmartScreen appears, confirm the file hash first and select **More info → Run anyway** only for your own build.
5. Confirm the same startup behavior as the source version.

## Installer test

1. Run `HomeGuard-Setup.exe`.
2. Choose whether to start HomeGuard with Windows.
3. Finish installation and launch it.
4. Confirm it appears under Windows installed apps.
5. Restart Windows.
6. Confirm startup works only when selected.
7. Uninstall it.
8. Confirm program files are removed.
9. Confirm personal event data under `%LOCALAPPDATA%\HomeGuard` is not silently deleted unless the uninstaller explicitly says it will be.

## Verify artifacts

From the workspace root, place the downloaded files in `dist`, then run:

```powershell
.\scripts\verify-artifacts.ps1
```

Expected:

- EXE exists.
- Installer exists if Inno Setup was used.
- APK exists.
- SHA-256 hashes are printed.
- No hash mismatch is reported.

---

# Part 5 — install the Android APK

## Phone preparation

1. Open Android Settings.
2. Enable Developer Options.
3. Enable USB debugging.
4. Connect the phone using USB.
5. Accept the RSA debugging prompt on the phone.

## Install using the helper

Put `HomeGuard-debug.apk` or `app-debug.apk` inside `dist`, then run:

```powershell
.\scripts\install-apk.ps1
```

Manual alternative:

```powershell
adb devices
adb install -r .\dist\HomeGuard-debug.apk
adb shell monkey -p com.noamjan.homeguard.debug 1
```

Expected:

- `adb devices` shows one device as `device`, not `unauthorized`.
- Installation reports `Success`.
- The HomeGuard app opens.
- The app does not request microphone permission during normal startup.

For a release APK, the package is `com.noamjan.homeguard`, without `.debug`.

---

# Part 6 — pair the phone locally

1. Put the PC and Android phone on the same private Wi-Fi.
2. Disable any phone VPN for the first local pairing test.
3. Open HomeGuard on Windows.
4. Open **Pair phone**.
5. Select **Generate new QR**.
6. Open HomeGuard on Android.
7. Scan the QR code.
8. Confirm the Android app shows the Windows camera dashboard.
9. Try scanning the same QR again.
10. Wait more than two minutes, generate a code, and try using the expired code.

Expected:

- First claim succeeds once.
- Reusing the same code fails.
- Expired code fails.
- Android stores its own credential.
- No permanent token is shown on screen.
- Windows lists the paired phone.

## Revocation test

1. On Windows, select the paired phone.
2. Choose **Revoke selected phone**.
3. Refresh the Android app.

Expected:

- The revoked phone can no longer read events, snapshots, logs, or send audio.
- Pairing again with a fresh QR restores access.

---

# Part 7 — local functional test checklist

Record every result in `TEST-REPORT-TEMPLATE.md`.

## A. Startup and camera

### HG-001 — clean startup

1. Start HomeGuard.
2. Wait 20 seconds.

Pass when:

- No crash or traceback.
- Camera status becomes active.
- Capture FPS is stable.
- Logs show startup, detector selection, and camera open.

### HG-002 — single instance

1. Start HomeGuard.
2. Try starting a second copy.

Pass when the second copy does not create another camera process.

### HG-003 — camera disconnect recovery

1. Unplug the USB webcam while running.
2. Wait 15 seconds.
3. Reconnect it.

Pass when:

- A readable camera error is shown/logged.
- The process stays alive.
- The camera reconnects automatically.

### HG-004 — webcam already in use

1. Close HomeGuard.
2. Open another camera application.
3. Start HomeGuard.
4. Close the other camera application.

Pass when HomeGuard reports the conflict and later recovers without restart.

## B. Person detection

### HG-010 — unknown person alert event

1. Ensure whitelist is empty or disabled.
2. Leave the camera view.
3. Walk into view for at least two seconds.

Pass when:

- Exactly one event is created.
- The screenshot clearly contains the person.
- Detection time and confidence are stored.
- No duplicate event appears during the cooldown.

### HG-011 — short appearance ignored

1. Move briefly through the edge of the frame for less than the configured visible time.

Pass when no event is created.

### HG-012 — continuous-person cooldown

1. Remain visible for two minutes.

Pass when notifications/events respect the configured cooldown and do not spam continuously.

### HG-013 — multiple people

1. Have two people enter the frame.

Pass when the system remains stable and creates a sensible event without duplicate storms.

### HG-014 — pet and object false-positive check

1. Move a pet, chair, bag, or large object through the frame.

Pass when no person alert is created. Record failures; do not hide them.

### HG-015 — low light

1. Repeat the person test in dim lighting.

Pass when behavior remains usable. Record missed detections and false alerts.

## C. Detection zones

### HG-020 — detection zone

1. Set a detection zone covering only half of the image.
2. Enter outside that zone.
3. Enter inside that zone.

Pass when outside movement is ignored and inside movement is detected.

### HG-021 — exclusion zone

1. Configure an exclusion zone around a doorway, TV, or reflective surface.
2. Move only inside the exclusion zone.

Pass when excluded movement does not create an event.

## D. Face whitelist

Face models must be installed first.

### HG-030 — enroll a clear face

1. Stand centered in good light.
2. Open **Whitelist** on Windows.
3. Enroll the same person three times from slightly different angles.
4. Use **Test current face**.

Pass when the person is matched consistently.

### HG-031 — whitelisted person suppression

1. Leave the frame.
2. Re-enter as the enrolled person.

Pass when the local event behavior matches settings and no unknown alert is sent.

### HG-032 — unknown person

1. Have a different person enter.

Pass when they are treated as unknown.

### HG-033 — unclear or hidden face

1. Enter with face turned away, covered, blurred, or too far away.

Pass when the person is treated as unknown, not whitelisted.

### HG-034 — similar-looking person

1. Test a sibling or similar-looking person.

Pass only when they are not incorrectly accepted as the enrolled person.

### HG-035 — remove whitelist entry

1. Delete the enrolled person.
2. Enter again.

Pass when the person is now treated as unknown.

## E. Events and retention

### HG-040 — Android event timeline

1. Create three events.
2. Open the Android Events tab.

Pass when:

- Events are ordered newest first.
- Thumbnails load.
- Unknown/whitelisted state is correct.
- Viewed/unviewed status changes correctly.

### HG-041 — event detail

1. Open an event.

Pass when the full image, time, confidence, camera name, and recognition result are visible.

### HG-042 — delete event

1. Delete one event from Android.

Pass when it disappears and its media becomes inaccessible.

### HG-043 — retention cleanup

1. Temporarily set retention to 15 minutes.
2. Create an event.
3. Adjust its database timestamp only in a disposable test installation, or wait for expiry.
4. Let maintenance run.

Pass when expired database rows and screenshots are deleted.

## F. Privacy and emergency controls

### HG-050 — privacy pause

1. Pause from Windows or Android.
2. Walk in front of the camera.
3. Open Live View.

Pass when no new detection occurs and snapshot/Live View is unavailable.

### HG-051 — resume

1. Resume from Android while emergency disable is not active.

Pass when camera processing returns.

### HG-052 — persistent emergency disable

1. Press **EMERGENCY DISABLE** on Windows.
2. Try resuming from Android.
3. Restart HomeGuard.
4. Restart Windows.

Pass when:

- Remote resume fails.
- Camera, remote commands, and remote audio stay disabled.
- Emergency state survives both restarts.
- Only **Clear emergency locally** on the Windows PC can restore it.

## G. Talk to PC

### HG-060 — permission behavior

1. Open the Talk tab.
2. Do not press Record.

Pass when Android does not access or request the microphone.

### HG-061 — local voice playback

1. Press Record.
2. Grant microphone permission.
3. Record five seconds.
4. Stop and send.

Pass when:

- Upload progress/status changes.
- PC reports received, playing, and completed.
- Audio plays once.
- Temporary audio is deleted.

### HG-062 — volume restoration

1. Set the PC volume to a known low level.
2. Send audio at 100% playback volume.

Pass when playback uses the requested volume and restores the original level afterward.

### HG-063 — remote stop

1. Send a 20-second message.
2. Press **Stop PC audio** while it is playing.

Pass when playback stops and the previous volume is restored.

### HG-064 — audio limits

1. Attempt a message longer than 30 seconds.
2. Attempt an invalid or oversized WAV through the API in a disposable test environment.

Pass when both are rejected safely.

---

# Part 8 — full cloud and remote tests

Do this only after local testing passes.

## 1. Deploy Supabase

1. Create a Supabase project.
2. Apply these files in order:

```text
backend/supabase/migrations/001_init.sql
backend/supabase/migrations/002_hardening.sql
backend/supabase/migrations/003_remote_audio.sql
```

3. Verify all HomeGuard tables have RLS enabled.
4. Verify `event-media` and `voice-media` buckets are private.
5. Deploy:

```text
notify-event
pair-device
create-stream
```

6. Configure the Edge Function secrets listed in `docs/DEPLOYMENT.md`.

## 2. Configure Firebase

1. Create Android app ID `com.noamjan.homeguard`.
2. Download `google-services.json`.
3. Rebuild the APK with it.
4. Enable Android notification permission when the app asks.

## 3. Configure Windows remote mode

Edit the installed/source `.env` using normal owner credentials, never a service-role key:

```env
HOMEGUARD_REMOTE_ENABLED=true
HOMEGUARD_SUPABASE_URL=https://YOUR-PROJECT.supabase.co
HOMEGUARD_SUPABASE_ANON_KEY=YOUR_PUBLIC_ANON_KEY
HOMEGUARD_SUPABASE_ACCESS_TOKEN=YOUR_OWNER_ACCESS_TOKEN
HOMEGUARD_OWNER_ID=YOUR-OWNER-UUID
HOMEGUARD_DEVICE_ID=YOUR-WINDOWS-DEVICE-UUID
HOMEGUARD_CAMERA_ID=YOUR-CAMERA-UUID
HOMEGUARD_NOTIFY_FUNCTION_URL=https://YOUR-PROJECT.supabase.co/functions/v1/notify-event
```

Restart HomeGuard and check the cloud queue/status.

## H. Remote alert tests

### HG-100 — background FCM

1. Lock the Android phone.
2. Leave HomeGuard running.
3. Trigger an unknown-person event.

Pass when a high-priority notification arrives with camera name and time.

### HG-101 — notification deep link

1. Tap the notification.

Pass when the correct event opens, not merely the app home screen.

### HG-102 — mobile-data event access

1. Turn off phone Wi-Fi.
2. Use mobile data.
3. Open the event and screenshot.

Pass when cloud history and protected image access still work.

### HG-103 — PC internet outage queue

1. Disconnect PC internet.
2. Trigger two events.
3. Reconnect internet.

Pass when:

- Events remain locally available.
- Upload queue grows while offline.
- Queue drains automatically afterward.
- Cloud does not receive duplicate events.

### HG-104 — phone offline recovery

1. Put the phone in airplane mode.
2. Trigger an event.
3. Restore connectivity.

Pass when the event becomes visible and notification behavior is sensible without spam.

### HG-105 — second-account isolation

1. Create a second Supabase account.
2. Sign into that account on another phone or REST client.
3. Attempt to read the first account’s events/media/devices.

Pass only when every request is rejected or returns no rows.

## I. Remote Live View

### HG-110 — home Wi-Fi Live View

1. Open Live on Android while on home Wi-Fi.

Pass when video connects, remains stable, and closes when leaving the screen.

### HG-111 — mobile-data TURN test

1. Disable phone Wi-Fi.
2. Open Live View over mobile data.

Pass when the stream connects through the deployed infrastructure without router port forwarding.

### HG-112 — restrictive network

1. Test from another Wi-Fi network that blocks direct peer-to-peer traffic.

Pass when TURN fallback succeeds.

### HG-113 — session expiry

1. Keep Live View open longer than the configured maximum session.

Pass when the session expires and cleans itself up.

### HG-114 — privacy/emergency Live View denial

1. Activate privacy pause, then emergency disable.
2. Try Live View each time.

Pass when both deny video, and emergency disable remains local-only to clear.

### HG-115 — unauthorized room join

1. Use a revoked phone, second account, wrong device ID, or expired stream token.

Pass when signaling rejects the connection.

## J. Remote audio

### HG-120 — mobile-data voice playback

1. Disable phone Wi-Fi.
2. Record and send a short message.

Pass when the cloud command reaches the paired Windows device and receipts update.

### HG-121 — expired command

1. In a disposable test environment, delay a voice command beyond its expiration.

Pass when Windows rejects it and does not play the file.

### HG-122 — replay attack

1. Resubmit the same command ID/nonce.

Pass when the duplicate is rejected.

### HG-123 — revoked phone command

1. Revoke the phone.
2. Attempt another remote voice message.

Pass when it is rejected.

---

# Part 9 — reliability, performance, and soak tests

## HG-200 — 24-hour soak

Run HomeGuard for 24 hours with normal household activity.

Record at 0, 1, 4, 8, 12, and 24 hours:

- HomeGuard process RAM.
- CPU while idle.
- CPU during detection.
- Capture FPS.
- AI FPS.
- Event count.
- Cloud queue depth.
- Data-folder size.
- Log-folder size.

Pass targets:

- No crash.
- No continuously increasing memory usage.
- No unbounded storage growth.
- Queue returns to zero when online.
- Logs rotate.
- Camera reconnect remains functional.

## HG-201 — weak-PC profile

Use 960×540, 8 capture FPS, 2 AI FPS, inference size 416.

Pass when the PC remains responsive and alert timing is still acceptable.

## HG-202 — repeated app backgrounding

1. Open and close each Android screen repeatedly.
2. Put the app in the background 20 times.
3. Rotate the phone during Live View.

Pass when there are no crashes, stuck microphone sessions, or abandoned streams.

## HG-203 — storage pressure

1. In a disposable test profile, reduce available disk space.

Pass when HomeGuard logs a disk warning and does not corrupt its database.

---

# Part 10 — debug logs and bug reports

## Windows logs

```text
%LOCALAPPDATA%\HomeGuard\logs\homeguard.log
%LOCALAPPDATA%\HomeGuard\logs\homeguard.jsonl
```

## Android logs

App-private files:

```text
files/logs/homeguard.log
files/logs/homeguard.jsonl
```

For a debug APK, collect everything automatically:

```powershell
.\scripts\collect-debug-bundle.ps1
```

The output ZIP intentionally excludes API-token files, face embeddings, event media, voice recordings, and the event database. Review the ZIP before sharing it because device IDs, timestamps, camera names, and LAN addresses may still be sensitive.

## Every bug report must include

- Test ID, such as `HG-052`.
- Exact action performed.
- Expected result.
- Actual result.
- Windows version.
- Android model and version.
- Whether phone used Wi-Fi or mobile data.
- Time the failure occurred.
- Screenshot or screen recording.
- Debug bundle.
- Whether the bug reproduces after restart.

---

# Final release gate

Do not call HomeGuard v1.0 ready until all of these pass on real devices:

- Unknown person notification.
- Whitelisted person suppression.
- Unclear face treated as unknown.
- Background/lock-screen FCM.
- Cloud event and image access on mobile data.
- WebRTC with TURN outside the home network.
- Remote audio, stop, receipts, and volume restoration.
- Device revocation and second-account isolation.
- Persistent emergency disable.
- Camera/internet recovery.
- Installer upgrade, startup, and uninstall.
- 24-hour soak without memory/storage growth.

