param([string]$DeviceSerial = '', [switch]$Install)
$ErrorActionPreference = 'Stop'
# This launcher lives in scripts/; the repository root is its parent directory.
$cinemaRoot = Split-Path -Parent $PSScriptRoot
$cinemaAdb = Join-Path $cinemaRoot '.android-tools/windows/platform-tools/adb.exe'
if (!(Test-Path -LiteralPath $cinemaAdb)) { throw 'ADB is missing. See android/cinemahud/README.md.' }
if (!$DeviceSerial) {
    $cinemaDevices = @(& $cinemaAdb devices | Where-Object { $_ -match '^([^\s]+)\s+device$' } | ForEach-Object { ($_ -split '\s+')[0] })
    if ($cinemaDevices.Count -ne 1) { throw 'Connect one authorized Android phone, or pass -DeviceSerial.' }
    $DeviceSerial = $cinemaDevices[0]
}
try { $null = Invoke-RestMethod 'http://127.0.0.1:8080/api/status' -TimeoutSec 2 }
catch {
    $cinemaPython = Join-Path $cinemaRoot 'venv/Scripts/python.exe'
    Start-Process -FilePath $cinemaPython -ArgumentList '-u -m tools.research.ptp_liveview_client --source ptp --serve --no-auto-deploy' -WorkingDirectory $cinemaRoot -WindowStyle Hidden | Out-Null
    $cinemaReady = $false
    for ($cinemaTry = 0; $cinemaTry -lt 15; $cinemaTry++) {
        Start-Sleep -Milliseconds 700
        try { $null = Invoke-RestMethod 'http://127.0.0.1:8080/api/status' -TimeoutSec 1; $cinemaReady = $true; break } catch {}
    }
    if (!$cinemaReady) { throw 'PTP server did not start. Check that the camera is connected in PC Remote.' }
}
if ($Install) {
    & $cinemaAdb -s $DeviceSerial install -r (Join-Path $cinemaRoot 'dist/cinemahud-android/CinemaHUD-Android-arm64.apk')
    if ($LASTEXITCODE -ne 0) { throw 'Android installation failed.' }
}
& $cinemaAdb -s $DeviceSerial reverse tcp:8080 tcp:8080
if ($LASTEXITCODE -ne 0) { throw 'USB bridge could not be created.' }
& $cinemaAdb -s $DeviceSerial shell am force-stop com.cinemahud.cinemahud_android
& $cinemaAdb -s $DeviceSerial shell am start -n com.cinemahud.cinemahud_android/.MainActivity --es bridge http://127.0.0.1:8080
if ($LASTEXITCODE -ne 0) { throw 'CinemaHUD could not be started.' }
