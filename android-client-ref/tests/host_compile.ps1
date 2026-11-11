# Offline host compile + assertion harness for the portable a6400lived native sources.
#
# Why this exists in addition to host_compile.sh: the WSL image used on this host
# has the ARM cross compiler but NO host C++ compiler (`g++`, `gcc`, `clang++`
# are absent in Ubuntu). The Windows host does have MinGW g++ (16.2.0), so this
# script performs the identical compile/run using Windows paths.
#
# This is NOT an Android build. It compiles the same portable sources as
# host_compile.sh against tests/host_stub (JNI/EGL/GLES/AHardwareBuffer/turbojpeg
# are compile-only fakes), then runs the host assertions. No GPU, no camera, no
# Android SDK is involved.
#
#   .\android-client-ref\tests\host_compile.ps1
#
# Exit code: 0 = compile clean (no warnings, -Werror) and all assertions passed.

$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$cpp  = Join-Path $root 'app\src\main\cpp'
$stub = Join-Path $here 'host_stub'

$cxx = (Get-Command g++ -ErrorAction SilentlyContinue)
if (-not $cxx) {
    Write-Error 'g++ not found. Install MinGW-w64 (or set PATH) - see tests/host_compile.sh for the WSL equivalent.'
    exit 2
}

$outDir = Join-Path $env:TEMP ("a6400-host-tests-" + [System.Diagnostics.Process]::GetCurrentProcess().Id)
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$exe = Join-Path $outDir 'host_main.exe'

$sources = @(
    (Join-Path $cpp  'jni_bridge.cpp'),
    (Join-Path $cpp  'pipeline.cpp'),
    (Join-Path $cpp  'jpeg_decoder.cpp'),
    (Join-Path $cpp  'ahardware_buffer_pool.cpp'),
    (Join-Path $cpp  'gl_renderer.cpp'),
    (Join-Path $cpp  'uvc_frame_parser.cpp'),
    (Join-Path $stub 'turbojpeg_stub.cpp'),
    (Join-Path $here 'host_main.cpp')
)

$args = @(
    '-std=c++17', '-Wall', '-Wextra', '-Werror',
    '-DA6400_HOST_COMPILE',
    "-I$stub",
    "-I$(Join-Path $stub 'generated')",
    "-I$cpp"
) + $sources + @('-o', $exe)

Write-Host ("host_compile.ps1: " + (& $cxx.Source --version | Select-Object -First 1))
& $cxx.Source @args
if ($LASTEXITCODE -ne 0) {
    Write-Error "host compile failed (exit $LASTEXITCODE)"
    exit 3
}

& $exe
$runExit = $LASTEXITCODE
Remove-Item $outDir -Recurse -Force -ErrorAction SilentlyContinue
if ($runExit -ne 0) {
    Write-Error "host assertions failed (exit $runExit)"
    exit 4
}
Write-Host 'host_compile.ps1: PASS'
exit 0
