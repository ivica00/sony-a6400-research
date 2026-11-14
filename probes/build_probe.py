"""Build and offline-verify the read-only ILCE-6400 UVC/DMA probe.

Two modes, both offline and both without camera access:

  (default)      cross-compile probes/uvc_dma_probe.c with the repo's WSL
                 arm-linux-gnueabi-gcc and record a manifest next to the binary.
  --host-check   compile the SAME source for x86-64 under WSL with
                 -DPROBE_HOST_STUB, run --help, then run a smoke pass against a
                 synthetic /proc-/sys-/dev-like tree in a WSL temp directory and
                 validate the emitted JSON with probes/test_probe_report.py.

Nothing is deployed and no camera is contacted.  A build is not a hardware test.

Exit status: 0 on success, 1 on any loud failure.
"""
import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBES = ROOT / 'probes'
SOURCE = PROBES / 'uvc_dma_probe.c'
VALIDATOR = PROBES / 'test_probe_report.py'
DISTRO = 'Ubuntu'

# Flags are identical to the repo's native-camera convention
# (tools/research/build_native_monitor_collector.py) minus the sysroot libc,
# because this probe is a self-contained _start with direct svc syscalls.
ARM_FLAGS = [
    '-std=gnu11',
    '-march=armv7-a',
    '-mfloat-abi=softfp',
    '-O2',
    '-Wall', '-Wextra', '-Werror',
    '-ffreestanding',        # no implicit libc calls; keeps the binary self-contained
    '-nostdlib', '-static',  # no crt/libc; _start is ours, matching the feeder
    '-fno-stack-protector',  # no __stack_chk_fail outside libc
    '-fno-pic', '-fno-pie',  # fixed-address non-PIE image, no GOT/PLT rewriting
    '-Wl,-e,_start',
]
FLAGS_RATIONALE = {
    '-std=gnu11': 'repo convention for the freestanding native helpers',
    '-march=armv7-a': 'camera CPU is ARMv7-A',
    '-mfloat-abi=softfp': 'repo convention; probe uses no floating point',
    '-O2': 'repo convention; keeps the image small enough for /tmp_bt',
    '-Wall -Wextra -Werror': 'warnings are build failures, as in the repo builders',
    '-ffreestanding': 'the probe includes no headers and must not synthesise libc calls',
    '-nostdlib -static': 'no libc dependency; direct svc syscalls only',
    '-fno-stack-protector': 'no libc stack-failure helper is linked',
    '-fno-pic -fno-pie': 'static, load-anywhere-free image',
    '-Wl,-e,_start': 'entry is the probe _start, not a crt stub',
}


def fail(message):
    print(f'build_probe: {message}', file=sys.stderr)
    raise SystemExit(1)


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def linux_path(path):
    """Translate a Windows path under the repo into /mnt/<drive>/... (repo convention)."""
    path = Path(path).resolve()
    if sys.platform.startswith('linux'):
        return path.as_posix()
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def _decode_wsl(data):
    """wsl.exe emits its own diagnostics as UTF-16LE and the Linux program's as UTF-8."""
    if not data:
        return ''
    if b'\x00' in data[:256]:
        try:
            return data.decode('utf-16-le', errors='replace')
        except UnicodeDecodeError:
            pass
    return data.decode('utf-8', errors='replace')


def wsl(args, *, input_text=None, timeout=300):
    if sys.platform.startswith('linux'):
        command = [str(a) for a in args]
    else:
        command = ['wsl', '-d', DISTRO, '--', *[str(a) for a in args]]
    try:
        proc = subprocess.run(command,
                             input=None if input_text is None else input_text.encode('utf-8'),
                             capture_output=True, timeout=timeout)
    except FileNotFoundError:
        fail('wsl.exe not found; the ARM cross toolchain is only reachable through WSL')
    except subprocess.TimeoutExpired:
        fail(f'WSL command timed out after {timeout}s: {args[0]}')
    proc.stdout_text = _decode_wsl(proc.stdout)
    proc.stderr_text = _decode_wsl(proc.stderr)
    proc.combined = (proc.stdout_text + proc.stderr_text).strip()
    if proc.returncode != 0 and 'ACCESSDENIED' in proc.combined.upper().replace('/', ''):
        print('build_probe: WSL refused the request (Wsl/E_ACCESS_DENIED). This sandbox runs '
              'workspace binaries at low integrity, and a low-integrity process can neither '
              'start WSL nor raise its own children above that level. Re-run this script from a '
              'medium/high-integrity interpreter.', file=sys.stderr)
    return proc


def require_arm_compiler():
    probe = wsl(['arm-linux-gnueabi-gcc', '--version'], timeout=60)
    if probe.returncode != 0:
        fail('arm-linux-gnueabi-gcc is not available in WSL '
             f'(exit {probe.returncode}): {probe.combined[:300]}')
    version = probe.stdout_text.splitlines()[0].strip()
    if 'arm-linux-gnueabi' not in version:
        fail(f'unexpected compiler identity: {version!r}')
    return version


def check_elf(path, machine):
    data = Path(path).read_bytes()
    if len(data) < 64 or data[:4] != b'\x7fELF':
        fail(f'{path} is not an ELF file')
    elf_class = data[4]
    e_machine = int.from_bytes(data[18:20], 'little')
    e_type = int.from_bytes(data[16:18], 'little')
    if machine == 'ARM' and (elf_class != 1 or e_machine != 40):
        fail(f'{path} is not a 32-bit ARM ELF (class {elf_class}, machine {e_machine})')
    if machine == 'x86-64' and (elf_class != 2 or e_machine != 62):
        fail(f'{path} is not an x86-64 ELF (class {elf_class}, machine {e_machine})')
    if elf_class == 1:
        phoff = int.from_bytes(data[28:32], 'little')
        phentsize = int.from_bytes(data[42:44], 'little')
        phnum = int.from_bytes(data[44:46], 'little')
    else:
        phoff = int.from_bytes(data[32:40], 'little')
        phentsize = int.from_bytes(data[54:56], 'little')
        phnum = int.from_bytes(data[56:58], 'little')
    pt_dynamic = False
    for index in range(phnum):
        start = phoff + index * phentsize
        if start + 4 > len(data):
            fail(f'{path} has a truncated program header table')
        if int.from_bytes(data[start:start + 4], 'little') == 2:  # PT_DYNAMIC
            pt_dynamic = True
    if machine == 'ARM' and pt_dynamic:
        fail(f'{path} unexpectedly has PT_DYNAMIC; this probe must stay libc-free')
    return {'class': 32 if elf_class == 1 else 64, 'machine': machine,
            'type': {2: 'EXEC', 3: 'DYN'}.get(e_type, str(e_type)),
            'pt_dynamic': pt_dynamic}


def build_arm(output_dir):
    if not SOURCE.is_file():
        fail(f'missing source: {SOURCE}')
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / 'uvc_dma_probe_arm'
    staging = output_dir / 'uvc_dma_probe_arm.tmp'
    if staging.exists():
        staging.unlink()
    compiler_version = require_arm_compiler()
    args = [*ARM_FLAGS, '-o', linux_path(staging), linux_path(SOURCE)]
    result = wsl(['arm-linux-gnueabi-gcc', *args], timeout=300)
    if result.returncode != 0:
        fail('ARM compile failed:\n' + result.combined[:4000])
    if not staging.is_file() or staging.stat().st_size == 0:
        fail(f'compiler produced no output at {staging}')
    elf = check_elf(staging, 'ARM')
    staging.replace(target)
    manifest = {
        'status': 'built_not_deployed',
        'camera_access': False,
        'deployed': False,
        'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'output': {
            'path': target.relative_to(ROOT).as_posix(),
            'bytes': target.stat().st_size,
            'sha256': sha256_file(target),
            'elf': elf,
        },
        'source': {
            'path': SOURCE.relative_to(ROOT).as_posix(),
            'bytes': SOURCE.stat().st_size,
            'sha256': sha256_file(SOURCE),
        },
        'compiler': {'command': 'arm-linux-gnueabi-gcc (via WSL)', 'version': compiler_version},
        'flags': ARM_FLAGS,
        'flags_rationale': FLAGS_RATIONALE,
        'limitations': [
            'Built and statically verified only; the authoring task did not run it on hardware.',
            'Default mode is read-only observation; --devmem is compiled out (PROBE_ENABLE_DEVMEM=0).',
            '--poll-get-jpeg is an opt-in camera-side DataflowInfra transaction requiring explicit user authorization.',
            'A build receipt is not evidence that any camera value was observed.',
        ],
    }
    manifest_path = output_dir / 'manifest.json'
    manifest_path.write_bytes((json.dumps(manifest, indent=2) + '\n').encode('utf-8'))
    print(f'built {manifest["output"]["path"]} '
          f'({manifest["output"]["bytes"]} B, sha256 {manifest["output"]["sha256"]})')
    print(f'manifest {manifest_path.relative_to(ROOT).as_posix()}')
    return manifest


FIXTURE_SETUP = r'''#!/bin/sh
# Synthetic /proc-/sys-/dev-like tree for the host fixture run of uvc_dma_probe.
# Every value below is fixture data, not a camera observation.
set -eu
ROOT="$1"
mkdir -p "$ROOT/proc/149/fd" "$ROOT/proc/149/task" "$ROOT/proc/osal" \
         "$ROOT/sys/class/udc/dwc3.0" "$ROOT/dev/usb" "$ROOT/out"

printf '12345.67 67890.12\n' > "$ROOT/proc/uptime"
printf 'Linux version 4.9.0-fixture (fixture@host) #1 SMP PREEMPT\n' > "$ROOT/proc/version"
printf 'console=ttyS0 root=/dev/ram0 fixture=1\n' > "$ROOT/proc/cmdline"
printf 'Character devices:\n  1 mem\n248 usb\n249 stream\n\nBlock devices:\n  8 sd\n' > "$ROOT/proc/devices"
printf 'fixture_core 1234 1 -, Live 0x00000000\nfixture_aux 42 0 -, Live 0x00000000\n' > "$ROOT/proc/modules"

cat > "$ROOT/proc/149/status" <<'EOF'
Name:   im.elf
State:  S (sleeping)
Tgid:   149
Pid:    149
PPid:   1
Threads:        175
VmSize:    123456 kB
VmRSS:      45678 kB
VmLib:       1234 kB
CapEff: 0000003fffffffff
NoNewPrivs:     0
Seccomp:        0
EOF

cat > "$ROOT/proc/149/maps" <<'EOF'
00008000-0009f000 r-xp 00000000 00:00 0          /fixture/im.elf
01000000-01040000 rw-p 00000000 00:00 0          /fixture/libObj.so
02000000-02010000 r-xp 00000000 00:00 0          /fixture/libInfraUsbCmn.so
03000000-03002000 rw-p 00000000 00:00 0          /fixture/libptp.so
04000000-04001000 rw-p 00000000 00:00 0          /fixture/unrelated.so
EOF

ln -s /dev/stream  "$ROOT/proc/149/fd/9"
ln -s /dev/stream2 "$ROOT/proc/149/fd/23"
printf 'x' > "$ROOT/proc/149/fd/0"
: > "$ROOT/proc/149/task/149"
: > "$ROOT/proc/149/task/150"
: > "$ROOT/proc/149/task/151"

# one masked (address 0) symbol exercises the restricted path
printf '00001000 T usb_gadgetcore_register_driver\n00002000 T osal_snd_msg\n' > "$ROOT/proc/kallsyms"
printf '00000000 T osal_rcv_msg_tmo\n00003000 t unrelated_symbol\n' >> "$ROOT/proc/kallsyms"

printf 'qid=0x0167046a ascii\n\152\004\147\001 raw little endian\nqid 0x00CA8192\n' > "$ROOT/proc/osal/uipc"
printf 'minfo fixture header\n' > "$ROOT/proc/osal/minfo"
printf 'ulogio fixture header\n' > "$ROOT/proc/osal/ulogio"

printf 'configured\n' > "$ROOT/sys/class/udc/dwc3.0/state"
printf 'high-speed\n' > "$ROOT/sys/class/udc/dwc3.0/current_speed"
printf 'super-speed\n' > "$ROOT/sys/class/udc/dwc3.0/maximum_speed"
printf '1\n' > "$ROOT/sys/class/udc/dwc3.0/active"

: > "$ROOT/dev/usb/event"
: > "$ROOT/dev/uipc"
: > "$ROOT/dev/stream"
: > "$ROOT/dev/stream2"
: > "$ROOT/dev/dmpgles2"
echo FIXTURE_READY
'''


def load_validator():
    if not VALIDATOR.is_file():
        fail(f'missing validator: {VALIDATOR}')
    spec = importlib.util.spec_from_file_location('probe_report_validator', VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def host_compiler():
    """Return (kind, description) for an available x86-64 compiler.

    This image ships gcc-15's x86-64 cc1/as/ld but no gcc driver, so the driver is
    preferred when present and cc1 is the documented fallback.
    """
    driver = wsl(['bash', '-c', 'command -v cc gcc clang x86_64-linux-gnu-gcc tcc || true'],
                 timeout=60)
    for candidate in driver.stdout_text.split():
        return {'kind': 'driver', 'path': candidate}
    cc1 = wsl(['bash', '-c', 'ls -1 /usr/libexec/gcc/x86_64-linux-gnu/*/cc1 2>/dev/null'],
              timeout=60)
    candidates = [line.strip() for line in cc1.stdout_text.splitlines() if line.strip()]
    if not candidates:
        fail('no x86-64 C compiler in WSL (no cc/gcc/clang driver and no cc1); '
             'install a host compiler or run --host-check on a machine that has one')
    as_tool = wsl(['bash', '-c', 'command -v x86_64-linux-gnu-as || command -v as || true'],
                  timeout=60).stdout_text.strip()
    ld_tool = wsl(['bash', '-c', 'command -v x86_64-linux-gnu-ld || command -v ld || true'],
                  timeout=60).stdout_text.strip()
    if not as_tool or not ld_tool:
        fail('no x86-64 assembler/linker in WSL')
    return {'kind': 'cc1', 'cc1': candidates[0], 'as': as_tool, 'ld': ld_tool}


def host_check(output_dir):
    validator = load_validator()
    if not SOURCE.is_file():
        fail(f'missing source: {SOURCE}')
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    host_dir = out_dir / 'host-check'
    host_dir.mkdir(parents=True, exist_ok=True)

    made = wsl(['bash', '-c', 'mktemp -d /tmp/uvc_dma_probe_host.XXXXXX'], timeout=60)
    root = made.stdout_text.strip()
    if made.returncode != 0 or not root.startswith('/tmp/uvc_dma_probe_host.'):
        fail('could not create a WSL fixture directory: ' + made.combined[:400])
    print(f'host-check fixture: {root}')

    setup_path = f'{root}/setup.sh'
    write = wsl(['bash', '-c', f"cat > '{setup_path}'"], input_text=FIXTURE_SETUP, timeout=60)
    if write.returncode != 0:
        fail('could not write the fixture setup script: ' + write.combined[:400])
    setup = wsl(['bash', setup_path, root], timeout=60)
    if setup.returncode != 0 or 'FIXTURE_READY' not in setup.stdout_text:
        fail('fixture setup failed: ' + setup.combined[:600])

    compiler = host_compiler()
    binary = f'{root}/uvc_dma_probe_host'
    src = linux_path(SOURCE)
    common = ['-O2', '-Wall', '-Wextra', '-Werror', '-fno-stack-protector',
              '-ffreestanding', '-fno-pie', '-DPROBE_HOST_STUB',
              f'-DPROBE_HOST_ROOT=' + '"' + root + '"']
    steps = []
    if compiler['kind'] == 'driver':
        steps.append([compiler['path'], *common, '-static', '-nostdlib',
                      '-Wl,-e,_start', '-o', binary, src])
    else:
        asm = f'{root}/probe.s'
        obj = f'{root}/probe.o'
        steps.append([compiler['cc1'], '-quiet', *common, '-o', asm, src])
        steps.append([compiler['as'], asm, '-o', obj])
        steps.append([compiler['ld'], '-static', '-nostdlib', '-o', binary, obj, '-e', '_start'])
    ran = []
    for step in steps:
        result = wsl(step, timeout=180)
        ran.append(' '.join(step))
        if result.returncode != 0:
            fail('host compile step failed: ' + ' '.join(step) + '\n' + result.combined[:2000])

    help_run = wsl([binary, '--help'], timeout=60)
    if help_run.returncode != 0 or 'usage: uvc_dma_probe' not in help_run.stdout_text:
        fail(f'--help did not behave: exit {help_run.returncode}')

    smoke = wsl([binary, '--out', '/out/report.json'], timeout=120)
    if smoke.returncode not in (0, 2):
        fail(f'smoke run failed: exit {smoke.returncode}\n{smoke.combined[:2000]}')
    report_path = f'{root}/out/report.json'
    raw = wsl(['cat', report_path], timeout=60)
    if raw.returncode != 0 or not raw.stdout.strip():
        fail('smoke run produced no report')
    try:
        report = json.loads(raw.stdout)
    except json.JSONDecodeError as exc:
        fail(f'smoke report is not JSON: {exc}')
    try:
        validator.validate_report(report)
    except Exception as exc:   # validator raises ReportError(ValueError)
        fail(f'smoke report failed validation: {exc}')

    # keep the artefacts this host check produced (the report is generated, not committed)
    report_text = json.dumps(report, indent=2) + '\n'
    (host_dir / 'help.txt').write_bytes(help_run.stdout_text.encode('utf-8'))
    (host_dir / 'report.json').write_bytes(report_text.encode('utf-8'))
    manifest = {
        'status': 'host_fixture_verified',
        'camera_access': False,
        'deployed': False,
        'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'source': {'path': SOURCE.relative_to(ROOT).as_posix(),
                   'bytes': SOURCE.stat().st_size, 'sha256': sha256_file(SOURCE)},
        'fixture': {
            'root': root,
            'note': 'synthetic values only; no camera data was involved',
            'kind': 'proc/sys/dev tree with regular files standing in for device nodes',
        },
        'compiler': compiler,
        'compile_steps': ran,
        'host_flags': common,
        'results': {
            'help_exit': help_run.returncode,
            'smoke_exit': smoke.returncode,
            'report_schema': report.get('schema'),
            'report_sha256': hashlib.sha256(report_text.encode()).hexdigest(),
            'smoke_notes': report.get('notes'),
            'kallsyms_hits': sorted(k for k, v in report['kallsyms']['symbols'].items() if v),
            'uipc_counts': report['uipc']['counts'],
            'exit_code_in_report': report.get('exit_code'),
        },
        'limitations': [
            'The fixture run proves argument parsing, bounded reads, and JSON emission only.',
            'Regular files stand in for /dev nodes, so major:minor is 0:0 in this report.',
            'No syscall or ioctl path was exercised against real camera hardware.',
        ],
    }
    (host_dir / 'manifest.json').write_bytes((json.dumps(manifest, indent=2) + '\n').encode('utf-8'))

    removed = wsl(['bash', '-c', f'rm -rf "{root}"'], timeout=60)
    print(f'host-check report: {(host_dir / "report.json").relative_to(ROOT).as_posix()} '
          f'(sha256 {manifest["results"]["report_sha256"]})')
    print(f'help exit {help_run.returncode}, smoke exit {smoke.returncode}, '
          f'validation ok, fixture removed={removed.returncode == 0}')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--host-check', action='store_true',
                        help='compile and smoke-run the host fixture build instead of the ARM build')
    parser.add_argument('--all', action='store_true', help='ARM build and host check')
    parser.add_argument('--output-dir', type=Path, default=PROBES / 'build',
                        help='output directory (default probes/build)')
    args = parser.parse_args()
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    if args.all:
        build_arm(output_dir)
        host_check(output_dir)
    elif args.host_check:
        host_check(output_dir)
    else:
        build_arm(output_dir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
