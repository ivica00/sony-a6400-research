# Build the protocol-v2 native USB debugger with the WSL ARM cross compiler.
# The Python build tool performs the same compile step when WSL can be spawned
# from Python; this wrapper keeps the exact compiler invocation reproducible in
# sandboxes that only permit WSL as a direct PowerShell child. It does not
# deploy to or execute anything on the camera.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$linux = '/mnt/' + $root.Substring(0,1).ToLower() + ($root.Substring(2) -replace '\\','/')
$out = 'artifacts/native/usb-debugger-e0401'
New-Item -ItemType Directory -Force -Path (Join-Path $root $out) | Out-Null

$common = @(
  '-std=gnu11','-march=armv7-a','-mfloat-abi=softfp','-O2','-Wall','-Wextra','-Werror',
  '-nostdlib','-U_FORTIFY_SOURCE','-D_FORTIFY_SOURCE=0',
  '-U_TIME_BITS','-D_TIME_BITS=32','-U_FILE_OFFSET_BITS','-D_FILE_OFFSET_BITS=32'
)

$exeArgs = @('--cd',$linux,'--exec','arm-linux-gnueabi-gcc') + $common + @(
  '-fno-stack-protector','-Wl,-e,_start,-z,defs,-z,max-page-size=4096',
  '--dynamic-linker=/lib/ld-linux.so.3','-lgcc','-o',
  "$out/a6400_usb_debugd.elf",
  'tools/native_camera/debug_start.S',
  'tools/native_camera/a6400_usb_debugd.c',
  'tools/sony_sysroot/lib/libc.so'
)
& wsl.exe @exeArgs
if ($LASTEXITCODE -ne 0) { throw "daemon compile failed: $LASTEXITCODE" }

$launcherArgs = @('--cd',$linux,'--exec','arm-linux-gnueabi-gcc') + $common + @(
  '-fPIC','-shared','-Wl,-soname,usb_debug_launcher.so,-z,defs,-z,max-page-size=4096','-o',
  "$out/usb_debug_launcher.so",
  'tools/native_camera/hook/usb_debug_launcher.c',
  'tools/sony_sysroot/lib/libc.so'
)
& wsl.exe @launcherArgs
if ($LASTEXITCODE -ne 0) { throw "launcher compile failed: $LASTEXITCODE" }

Write-Output 'compiled artifacts/native/usb-debugger-e0401/a6400_usb_debugd.elf'
