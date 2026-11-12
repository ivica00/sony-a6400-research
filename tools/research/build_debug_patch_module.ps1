# Build the RAM-only helper module with the WSL ARM toolchain.
# Default (no arguments) is the E0403 B1c helper (a6400_dbg_patch.c).
# -Tree builds the E0407b1 tree building block (a6400_dbg_tree.c), its
# Unicorn test image and the artifacts/tests payload from the same source.
# The Python tool performs the carrier ELF surgery and the static audit; this
# wrapper compiles the helper object and links the final module.
param(
  [string]$Source,
  [string]$Object,
  [string]$OutDir,
  [string]$Name,
  [switch]$Tree
)
$ErrorActionPreference = 'Stop'
if (-not $Source) { $Source = if ($Tree) { 'tools/native_camera/a6400_dbg_tree.c' } else { 'tools/native_camera/a6400_dbg_patch.c' } }
if (-not $OutDir) { $OutDir = if ($Tree) { 'artifacts/native/e0407b1-tree' } else { 'artifacts/native/a6400-dbg-patch-e0403' } }
if (-not $Name) { $Name = if ($Tree) { 'a6400_dbg_tree' } else { 'a6400_dbg_patch' } }
if (-not $Object) { $Object = "$OutDir/$Name.o" }
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$linux = '/mnt/' + $root.Substring(0,1).ToLower() + ($root.Substring(2) -replace '\\','/')
$final = Join-Path $OutDir 'final'
New-Item -ItemType Directory -Force -Path (Join-Path $root $final) | Out-Null

$common = @(
  '-std=gnu11','-marm','-march=armv7-a','-mfloat-abi=softfp','-O2',
  '-Wall','-Wextra','-Werror','-ffreestanding','-fno-builtin','-fno-pic','-fno-pie',
  '-fno-stack-protector','-fno-common','-fno-tree-loop-distribute-patterns'
)

$srcUnix = $Source -replace '\\','/'
$objUnix = $Object -replace '\\','/'
$outUnix = $OutDir -replace '\\','/'

$pyArgs = @('--name', $Name, '--output-dir', $OutDir)
if ($Tree) {
  $pyArgs += @('--tree-source', $Source)
}

if ($Tree) {
  # Unicorn test image: same source, service stubs bound to fixed addresses so
  # the compiled tree logic runs against a synthetic fixture (no hardware).
  $testObj = Join-Path $OutDir 'a6400_dbg_tree_test.o'
  & wsl.exe --cd $linux --exec arm-linux-gnueabi-gcc @common -DA6400_TREE_TEST -c $srcUnix -o ($testObj -replace '\\','/')
  if ($LASTEXITCODE -ne 0) { throw "tree test compile failed: $LASTEXITCODE" }
  $testDir = Join-Path $root (Join-Path $OutDir 'test')
  New-Item -ItemType Directory -Force -Path $testDir | Out-Null
  $ldScript = Join-Path $testDir 'tree_test.ld'
  @'
ENTRY(init_module)
SECTIONS
{
  . = 0x10010000;
  .text : { *(.text*) }
  . = 0x10020000;
  .rodata : { *(.rodata*) }
  . = 0x10021000;
  .data : { *(.data*) }
  . = 0x10022000;
  .bss : { *(.bss*) *(COMMON) }
  /DISCARD/ : { *(.ARM.exidx*) *(.ARM.attributes) *(.comment) *(.modinfo) }
}
tree_alloc = 0x10030000;
tree_kfree = 0x10030010;
tree_memcpy = 0x10030020;
tree_memset = 0x10030030;
tree_probe_read = 0x10030040;
tree_probe_write = 0x10030050;
tree_log = 0x10030060;
tree_pullup = 0x10030070;
tree_stop_disconnect = 0x10030080;
tree_gcw_stop = 0x10030090;
'@ | Set-Content -Path $ldScript -Encoding ascii
  & wsl.exe --cd $linux --exec arm-linux-gnueabi-ld -T "$outUnix/test/tree_test.ld" `
    -o "$outUnix/test/tree_test.elf" ($testObj -replace '\\','/')
  if ($LASTEXITCODE -ne 0) { throw "tree test link failed: $LASTEXITCODE" }
  & .\venv\Scripts\python.exe -m tools.research.build_debug_patch_module --emit-tree-test-payload
  if ($LASTEXITCODE -ne 0) { throw "tree test payload failed: $LASTEXITCODE" }
}

& wsl.exe --cd $linux --exec arm-linux-gnueabi-gcc @common -c $srcUnix -o $objUnix
if ($LASTEXITCODE -ne 0) { throw "helper compile failed: $LASTEXITCODE" }

& .\venv\Scripts\python.exe -m tools.research.build_debug_patch_module @pyArgs --prepare-only
if ($LASTEXITCODE -ne 0) { throw "carrier preparation failed: $LASTEXITCODE" }

& wsl.exe --cd $linux --exec arm-linux-gnueabi-ld -r `
  -o "$outUnix/final/$Name.ko" `
  "$outUnix/carrier_redirected.ko" `
  $objUnix
if ($LASTEXITCODE -ne 0) { throw "module link failed: $LASTEXITCODE" }

& .\venv\Scripts\python.exe -m tools.research.build_debug_patch_module @pyArgs --audit-only
if ($LASTEXITCODE -ne 0) { throw "static audit failed: $LASTEXITCODE" }
Write-Output 'module built and audited'
