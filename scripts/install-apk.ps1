param(
    [string]$ApkPath = "",
    [switch]$Release
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$adb = Get-Command adb -ErrorAction SilentlyContinue
if (-not $adb) { throw "adb was not found. Install Android Platform Tools and add them to PATH." }

& $adb.Source start-server | Out-Null
$devices = @(& $adb.Source devices | Select-Object -Skip 1 | Where-Object { $_ -match "\sdevice$" })
if ($devices.Count -eq 0) {
    throw "No authorized Android device found. Enable USB debugging, reconnect the phone, and accept the RSA prompt."
}
if ($devices.Count -gt 1) {
    throw "More than one Android device is connected. Disconnect extras or install manually with adb -s SERIAL install -r APK."
}

if (-not $ApkPath) {
    $candidates = @(
        (Join-Path $Root "dist\HomeGuard-debug.apk"),
        (Join-Path $Root "dist\app-debug.apk"),
        (Join-Path $Root "dist\HomeGuard-release.apk"),
        (Join-Path $Root "dist\app-release.apk"),
        (Join-Path $Root "android-app\app\build\outputs\apk\debug\app-debug.apk"),
        (Join-Path $Root "android-app\app\build\outputs\apk\release\app-release.apk")
    )
    $ApkPath = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $ApkPath -or -not (Test-Path $ApkPath)) { throw "APK not found. Pass -ApkPath or place the APK in the dist folder." }

$resolved = (Resolve-Path $ApkPath).Path
Write-Host "Installing: $resolved" -ForegroundColor Cyan
& $adb.Source install -r $resolved
if ($LASTEXITCODE -ne 0) { throw "adb install failed" }

$packageName = if ($Release -or $resolved -match "release") { "com.noamjan.homeguard" } else { "com.noamjan.homeguard.debug" }
Write-Host "Launching $packageName" -ForegroundColor Cyan
& $adb.Source shell monkey -p $packageName -c android.intent.category.LAUNCHER 1 | Out-Null
Write-Host "Installed and launch requested successfully." -ForegroundColor Green
