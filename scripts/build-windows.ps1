param(
    [switch]$WithOnnx,
    [switch]$WithWebRtc,
    [switch]$SkipInstaller
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Agent = Join-Path $Root "windows-agent"
$Dist = Join-Path $Root "dist"
Set-Location $Agent

if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw "Python launcher not found. Install Python 3.12 x64." }
if (-not (Test-Path .venv)) { py -3.12 -m venv .venv }
$Python = Join-Path $Agent ".venv\Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements-dev.txt
if ($WithOnnx) { & $Python -m pip install -r requirements-onnx.txt }
if ($WithWebRtc) { & $Python -m pip install -r requirements-webrtc.txt }
& $Python -m compileall -q src tests
& $Python -m pytest -q
& $Python -m PyInstaller --clean --noconfirm HomeGuardAgent.spec

New-Item -ItemType Directory -Force $Dist | Out-Null
Remove-Item (Join-Path $Dist "HomeGuardAgent") -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item -Recurse -Force .\dist\HomeGuardAgent $Dist

if (-not $SkipInstaller) {
    $Iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($Iscc) {
        & $Iscc.Source .\installer.iss
        if (-not (Test-Path (Join-Path $Dist "HomeGuard-Setup.exe"))) { throw "Installer build did not produce HomeGuard-Setup.exe" }
    } else {
        Write-Warning "Inno Setup is not installed; portable EXE built, installer skipped. Install: winget install JRSoftware.InnoSetup"
    }
}

Get-ChildItem $Dist -Recurse -File | Get-FileHash -Algorithm SHA256 |
    ForEach-Object { "{0}  {1}" -f $_.Hash.ToLowerInvariant(), $_.Path.Substring($Root.Length + 1).Replace('\\','/') } |
    Set-Content (Join-Path $Dist "SHA256SUMS-Windows.txt")
Write-Host "Windows artifacts are in $Dist"
