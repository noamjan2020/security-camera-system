$Root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $Root "windows-agent")
if (-not (Test-Path .venv)) { py -3.12 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m homeguard_agent.cli run
