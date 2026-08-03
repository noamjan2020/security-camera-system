from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []
checks = 0


def check(condition: bool, message: str) -> None:
    global checks
    checks += 1
    if not condition:
        errors.append(message)


# XML resources and manifest must be well formed.
for path in sorted((ROOT / "android-app").rglob("*.xml")):
    try:
        ET.parse(path)
        check(True, str(path))
    except ET.ParseError as exc:
        check(False, f"Malformed XML {path.relative_to(ROOT)}: {exc}")

# JSON configuration must parse.
for path in sorted(ROOT.rglob("*.json")):
    if any(part in {".gradle", "build", "dist", "node_modules"} for part in path.parts):
        continue
    try:
        json.loads(path.read_text(encoding="utf-8"))
        check(True, str(path))
    except Exception as exc:
        check(False, f"Malformed JSON {path.relative_to(ROOT)}: {exc}")

# SQL migrations must have explicit transactions and unique numeric ordering.
migrations = sorted((ROOT / "backend/supabase/migrations").glob("*.sql"))
check(bool(migrations), "No Supabase migrations found")
prefixes = [path.name.split("_", 1)[0] for path in migrations]
check(len(prefixes) == len(set(prefixes)), "Duplicate migration prefixes")
for path in migrations:
    text = path.read_text(encoding="utf-8").strip().lower()
    check(text.startswith("begin;"), f"Migration does not start with begin: {path.name}")
    check(text.endswith("commit;"), f"Migration does not end with commit: {path.name}")

# Version values should stay aligned.
pyproject = (ROOT / "windows-agent/pyproject.toml").read_text(encoding="utf-8")
runtime = (ROOT / "windows-agent/src/homeguard_agent/runtime.py").read_text(encoding="utf-8")
gradle = (ROOT / "android-app/app/build.gradle.kts").read_text(encoding="utf-8")
installer = (ROOT / "windows-agent/installer.iss").read_text(encoding="utf-8")
api_source = (ROOT / "windows-agent/src/homeguard_agent/api.py").read_text(encoding="utf-8")
signaling_source = (ROOT / "backend/signaling-server/src/server.ts").read_text(encoding="utf-8")
signaling_package = json.loads((ROOT / "backend/signaling-server/package.json").read_text(encoding="utf-8"))
versions = {
    "pyproject": re.search(r'version\s*=\s*"([^"]+)"', pyproject),
    "runtime": re.search(r'VERSION\s*=\s*"([^"]+)"', runtime),
    "api": re.search(r'version:\s*str\s*=\s*"([^"]+)"', api_source),
    "android": re.search(r'versionName\s*=\s*"([^"]+)"', gradle),
    "installer": re.search(r'MyAppVersion\s+"([^"]+)"', installer),
    "signaling_health": re.search(r'version:\s*"([^"]+)"', signaling_source),
}
check(signaling_package.get("version") == "0.4.0", "Signaling package version is not 0.4.0")
check(all(match for match in versions.values()), "Unable to read all version declarations")
if all(match for match in versions.values()):
    values = {name: match.group(1) for name, match in versions.items() if match}
    check(len(set(values.values())) == 1, f"Version mismatch: {values}")

# Release hygiene: no caches, local DBs or known credential formats.
for path in ROOT.rglob("*"):
    if path.is_dir() and path.name in {"__pycache__", ".pytest_cache"}:
        errors.append(f"Generated cache directory present: {path.relative_to(ROOT)}")
    if path.is_file() and path.suffix in {".pyc", ".db", ".jks", ".keystore"}:
        errors.append(f"Generated/sensitive file present: {path.relative_to(ROOT)}")

secret_patterns = {
    "OpenAI key": re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    "PEM private key": re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----\s+[A-Za-z0-9+/]{20,}"),
    "Supabase service JWT": re.compile(r"eyJ[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}"),
}
for path in ROOT.rglob("*"):
    if not path.is_file() or any(part in {".git", "build", "dist", "node_modules", ".gradle"} for part in path.parts):
        continue
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".zip", ".jar", ".onnx", ".pyc"}:
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    for name, pattern in secret_patterns.items():
        check(not pattern.search(text), f"Possible {name} in {path.relative_to(ROOT)}")

# Android cleartext is intentionally limited in code to private numeric LAN hosts.
models = (ROOT / "android-app/app/src/main/java/com/noamjan/homeguard/data/Models.kt").read_text()
check("isPrivateLanHost" in models, "Private-LAN URL validator is missing")
check("Unencrypted HTTP is allowed only for a private LAN address" in models, "Public HTTP rejection is missing")



# Remote Live View must remain origin-locked, authenticated and device-bound.
webview = (ROOT / "android-app/app/src/main/java/com/noamjan/homeguard/ui/WebRtcLiveView.kt").read_text(encoding="utf-8")
live_html = (ROOT / "android-app/app/src/main/assets/live_view.html").read_text(encoding="utf-8")
windows_webrtc = (ROOT / "windows-agent/src/homeguard_agent/webrtc.py").read_text(encoding="utf-8")
create_stream = (ROOT / "backend/supabase/functions/create-stream/index.ts").read_text(encoding="utf-8")
signaling = (ROOT / "backend/signaling-server/src/server.ts").read_text(encoding="utf-8")
windows_build = (ROOT / "scripts/build-windows.ps1").read_text(encoding="utf-8")
workflow = (ROOT / ".github/workflows/build-artifacts.yml").read_text(encoding="utf-8")
for condition, message in [
    ("addWebMessageListener" in webview, "Android Live View lacks origin-scoped WebMessage listener"),
    ("addJavascriptInterface" not in webview, "Android Live View uses unsafe addJavascriptInterface"),
    ("allowFileAccess = false" in webview and "allowContentAccess = false" in webview, "Android Live View file/content access is not disabled"),
    ("MIXED_CONTENT_NEVER_ALLOW" in webview, "Android Live View allows mixed content"),
    ("Authorization" in webview and "Bearer" in webview, "Android signaling bearer authentication is missing"),
    ("viewerDeviceId" in webview, "Android signaling join is not bound to the paired device"),
    ("connect-src 'none'" in live_html, "Bundled Live View page can create its own network connections"),
    ("deviceId" in windows_webrtc and '"role": "publisher"' in windows_webrtc, "Windows signaling join is not device-bound"),
    ("camera_device_id" in create_stream and "viewer_device_id" in create_stream, "Stream command lacks device binding"),
    ("JoinPayload" in signaling and "expectedDeviceId" in signaling, "Signaling server does not enforce session device identity"),
    ("WithWebRtc" in windows_build, "Windows build script does not support WebRTC dependencies"),
    ("-WithWebRtc" in workflow, "CI Windows build omits WebRTC dependencies"),
    (create_stream.find("const now = Date.now()") < create_stream.find('.gt("last_seen_at"'), "create-stream uses heartbeat time before declaration"),
    ("register_windows_device" in (ROOT / "windows-agent/src/homeguard_agent/cloud.py").read_text(encoding="utf-8"), "Windows cloud heartbeat is missing"),
    ("upsertAndroidDevice" in (ROOT / "android-app/app/src/main/java/com/noamjan/homeguard/data/CloudClient.kt").read_text(encoding="utf-8"), "Android cloud device heartbeat is missing"),
]:
    check(condition, message)


if errors:
    print("STATIC CHECKS FAILED")
    for error in errors:
        print(f"- {error}")
    sys.exit(1)
print(f"Static checks passed: {checks}")
