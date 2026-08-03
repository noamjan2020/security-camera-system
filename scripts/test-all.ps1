$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Remove-PythonArtifacts {
    Get-ChildItem -Path $Root -Directory -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache") } |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Path $Root -File -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

Remove-PythonArtifacts
try {
    Write-Host "[1/8] Static workspace checks"
    py -3.12 scripts\static_checks.py
    Write-Host "[2/8] Python compile"
    py -3.12 -m compileall -q windows-agent\src windows-agent\tests
    Write-Host "[3/8] Windows-agent tests"
    Push-Location windows-agent
    try { py -3.12 -m pytest -q } finally { Pop-Location }
    Write-Host "[4/8] Signaling tests"
    Push-Location backend\signaling-server
    try { node --test tests.mjs } finally { Pop-Location }
    Write-Host "[5/8] Android pure Kotlin checks"
    if ((Get-Command bash -ErrorAction SilentlyContinue) -and (Get-Command kotlinc -ErrorAction SilentlyContinue)) {
        bash scripts/test-android-pure.sh
    } else {
        Write-Warning "SKIP: Git Bash/WSL and Kotlin CLI are required for the pure Kotlin check. CI always runs it."
    }
    Write-Host "[6/8] TypeScript syntax checks"
    node scripts\check-typescript-syntax.mjs
    Write-Host "[7/8] Signaling TypeScript build"
    Push-Location backend\signaling-server
    try {
        if (Test-Path node_modules) { npm run build } else { Write-Warning "SKIP: run npm install first." }
    } finally { Pop-Location }
    Write-Host "[8/8] Android tests/build"
    Push-Location android-app
    try {
        if (Test-Path .\gradlew.bat) { .\gradlew.bat testDebugUnitTest lintDebug assembleDebug }
        elseif ((Get-Command gradle -ErrorAction SilentlyContinue) -and $env:ANDROID_HOME) { gradle testDebugUnitTest lintDebug assembleDebug }
        else { Write-Warning "SKIP: Android SDK/Gradle unavailable." }
    } finally { Pop-Location }
} finally {
    Remove-PythonArtifacts
}
