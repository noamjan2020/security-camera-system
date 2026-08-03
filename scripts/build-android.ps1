param([switch]$Release)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$App = Join-Path $Root "android-app"
$Dist = Join-Path $Root "dist"
Set-Location $App

if (-not $env:ANDROID_HOME) { throw "ANDROID_HOME is not set. Install Android Studio, API 37, and Build Tools 36.0.0." }
$Tasks = if ($Release) { @("testDebugUnitTest", "lintDebug", "assembleRelease") } else { @("testDebugUnitTest", "lintDebug", "assembleDebug") }
if (Test-Path .\gradlew.bat) { & .\gradlew.bat @Tasks --stacktrace }
elseif (Get-Command gradle -ErrorAction SilentlyContinue) { & gradle @Tasks --stacktrace }
else { throw "Gradle 9.5.0 is unavailable. Open the project in Android Studio or install Gradle 9.5.0." }

New-Item -ItemType Directory -Force $Dist | Out-Null
if ($Release) {
    $Source = ".\app\build\outputs\apk\release\app-release.apk"
    if (-not (Test-Path $Source)) { throw "Release APK was not produced. Configure HOMEGUARD_ANDROID_KEYSTORE_* environment variables for a signed release." }
    $Target = Join-Path $Dist "HomeGuard-release.apk"
} else {
    $Source = ".\app\build\outputs\apk\debug\app-debug.apk"
    if (-not (Test-Path $Source)) { throw "Debug APK was not produced." }
    $Target = Join-Path $Dist "HomeGuard-debug.apk"
}
Copy-Item $Source $Target -Force
$Hash = Get-FileHash $Target -Algorithm SHA256
"{0}  {1}" -f $Hash.Hash.ToLowerInvariant(), (Split-Path $Target -Leaf) | Set-Content (Join-Path $Dist "SHA256SUMS-Android.txt")
Write-Host "Installable APK: $Target"
