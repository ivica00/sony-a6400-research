#requires -Version 5.1
<#
.SYNOPSIS
    Capture the host side of the Track B UVC/RenderStream negotiation with the
    best capture stack this machine actually has, then write a hash-pinned
    manifest around a caller-supplied command.

.DESCRIPTION
    OFFLINE / CAMERA-FREE TODAY. This script never changes a camera mode, never
    loads a module and never touches a Sony device. It only:
      * detects USBPcapCMD (USBPcap), dumpcap (Npcap), Windows USB ETW
        (logman/wpr/tracelog) and the providers
        Microsoft-Windows-USB-USBPORT, Microsoft-Windows-USB-USBHUB3,
        Microsoft-Windows-USB-USBXHCI;
      * starts the best available capture into
        artifacts/analysis/<name>/usb-capture.<ext>;
      * runs the caller's command (default: the ffmpeg DirectShow RenderStream
        attempt against "USB Streaming Device") with stdout+stderr captured;
      * stops the capture and writes manifest.json with tool versions, exact
        commands, start/stop times, capture size/SHA-256, the command exit code,
        stderr log hash, and before/after PnP + dshow snapshots.

    -DryRun performs detection, prints the exact commands it WOULD run,
    validates argument handling, takes best-effort read-only snapshots and
    writes a dry-run manifest. It starts no capture and runs no ffmpeg capture.

.PARAMETER Name
    Output directory name under artifacts/analysis. Default:
    trackb-capture-<UTC timestamp>. Allowed: A-Z a-z 0-9 . _ -

.PARAMETER OutRoot
    Override the analysis root (default: <repo>/artifacts/analysis).

.PARAMETER Command
    Command line executed with cmd.exe /d /s /c, output captured. Default is the
    ffmpeg DirectShow RenderStream one-frame attempt.

.PARAMETER TimeoutSec
    Bound on the caller command (1..600). Default 90.

.PARAMETER UsbPcapDevice
    USBPcap device. Default \\.\USBPcap1 (verify with `USBPcapCMD.exe -D`).

.PARAMETER NpcapInterface
    dumpcap interface (from `dumpcap -D`). Without it Npcap is reported but not
    selected: dumpcap cannot capture a USB bus without a USBPcap-style interface.

.PARAMETER Analyze
    Analysis-only mode: convert an existing .etl to XML with tracerpt, or with
    `netsh trace convert ... dump=XML` when tracerpt is absent. Writes
    usb-capture-analysis.json next to the ETL. No capture is started.

.PARAMETER DryRun
    Detection + exact-command preview + dry-run manifest. Starts nothing.

.EXAMPLE
    .\renderstream_capture.ps1 -DryRun -Name trackb-diag-e0351

.EXAMPLE
    .\renderstream_capture.ps1 -Name trackb-live-01 -TimeoutSec 120

.EXAMPLE
    .\renderstream_capture.ps1 -Analyze 'artifacts\analysis\trackb-live-01\usb-capture.etl'

.NOTES
    Exit codes: 0 ok / dry-run with a stack; 2 no capture stack available;
    3 invalid arguments; 4 capture start/stop or capture file failed;
    5 caller command timed out; 6 ETL analysis tool missing/failed.

    ETW command correction: `logman start <name> -p ... -o ...` is not valid
    logman syntax (start accepts only -as/-ets). The working sequence used here
    is `logman create trace <name> -pf providers.txt -o file.etl -ets` then
    `logman stop <name> -ets` then `logman delete <name> -ets`. A provider list
    file is used because -p enables exactly one provider per create.
#>
[CmdletBinding()]
param(
    [string]$Name = '',
    [string]$OutRoot = '',
    [string]$Command = '',
    [ValidateRange(1, 600)]
    [int]$TimeoutSec = 90,
    [string]$UsbPcapDevice = '\\.\USBPcap1',
    [string]$NpcapInterface = '',
    [string]$Analyze = '',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$EXIT_OK = 0
$EXIT_NO_STACK = 2
$EXIT_ARGS = 3
$EXIT_CAPTURE = 4
$EXIT_TIMEOUT = 5
$EXIT_ANALYZE = 6

$Script:Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$Script:RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
if (-not $OutRoot) {
    $OutRoot = Join-Path $Script:RepoRoot 'artifacts\analysis'
}
$Script:OutRoot = $OutRoot

$Script:DefaultCommand = 'ffmpeg -nostdin -y -hide_banner -f dshow -rtbufsize 256M -i "video=USB Streaming Device" -frames:v 1 -update 1 "renderstream.png"'

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

function Write-Utf8File {
    param([string]$Path, [string]$Text)
    [System.IO.File]::WriteAllText($Path, $Text, $Script:Utf8NoBom)
}

function Get-UtcStamp {
    return (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
}

function Test-Elevated {
    try {
        $id = [Security.Principal.WindowsIdentity]::GetCurrent()
        $pr = New-Object Security.Principal.WindowsPrincipal($id)
        return $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch {
        return $false
    }
}

function Find-Tool {
    param([string[]]$Names, [string[]]$Paths)
    foreach ($p in $Paths) {
        if ($p -and (Test-Path -LiteralPath $p -PathType Leaf)) {
            return (Get-Item -LiteralPath $p).FullName
        }
    }
    foreach ($n in $Names) {
        $c = Get-Command $n -ErrorAction SilentlyContinue
        if ($c) { return $c.Source }
    }
    return $null
}

function Get-ToolVersion {
    param([string]$Path)
    if (-not $Path) { return $null }
    try {
        return (Get-Item -LiteralPath $Path).VersionInfo.FileVersion
    } catch {
        return $null
    }
}

function Get-FirstVersionLine {
    param([string]$Exe, [string]$Arg = '-version')
    if (-not $Exe) { return $null }
    try {
        $out = & $Exe $Arg 2>&1 | Select-Object -First 1
        if ($out) { return ([string]$out).Trim() }
    } catch { }
    return $null
}

function Get-Sha256 {
    param([string]$Path)
    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    try {
        return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    } catch {
        return $null
    }
}

function Get-PnpSnapshot {
    # Read-only. The 054C/PID_0322 filter is the UVC composite device under
    # investigation; the wider 054C filter keeps the Mass Storage / PC Remote
    # parent visible in the same snapshot.
    $pid0322 = @()
    $allSony = @()
    try {
        $allSony = @(Get-PnpDevice -PresentOnly -ErrorAction Stop |
            Where-Object { $_.InstanceId -like '*VID_054C*' } |
            Select-Object Status, Class, FriendlyName, InstanceId)
    } catch {
        $allSony = @()
    }
    $pid0322 = @($allSony | Where-Object { $_.InstanceId -like '*PID_0322*' })
    return [pscustomobject]@{
        pid_0322 = @($pid0322)
        all_sony = @($allSony)
    }
}

function Get-DshowSnapshot {
    # Read-only enumeration. ffmpeg returns 1 for `-i dummy`; that is expected
    # and the output (which lists the DirectShow devices) is what matters.
    $ffmpeg = Find-Tool -Names @('ffmpeg.exe', 'ffmpeg') -Paths @()
    if (-not $ffmpeg) {
        return [pscustomobject]@{ available = $false; exit_code = $null; output = 'ffmpeg not found' }
    }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $ffmpeg
    $psi.Arguments = '-hide_banner -list_devices true -f dshow -i dummy'
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $p = New-Object System.Diagnostics.Process
    $p.StartInfo = $psi
    [void]$p.Start()
    $outTask = $p.StandardOutput.ReadToEndAsync()
    $errTask = $p.StandardError.ReadToEndAsync()
    [void]$p.WaitForExit(15000)
    try { $p.WaitForExit() } catch { }
    $text = ($outTask.Result + $errTask.Result)
    return [pscustomobject]@{
        available = $true
        exit_code = $p.ExitCode
        output = $text.Trim()
    }
}

function Get-UsbProviders {
    # Read-only query: which of the three required USB ETW providers exist.
    $wanted = @(
        'Microsoft-Windows-USB-USBPORT',
        'Microsoft-Windows-USB-USBHUB3',
        'Microsoft-Windows-USB-USBXHCI'
    )
    $rows = @()
    $table = @{}
    try {
        $lines = & logman query providers 2>&1
        foreach ($line in $lines) {
            if ($line -match '^(Microsoft-Windows-[A-Za-z0-9\-]+)\s+\{([0-9A-Fa-f\-]+)\}') {
                $table[$matches[1]] = $matches[2]
            }
        }
    } catch { }
    foreach ($w in $wanted) {
        $rows += [pscustomobject]@{
            name = $w
            present = $table.ContainsKey($w)
            guid = if ($table.ContainsKey($w)) { $table[$w] } else { $null }
        }
    }
    return $rows
}

function Get-Availability {
    $elevated = Test-Elevated
    $pf = $env:ProgramFiles
    $pf86 = ${env:ProgramFiles(x86)}
    if (-not $pf86) { $pf86 = 'C:\Program Files (x86)' }
    $usbpcap = Find-Tool -Names @('USBPcapCMD.exe') -Paths @(
        (Join-Path $pf 'USBPcap\USBPcapCMD.exe'),
        (Join-Path $pf86 'USBPcap\USBPcapCMD.exe')
    )
    $dumpcap = Find-Tool -Names @('dumpcap.exe') -Paths @(
        (Join-Path $pf 'Npcap\dumpcap.exe'),
        (Join-Path $pf86 'Npcap\dumpcap.exe'),
        (Join-Path $pf 'Wireshark\dumpcap.exe'),
        (Join-Path $pf86 'Wireshark\dumpcap.exe')
    )
    $logman = Find-Tool -Names @('logman.exe') -Paths @()
    $wpr = Find-Tool -Names @('wpr.exe') -Paths @()
    $tracelog = Find-Tool -Names @('tracelog.exe') -Paths @()
    $tracerpt = Find-Tool -Names @('tracerpt.exe') -Paths @()
    $netsh = Find-Tool -Names @('netsh.exe') -Paths @()
    $ffmpeg = Find-Tool -Names @('ffmpeg.exe', 'ffmpeg') -Paths @()

    $providers = @()
    if ($logman) { $providers = @(Get-UsbProviders) }
    $providersPresent = ($providers.Count -gt 0) -and (@($providers | Where-Object { -not $_.present }).Count -eq 0)
    $etwPresent = [bool]($logman) -and $providersPresent

    $npcapPresent = [bool]$dumpcap
    $npcapUsable = $npcapPresent -and ($NpcapInterface -ne '')

    $selected = 'none'
    if ($usbpcap) { $selected = 'usbpcap' }
    elseif ($npcapUsable) { $selected = 'npcap' }
    elseif ($etwPresent) { $selected = 'etw' }

    return [pscustomobject]@{
        elevated = $elevated
        usbpcap = [pscustomobject]@{
            present = [bool]$usbpcap
            path = $usbpcap
            version = Get-ToolVersion $usbpcap
            device = $UsbPcapDevice
        }
        npcap = [pscustomobject]@{
            present = $npcapPresent
            path = $dumpcap
            version = Get-ToolVersion $dumpcap
            interface = $NpcapInterface
            usable = $npcapUsable
        }
        etw = [pscustomobject]@{
            logman = $logman
            wpr = $wpr
            tracelog = $tracelog
            tracerpt = $tracerpt
            netsh = $netsh
            providers = @($providers)
            providers_present = [bool]$providersPresent
            present = [bool]$etwPresent
        }
        ffmpeg = [pscustomobject]@{
            path = $ffmpeg
            version = (Get-FirstVersionLine -Exe $ffmpeg)
        }
        selected = $selected
    }
}

function Show-Availability {
    param($Avail)
    Write-Host ''
    Write-Host '=== capture stack availability ===' -ForegroundColor Cyan
    Write-Host ("  elevated (Administrator) : {0}" -f $Avail.elevated)
    Write-Host ("  USBPcapCMD.exe           : {0}" -f $(if ($Avail.usbpcap.present) { "$($Avail.usbpcap.path) [$($Avail.usbpcap.version)]" } else { 'NOT FOUND' }))
    Write-Host ("  dumpcap.exe (Npcap)      : {0}" -f $(if ($Avail.npcap.present) { "$($Avail.npcap.path) [$($Avail.npcap.version)]" } else { 'NOT FOUND' }))
    Write-Host ("  logman.exe               : {0}" -f $(if ($Avail.etw.logman) { $Avail.etw.logman } else { 'NOT FOUND' }))
    Write-Host ("  wpr.exe                  : {0}" -f $(if ($Avail.etw.wpr) { $Avail.etw.wpr } else { 'NOT FOUND' }))
    Write-Host ("  tracelog.exe             : {0}" -f $(if ($Avail.etw.tracelog) { $Avail.etw.tracelog } else { 'NOT FOUND' }))
    foreach ($prov in $Avail.etw.providers) {
        Write-Host ("  provider {0,-38}: {1}" -f $prov.name, $(if ($prov.present) { $prov.guid } else { 'NOT REGISTERED' }))
    }
    Write-Host ("  ffmpeg.exe               : {0}" -f $(if ($Avail.ffmpeg.path) { "$($Avail.ffmpeg.path) [$($Avail.ffmpeg.version)]" } else { 'NOT FOUND' }))
    Write-Host ("  selected stack           : {0}" -f $Avail.selected) -ForegroundColor Yellow
    Write-Host ''
}

function Show-NoStackGuidance {
    Write-Host 'No usable USB capture stack was found on this host.' -ForegroundColor Red
    Write-Host ''
    Write-Host 'Install ONE of the following (nothing was installed by this script):'
    Write-Host ''
    Write-Host '1) USBPcap (gives USB bus capture + USBPcapCMD.exe):'
    Write-Host '     https://desowin.org/usbpcap/'
    Write-Host '     default: C:\Program Files\USBPcap\USBPcapCMD.exe'
    Write-Host '     list roots : "C:\Program Files\USBPcap\USBPcapCMD.exe" -D'
    Write-Host '     capture    : "C:\Program Files\USBPcap\USBPcapCMD.exe" -d \\.\USBPcap1 -o out.pcap -A'
    Write-Host ''
    Write-Host '2) Npcap + Wireshark (gives dumpcap.exe):'
    Write-Host '     https://npcap.com/#download'
    Write-Host '     list ifaces: "C:\Program Files\Npcap\dumpcap.exe" -D'
    Write-Host '     capture    : "C:\Program Files\Npcap\dumpcap.exe" -i <iface> -w out.pcapng'
    Write-Host ''
    Write-Host '3) Windows USB ETW (built in; needs an elevated session):'
    Write-Host '     logman create trace a6400usb -pf providers.txt -o usb-capture.etl -ets'
    Write-Host '     logman stop a6400usb -ets'
    Write-Host '     logman delete a6400usb -ets'
    Write-Host '     providers.txt:'
    Write-Host '       Microsoft-Windows-USB-USBPORT'
    Write-Host '       Microsoft-Windows-USB-USBHUB3'
    Write-Host '       Microsoft-Windows-USB-USBXHCI'
    Write-Host ''
    Write-Host 'An elevated PowerShell session is required for all three.'
}

function Get-CaptureSpec {
    param($Avail, [string]$OutDir)
    $capturePath = $null
    $startCmd = $null
    $stopCmd = $null
    switch ($Avail.selected) {
        'usbpcap' {
            $capturePath = Join-Path $OutDir 'usb-capture.pcap'
            $startCmd = '"{0}" -d {1} -o "{2}" -A' -f $Avail.usbpcap.path, $Avail.usbpcap.device, $capturePath
            $stopCmd = 'Stop-Process -Id <USBPcapCMD pid> -Force   # USBPcapCMD has no graceful CLI stop'
        }
        'npcap' {
            $capturePath = Join-Path $OutDir 'usb-capture.pcapng'
            $startCmd = '"{0}" -i "{1}" -w "{2}" -a duration:{3}' -f $Avail.npcap.path, $Avail.npcap.interface, $capturePath, ($TimeoutSec + 30)
            $stopCmd = 'Stop-Process -Id <dumpcap pid> -Force   # auto-stops after -a duration'
        }
        'etw' {
            $capturePath = Join-Path $OutDir 'usb-capture.etl'
            $providersFile = Join-Path $OutDir 'usb-providers.txt'
            $startCmd = 'logman create trace a6400usb -pf "{0}" -o "{1}" -ets' -f $providersFile, $capturePath
            $stopCmd = 'logman stop a6400usb -ets'
        }
        default {
            $capturePath = Join-Path $OutDir 'usb-capture.none'
            $startCmd = $null
            $stopCmd = $null
        }
    }
    return [pscustomobject]@{
        path = $capturePath
        start_command = $startCmd
        stop_command = $stopCmd
        delete_command = $(if ($Avail.selected -eq 'etw') { 'logman delete a6400usb -ets' } else { $null })
    }
}

function Start-Capture {
    param($Avail, [string]$OutDir, $Spec)
    $state = [pscustomobject]@{
        started = $false
        method = $Avail.selected
        pid = $null
        start_utc = Get-UtcStamp
        error = $null
    }
    try {
        switch ($Avail.selected) {
            'usbpcap' {
                $proc = Start-Process -FilePath $Avail.usbpcap.path `
                    -ArgumentList @('-d', $Avail.usbpcap.device, '-o', $Spec.path, '-A') `
                    -PassThru -WindowStyle Hidden
                $state.pid = $proc.Id
                $state.started = $true
            }
            'npcap' {
                $proc = Start-Process -FilePath $Avail.npcap.path `
                    -ArgumentList @('-i', $Avail.npcap.interface, '-w', $Spec.path, '-a', ("duration:{0}" -f ($TimeoutSec + 30))) `
                    -PassThru -WindowStyle Hidden
                $state.pid = $proc.Id
                $state.started = $true
            }
            'etw' {
                $providersFile = Join-Path $OutDir 'usb-providers.txt'
                $providers = @(
                    'Microsoft-Windows-USB-USBPORT',
                    'Microsoft-Windows-USB-USBHUB3',
                    'Microsoft-Windows-USB-USBXHCI'
                )
                Write-Utf8File -Path $providersFile -Text (($providers -join "`r`n") + "`r`n")
                $out = & logman create trace a6400usb -pf $providersFile -o $Spec.path -ets 2>&1
                if ($LASTEXITCODE -ne 0) {
                    $state.error = ($out | Out-String).Trim()
                } else {
                    $state.started = $true
                }
            }
            default {
                $state.error = 'no capture stack selected'
            }
        }
    } catch {
        $state.error = $_.Exception.Message
        $state.started = $false
    }
    return $state
}

function Stop-Capture {
    param($Avail, $Spec, $State)
    $result = [pscustomobject]@{
        attempted = $true
        method = $null
        rc = $null
        output = $null
        stop_utc = Get-UtcStamp
    }
    if (-not $State.started) {
        $result.attempted = $false
        return $result
    }
    try {
        switch ($Avail.selected) {
            'usbpcap' {
                if ($State.pid) {
                    Stop-Process -Id $State.pid -Force -ErrorAction SilentlyContinue
                    $result.method = 'terminate_process'
                    $result.rc = 0
                }
            }
            'npcap' {
                if ($State.pid) {
                    Stop-Process -Id $State.pid -Force -ErrorAction SilentlyContinue
                    $result.method = 'terminate_process'
                    $result.rc = 0
                }
            }
            'etw' {
                $out = & logman stop a6400usb -ets 2>&1
                $result.method = 'logman_stop'
                $result.rc = $LASTEXITCODE
                $result.output = ($out | Out-String).Trim()
                $del = & logman delete a6400usb -ets 2>&1
                $result.output = ($result.output + "`n" + (($del | Out-String).Trim())).Trim()
            }
        }
    } catch {
        $result.rc = -1
        $result.output = $_.Exception.Message
    }
    return $result
}

function Invoke-CapturedCommand {
    param([string]$CommandLine, [string]$OutDir, [int]$Timeout)
    $stdoutPath = Join-Path $OutDir 'renderstream.stdout.log'
    $stderrPath = Join-Path $OutDir 'renderstream.stderr.log'
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $env:ComSpec
    $psi.Arguments = '/d /s /c "' + $CommandLine + '"'
    $psi.WorkingDirectory = $OutDir
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $p = New-Object System.Diagnostics.Process
    $p.StartInfo = $psi
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    [void]$p.Start()
    $outTask = $p.StandardOutput.ReadToEndAsync()
    $errTask = $p.StandardError.ReadToEndAsync()
    $timedOut = -not $p.WaitForExit($Timeout * 1000)
    if ($timedOut) {
        try { $p.Kill() } catch { }
        try { [void]$p.WaitForExit(5000) } catch { }
    }
    try { $p.WaitForExit() } catch { }
    $stdout = $outTask.Result
    $stderr = $errTask.Result
    $sw.Stop()
    Write-Utf8File -Path $stdoutPath -Text $stdout
    Write-Utf8File -Path $stderrPath -Text $stderr
    return [pscustomobject]@{
        command = $CommandLine
        exit_code = $(if ($timedOut) { $null } else { $p.ExitCode })
        timed_out = $timedOut
        duration_ms = [int]$sw.ElapsedMilliseconds
        stdout_log = $stdoutPath
        stderr_log = $stderrPath
        stderr_bytes = $stderr.Length
        stderr_sha256 = (Get-Sha256 $stderrPath)
    }
}

function Write-Manifest {
    param([string]$OutDir, $Manifest)
    $path = Join-Path $OutDir 'manifest.json'
    $json = $Manifest | ConvertTo-Json -Depth 10
    Write-Utf8File -Path $path -Text ($json + "`n")
    return $path
}

function Invoke-Analyze {
    param([string]$EtlPath)
    if (-not (Test-Path -LiteralPath $EtlPath -PathType Leaf)) {
        Write-Host ("ETL not found: {0}" -f $EtlPath) -ForegroundColor Red
        return $EXIT_ARGS
    }
    $dir = Split-Path -Parent (Resolve-Path -LiteralPath $EtlPath).Path
    $tracerpt = Find-Tool -Names @('tracerpt.exe') -Paths @()
    $netsh = Find-Tool -Names @('netsh.exe') -Paths @()
    $xmlPath = Join-Path $dir 'usb-capture.xml'
    $command = $null
    $rc = $null
    $output = $null
    if ($tracerpt) {
        $command = '"{0}" "{1}" -of XML -o "{2}" -y' -f $tracerpt, $EtlPath, $xmlPath
        try {
            $output = (& $tracerpt $EtlPath -of XML -o $xmlPath -y 2>&1 | Out-String).Trim()
            $rc = $LASTEXITCODE
        } catch {
            $rc = -1
            $output = $_.Exception.Message
        }
    } elseif ($netsh) {
        $command = 'netsh trace convert input="{0}" output="{1}" dump=XML overwrite=yes' -f $EtlPath, $xmlPath
        try {
            $output = (& netsh trace convert "input=$EtlPath" "output=$xmlPath" 'dump=XML' 'overwrite=yes' 2>&1 | Out-String).Trim()
            $rc = $LASTEXITCODE
        } catch {
            $rc = -1
            $output = $_.Exception.Message
        }
    } else {
        Write-Host 'Neither tracerpt.exe nor netsh.exe is available for ETL analysis.' -ForegroundColor Red
        return $EXIT_ANALYZE
    }
    $analysis = [pscustomobject]@{
        schema = 'a6400-usb-etl-analysis/1'
        etl = (Resolve-Path -LiteralPath $EtlPath).Path
        etl_bytes = (Get-Item -LiteralPath $EtlPath).Length
        etl_sha256 = (Get-Sha256 $EtlPath)
        command = $command
        exit_code = $rc
        output = $output
        xml = $xmlPath
        xml_written = (Test-Path -LiteralPath $xmlPath -PathType Leaf)
        xml_bytes = $(if (Test-Path -LiteralPath $xmlPath -PathType Leaf) { (Get-Item -LiteralPath $xmlPath).Length } else { 0 })
        xml_sha256 = (Get-Sha256 $xmlPath)
    }
    $jsonPath = Join-Path $dir 'usb-capture-analysis.json'
    Write-Utf8File -Path $jsonPath -Text (($analysis | ConvertTo-Json -Depth 6) + "`n")
    Write-Host ("analysis: {0}" -f $jsonPath)
    if ($rc -ne 0 -or -not $analysis.xml_written) {
        return $EXIT_ANALYZE
    }
    return $EXIT_OK
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

if ($Analyze -and $DryRun) {
    Write-Host '-Analyze and -DryRun are separate modes; pick one.' -ForegroundColor Red
    exit $EXIT_ARGS
}
if ($Analyze) {
    exit (Invoke-Analyze -EtlPath $Analyze)
}

if (-not $Name) {
    $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss')
    $Name = if ($DryRun) { "trackb-dryrun-$stamp" } else { "trackb-capture-$stamp" }
}
if ($Name -notmatch '^[A-Za-z0-9._-]+$') {
    Write-Host ("invalid -Name '{0}': use A-Z a-z 0-9 . _ -" -f $Name) -ForegroundColor Red
    exit $EXIT_ARGS
}
if (-not (Test-Path -LiteralPath $Script:OutRoot -PathType Container)) {
    Write-Host ("analysis root not found: {0}" -f $Script:OutRoot) -ForegroundColor Red
    exit $EXIT_ARGS
}
$outDir = Join-Path $Script:OutRoot $Name
if (-not (Test-Path -LiteralPath $outDir -PathType Container)) {
    New-Item -ItemType Directory -Path $outDir | Out-Null
}

if (-not $Command) { $Command = $Script:DefaultCommand }

$availability = Get-Availability
$spec = Get-CaptureSpec -Avail $availability -OutDir $outDir
$analysisCommand = '"{0}" "{1}" -of XML -o "{2}" -y' -f $availability.etw.tracerpt, $spec.path, (Join-Path $outDir 'usb-capture.xml')

Show-Availability -Avail $availability
Write-Host ("output directory : {0}" -f $outDir)
Write-Host ''
Write-Host '=== exact commands ===' -ForegroundColor Cyan
Write-Host ("  start capture : {0}" -f $(if ($spec.start_command) { $spec.start_command } else { '(none)' }))
Write-Host ("  run command   : cmd.exe /d /s /c `"{0}`"" -f $Command)
Write-Host ("  stop capture  : {0}" -f $(if ($spec.stop_command) { $spec.stop_command } else { '(none)' }))
if ($spec.delete_command) {
    Write-Host ("  cleanup       : {0}" -f $spec.delete_command)
}
Write-Host ("  analyze ETL   : {0}" -f $analysisCommand)
Write-Host ''

$before = [pscustomobject]@{
    pnp = Get-PnpSnapshot
    dshow = Get-DshowSnapshot
}

if ($DryRun) {
    if ($availability.selected -eq 'none') {
        Show-NoStackGuidance
        $manifest = [pscustomobject]@{
            schema = 'a6400-renderstream-capture/1'
            dry_run = $true
            name = $Name
            generated_utc = Get-UtcStamp
            error = 'no_capture_stack'
            availability = $availability
            commands = [pscustomobject]@{
                start = $spec.start_command
                run = $Command
                stop = $spec.stop_command
                cleanup = $spec.delete_command
                analyze = $analysisCommand
            }
            snapshots = [pscustomobject]@{ before = $before; after = $null }
        }
        $mp = Write-Manifest -OutDir $outDir -Manifest $manifest
        Write-Host ("dry-run manifest: {0}" -f $mp)
        exit $EXIT_NO_STACK
    }
    $manifest = [pscustomobject]@{
        schema = 'a6400-renderstream-capture/1'
        dry_run = $true
        name = $Name
        generated_utc = Get-UtcStamp
        note = 'No capture started, no ffmpeg capture command executed. The commands below are exactly what a live run would execute.'
        availability = $availability
        commands = [pscustomobject]@{
            start = $spec.start_command
            run = $Command
            stop = $spec.stop_command
            cleanup = $spec.delete_command
            analyze = $analysisCommand
        }
        capture = [pscustomobject]@{
            path = $spec.path
            exists = $false
            bytes = 0
            sha256 = $null
        }
        command_result = [pscustomobject]@{
            command = $Command
            executed = $false
        }
        snapshots = [pscustomobject]@{ before = $before; after = $null }
        required_providers = @(
            'Microsoft-Windows-USB-USBPORT',
            'Microsoft-Windows-USB-USBHUB3',
            'Microsoft-Windows-USB-USBXHCI'
        )
    }
    $mp = Write-Manifest -OutDir $outDir -Manifest $manifest
    Write-Host ''
    Write-Host 'DRY RUN: nothing was captured and no camera/USB operation was performed.' -ForegroundColor Yellow
    Write-Host ("dry-run manifest: {0}" -f $mp)
    exit $EXIT_OK
}

if ($availability.selected -eq 'none') {
    Show-NoStackGuidance
    exit $EXIT_NO_STACK
}
if (-not $availability.elevated) {
    Write-Host 'This session is NOT elevated. USB capture (USBPcap/dumpcap/ETW) requires Administrator.' -ForegroundColor Red
    Write-Host 'Re-open PowerShell with "Run as administrator" and re-run this script.' -ForegroundColor Red
    exit $EXIT_CAPTURE
}

$start = [pscustomobject]@{
    utc = Get-UtcStamp
    state = $null
}
$captureState = Start-Capture -Avail $availability -OutDir $outDir -Spec $spec
$start.state = $captureState
if (-not $captureState.started) {
    Write-Host ("capture start failed: {0}" -f $captureState.error) -ForegroundColor Red
    $manifest = [pscustomobject]@{
        schema = 'a6400-renderstream-capture/1'
        dry_run = $false
        name = $Name
        generated_utc = Get-UtcStamp
        error = 'capture_start_failed'
        availability = $availability
        commands = [pscustomobject]@{
            start = $spec.start_command
            run = $Command
            stop = $spec.stop_command
            cleanup = $spec.delete_command
        }
        start = $start
        snapshots = [pscustomobject]@{ before = $before; after = (Get-PnpSnapshot) }
    }
    [void](Write-Manifest -OutDir $outDir -Manifest $manifest)
    exit $EXIT_CAPTURE
}
# Give the capture driver time to attach before the USB mode transition.
Start-Sleep -Seconds 2

$cmdResult = Invoke-CapturedCommand -CommandLine $Command -OutDir $outDir -Timeout $TimeoutSec

$stop = [pscustomobject]@{
    utc = Get-UtcStamp
    result = $null
}
$stop.result = Stop-Capture -Avail $availability -Spec $spec -State $captureState
Start-Sleep -Milliseconds 800

$captureFile = $null
$captureBytes = 0
$captureSha = $null
$captureExists = $false
if ($spec.path -and (Test-Path -LiteralPath $spec.path -PathType Leaf)) {
    $captureExists = $true
    $captureFile = (Resolve-Path -LiteralPath $spec.path).Path
    $captureBytes = (Get-Item -LiteralPath $spec.path).Length
    $captureSha = Get-Sha256 $captureFile
}

$after = [pscustomobject]@{
    pnp = Get-PnpSnapshot
    dshow = Get-DshowSnapshot
}

$manifest = [pscustomobject]@{
    schema = 'a6400-renderstream-capture/1'
    dry_run = $false
    name = $Name
    generated_utc = Get-UtcStamp
    availability = $availability
    commands = [pscustomobject]@{
        start = $spec.start_command
        run = $Command
        stop = $spec.stop_command
        cleanup = $spec.delete_command
        analyze = $analysisCommand
    }
    start = $start
    stop = $stop
    capture = [pscustomobject]@{
        path = $captureFile
        exists = $captureExists
        bytes = $captureBytes
        sha256 = $captureSha
    }
    command_result = $cmdResult
    snapshots = [pscustomobject]@{ before = $before; after = $after }
    required_providers = @(
        'Microsoft-Windows-USB-USBPORT',
        'Microsoft-Windows-USB-USBHUB3',
        'Microsoft-Windows-USB-USBXHCI'
    )
}
$mp = Write-Manifest -OutDir $outDir -Manifest $manifest
Write-Host ''
Write-Host ("manifest        : {0}" -f $mp)
Write-Host ("capture         : {0} ({1} bytes)" -f $captureFile, $captureBytes)
Write-Host ("command exit    : {0} (timed out: {1})" -f $cmdResult.exit_code, $cmdResult.timed_out)
Write-Host ("stderr log      : {0} ({1} bytes, sha256 {2})" -f $cmdResult.stderr_log, $cmdResult.stderr_bytes, $cmdResult.stderr_sha256)

if (-not $captureExists -or $captureBytes -eq 0) {
    Write-Host 'capture file missing or empty: the capture is NOT evidence of a session.' -ForegroundColor Red
    exit $EXIT_CAPTURE
}
if ($cmdResult.timed_out) {
    exit $EXIT_TIMEOUT
}
exit $EXIT_OK
