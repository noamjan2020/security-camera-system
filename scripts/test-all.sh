#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

cleanup_python_artifacts() {
  find "$ROOT" -type d \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.mypy_cache' -o -name '.ruff_cache' \) -prune -exec rm -rf {} + 2>/dev/null || true
  find "$ROOT" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete 2>/dev/null || true
}

cleanup_python_artifacts
trap cleanup_python_artifacts EXIT

printf '\n[1/8] Static workspace checks\n'
python scripts/static_checks.py
printf '\n[2/8] Python compile\n'
python -m compileall -q windows-agent/src windows-agent/tests
printf '\n[3/8] Windows-agent tests\n'
(cd windows-agent && python -m pytest -q)
printf '\n[4/8] Signaling tests\n'
(cd backend/signaling-server && node --test tests.mjs)
printf '\n[5/8] Android pure Kotlin security checks\n'
bash scripts/test-android-pure.sh
printf '\n[6/8] TypeScript syntax checks\n'
node scripts/check-typescript-syntax.mjs
printf '\n[7/8] Signaling TypeScript build (when dependencies exist)\n'
if [ -d backend/signaling-server/node_modules ]; then
  (cd backend/signaling-server && npm run build)
else
  echo 'SKIP: node_modules is unavailable.'
fi
printf '\n[8/8] Android Gradle tests (when Gradle/SDK exist)\n'
if [ -x android-app/gradlew ]; then
  (cd android-app && ./gradlew testDebugUnitTest lintDebug assembleDebug)
elif command -v gradle >/dev/null 2>&1 && [ -n "${ANDROID_HOME:-}" ]; then
  (cd android-app && gradle testDebugUnitTest lintDebug assembleDebug)
else
  echo 'SKIP: Android SDK/Gradle is unavailable.'
fi
