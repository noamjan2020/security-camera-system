$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Agent = Join-Path $Root "windows-agent"
Set-Location $Agent
$Python = if (Test-Path .\.venv\Scripts\python.exe) { ".\.venv\Scripts\python.exe" } else { "py" }
if ($Python -eq "py") {
    py -3.12 -c "from pathlib import Path; from homeguard_agent.model_install import install_face_models; install_face_models(Path('models'))"
} else {
    & $Python -c "from pathlib import Path; from homeguard_agent.model_install import install_face_models; install_face_models(Path('models'))"
}
Write-Host "Face models installed in windows-agent\models"
