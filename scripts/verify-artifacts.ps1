param([string]$DistPath = "")
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Dist = if ($DistPath) { Resolve-Path $DistPath } else { Join-Path $Root "dist" }

if (-not (Test-Path $Dist)) { throw "Artifact folder not found: $Dist" }

$patterns = @(
    "HomeGuardAgent.exe",
    "HomeGuard-Setup.exe",
    "HomeGuard-debug.apk",
    "HomeGuard-release.apk",
    "app-debug.apk",
    "app-release.apk"
)

$files = Get-ChildItem $Dist -Recurse -File | Where-Object { $patterns -contains $_.Name }
if (-not $files) { throw "No HomeGuard EXE/installer/APK was found under $Dist" }

Write-Host "HomeGuard artifact verification" -ForegroundColor Cyan
foreach ($file in $files) {
    $hash = Get-FileHash $file.FullName -Algorithm SHA256
    Write-Host ""
    Write-Host $file.FullName -ForegroundColor White
    Write-Host ("Size: {0:N2} MB" -f ($file.Length / 1MB))
    Write-Host "SHA-256: $($hash.Hash.ToLowerInvariant())"

    if ($file.Extension -eq ".exe") {
        $signature = Get-AuthenticodeSignature $file.FullName
        Write-Host "Authenticode: $($signature.Status)"
        if ($signature.Status -ne "Valid") {
            Write-Warning "This build is not Authenticode-signed. Only run it if you built it yourself and the hash matches your CI output."
        }
    }
}

$hashFiles = Get-ChildItem $Dist -Recurse -File -Filter "SHA256SUMS-*.txt"
foreach ($hashFile in $hashFiles) {
    Write-Host ""
    Write-Host "Found recorded hashes: $($hashFile.FullName)" -ForegroundColor Cyan
    Get-Content $hashFile.FullName | ForEach-Object { Write-Host "  $_" }
}

$apksigner = Get-Command apksigner -ErrorAction SilentlyContinue
if ($apksigner) {
    foreach ($apk in $files | Where-Object Extension -eq ".apk") {
        Write-Host ""
        Write-Host "APK signature verification: $($apk.Name)" -ForegroundColor Cyan
        & $apksigner.Source verify --verbose --print-certs $apk.FullName
        if ($LASTEXITCODE -ne 0) { throw "APK signature verification failed: $($apk.FullName)" }
    }
} else {
    Write-Warning "apksigner is unavailable; APK signature verification was skipped."
}
