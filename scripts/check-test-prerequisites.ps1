$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot

function Write-Check {
    param([string]$Name, [bool]$Ok, [string]$Details)
    $status = if ($Ok) { "OK" } else { "MISSING" }
    $color = if ($Ok) { "Green" } else { "Yellow" }
    Write-Host ("[{0}] {1} — {2}" -f $status, $Name, $Details) -ForegroundColor $color
}

Write-Host "HomeGuard test-machine prerequisite check" -ForegroundColor Cyan
Write-Host "Workspace: $Root"
Write-Host ""

$isWindows = $env:OS -eq "Windows_NT"
Write-Check "Windows" $isWindows $(if ($isWindows) { [System.Environment]::OSVersion.VersionString } else { "Windows 11 x64 is required for EXE/installer testing" })

$psVersionOk = $PSVersionTable.PSVersion.Major -ge 5
Write-Check "PowerShell" $psVersionOk $PSVersionTable.PSVersion.ToString()

$git = Get-Command git -ErrorAction SilentlyContinue
Write-Check "Git" ($null -ne $git) $(if ($git) { (& git --version 2>$null) } else { "Install Git or use GitHub Desktop" })

$py = Get-Command py -ErrorAction SilentlyContinue
$python312 = $false
$pythonDetails = "Python launcher not found"
if ($py) {
    $pythonDetails = (& py -3.12 --version 2>&1 | Out-String).Trim()
    $python312 = $LASTEXITCODE -eq 0
}
Write-Check "Python 3.12 x64" $python312 $pythonDetails

$node = Get-Command node -ErrorAction SilentlyContinue
Write-Check "Node.js" ($null -ne $node) $(if ($node) { (& node --version 2>$null) } else { "Needed for signaling tests/build" })

$npm = Get-Command npm -ErrorAction SilentlyContinue
Write-Check "npm" ($null -ne $npm) $(if ($npm) { (& npm --version 2>$null) } else { "Installed with Node.js" })

$java = Get-Command java -ErrorAction SilentlyContinue
$javaText = if ($java) { ((& java -version 2>&1) | Select-Object -First 1 | Out-String).Trim() } else { "JDK 17 needed for Android" }
Write-Check "JDK" ($null -ne $java) $javaText

$gradle = Get-Command gradle -ErrorAction SilentlyContinue
$wrapper = Test-Path (Join-Path $Root "android-app\gradlew.bat")
Write-Check "Gradle or wrapper" (($null -ne $gradle) -or $wrapper) $(if ($wrapper) { "gradlew.bat present" } elseif ($gradle) { ((& gradle --version 2>$null | Select-String "Gradle" | Select-Object -First 1) -join "") } else { "Use Android Studio or install Gradle 9.5.0" })

$androidHome = $env:ANDROID_HOME
Write-Check "ANDROID_HOME" (-not [string]::IsNullOrWhiteSpace($androidHome)) $(if ($androidHome) { $androidHome } else { "Set it to your Android SDK folder" })

$adb = Get-Command adb -ErrorAction SilentlyContinue
Write-Check "ADB" ($null -ne $adb) $(if ($adb) { (& adb version 2>$null | Select-Object -First 1) } else { "Install Android Platform Tools" })

$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
Write-Check "Inno Setup 6" ($null -ne $iscc) $(if ($iscc) { $iscc.Source } else { "Needed only for HomeGuard-Setup.exe" })

$cameraCount = 0
if ($isWindows -and (Get-Command Get-PnpDevice -ErrorAction SilentlyContinue)) {
    try {
        $cameraCount = @(Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Where-Object { $_.Class -in @("Camera", "Image") }).Count
    } catch { $cameraCount = 0 }
}
Write-Check "Camera device" ($cameraCount -gt 0) "$cameraCount camera/image device(s) detected"

$freeGb = [math]::Round((Get-PSDrive -Name ((Split-Path $Root -Qualifier).TrimEnd(':')) -ErrorAction SilentlyContinue).Free / 1GB, 1)
if ($freeGb -isnot [double] -and $freeGb -isnot [decimal]) { $freeGb = 0 }
Write-Check "Free disk space" ($freeGb -ge 4) "$freeGb GB free; 4 GB or more recommended"

Write-Host ""
Write-Host "Basic source/Windows testing needs: Windows, PowerShell, Python 3.12, and a camera." -ForegroundColor Cyan
Write-Host "Android local build additionally needs JDK, Android SDK, and Gradle/Android Studio." -ForegroundColor Cyan
Write-Host "GitHub Actions can build the APK and Windows artifacts without local Android/packaging tools." -ForegroundColor Cyan
