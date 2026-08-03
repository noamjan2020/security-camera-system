param([string]$OutputDirectory = "")
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$OutputDirectory = if ($OutputDirectory) { $OutputDirectory } else { $Root }
$Temp = Join-Path $env:TEMP "HomeGuard-Debug-$Timestamp"
$Zip = Join-Path $OutputDirectory "HomeGuard-Debug-Bundle-$Timestamp.zip"
New-Item -ItemType Directory -Force $Temp | Out-Null

function Save-Text([string]$Name, [scriptblock]$Command) {
    try { & $Command 2>&1 | Out-String | Set-Content (Join-Path $Temp $Name) -Encoding UTF8 }
    catch { $_ | Out-String | Set-Content (Join-Path $Temp $Name) -Encoding UTF8 }
}

function Copy-RedactedLog([string]$Source, [string]$TargetName) {
    if (-not (Test-Path $Source)) { return }
    $text = Get-Content $Source -Raw -ErrorAction SilentlyContinue
    if ($null -eq $text) { return }
    $patterns = @(
        '(?i)(Authorization\s*[:=]\s*Bearer\s+)[A-Za-z0-9._~+\-/=]+',
        '(?i)(access_token\s*[":= ]+)[A-Za-z0-9._~+\-/=]+',
        '(?i)(refresh_token\s*[":= ]+)[A-Za-z0-9._~+\-/=]+',
        '(?i)(apikey\s*[":= ]+)[A-Za-z0-9._~+\-/=]+',
        '(?i)(password\s*[":= ]+)\S+'
    )
    foreach ($pattern in $patterns) { $text = [regex]::Replace($text, $pattern, '$1<REDACTED>') }
    Set-Content (Join-Path $Temp $TargetName) $text -Encoding UTF8
}

Save-Text "system-info.txt" {
    Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, OsBuildNumber, OsArchitecture, CsProcessors, CsTotalPhysicalMemory
}
Save-Text "network.txt" { ipconfig /all }
Save-Text "camera-devices.txt" {
    if (Get-Command Get-PnpDevice -ErrorAction SilentlyContinue) {
        Get-PnpDevice -PresentOnly | Where-Object { $_.Class -in @("Camera", "Image", "AudioEndpoint") } |
            Select-Object Status, Class, FriendlyName, InstanceId
    }
}
Save-Text "processes.txt" {
    Get-Process | Where-Object { $_.ProcessName -match "HomeGuard|python|java|adb" } |
        Select-Object ProcessName, Id, CPU, WorkingSet64, StartTime
}
Save-Text "firewall-rule.txt" {
    Get-NetFirewallRule -DisplayName "HomeGuard Local API" -ErrorAction SilentlyContinue |
        Get-NetFirewallPortFilter
}
Save-Text "workspace-status.txt" {
    "Workspace: $Root"
    if (Test-Path (Join-Path $Root "TEST-RESULTS.txt")) { Get-Content (Join-Path $Root "TEST-RESULTS.txt") }
    if (Test-Path (Join-Path $Root "BUILD-STATUS.txt")) { Get-Content (Join-Path $Root "BUILD-STATUS.txt") }
}

$dataDir = Join-Path $env:LOCALAPPDATA "HomeGuard"
Copy-RedactedLog (Join-Path $dataDir "logs\homeguard.log") "windows-homeguard.log"
Copy-RedactedLog (Join-Path $dataDir "logs\homeguard.jsonl") "windows-homeguard.jsonl"
if (Test-Path (Join-Path $dataDir "state.json")) { Copy-Item (Join-Path $dataDir "state.json") (Join-Path $Temp "state.json") -Force }

$venvPython = Join-Path $Root "windows-agent\.venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    Save-Text "doctor.txt" {
        Push-Location (Join-Path $Root "windows-agent")
        try { & $venvPython -m homeguard_agent.cli doctor } finally { Pop-Location }
    }
}

$adb = Get-Command adb -ErrorAction SilentlyContinue
if ($adb) {
    Save-Text "adb-devices.txt" { & $adb.Source devices -l }
    foreach ($package in @("com.noamjan.homeguard.debug", "com.noamjan.homeguard")) {
        $safe = $package.Replace('.', '-')
        try {
            $log = & $adb.Source shell run-as $package cat files/logs/homeguard.log 2>$null
            if ($LASTEXITCODE -eq 0 -and $log) { $log | Set-Content (Join-Path $Temp "android-$safe.log") -Encoding UTF8 }
            $json = & $adb.Source shell run-as $package cat files/logs/homeguard.jsonl 2>$null
            if ($LASTEXITCODE -eq 0 -and $json) { $json | Set-Content (Join-Path $Temp "android-$safe.jsonl") -Encoding UTF8 }
        } catch {}
    }
    Save-Text "android-logcat-homeguard.txt" {
        & $adb.Source logcat -d -T 2000 | Select-String -Pattern "HomeGuard|homeguard|AndroidRuntime"
    }
}

@"
Excluded intentionally:
- API token and device credential files
- Supabase access/refresh tokens
- face-whitelist embeddings
- events database
- camera screenshots
- voice recordings

Review this archive before sharing. Device IDs, timestamps, camera names, and LAN addresses may still be sensitive.
"@ | Set-Content (Join-Path $Temp "PRIVACY-NOTICE.txt") -Encoding UTF8

if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path (Join-Path $Temp "*") -DestinationPath $Zip -CompressionLevel Optimal
Remove-Item $Temp -Recurse -Force
Write-Host "Debug bundle created: $Zip" -ForegroundColor Green
