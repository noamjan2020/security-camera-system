param(
    [switch]$WithOnnx,
    [switch]$WithWebRtc
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Agent = Join-Path $Root "windows-agent"
Set-Location $Agent

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python 3.12 is required. Install it from python.org, then rerun this script."
}
if (-not (Test-Path .venv)) { py -3.12 -m venv .venv }
$Python = ".\.venv\Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt
if ($WithOnnx) { & $Python -m pip install -r requirements-onnx.txt }
if ($WithWebRtc) { & $Python -m pip install -r requirements-webrtc.txt }
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
& $Python -m compileall -q src tests
& $Python -m pytest -q
& $Python -m homeguard_agent.cli init
Write-Host "Setup complete. Run scripts\dev-run.ps1 from the workspace root."
