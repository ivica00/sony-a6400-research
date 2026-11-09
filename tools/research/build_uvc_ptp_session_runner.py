"""Build self-contained UVC/PTP session runner for ARM using Sony libc."""
import argparse, hashlib, json, os, subprocess
from pathlib import Path
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', required=True, type=Path)
    out = p.parse_args().output_dir.resolve()
    if not out.is_relative_to(ROOT / 'artifacts'):
        p.error('Output must be under artifacts')
    out.mkdir(parents=True, exist_ok=True)
    target = out / 'uvc_ptp_session_runner.elf'
    source = ROOT / 'tools/native_camera/uvc_ptp_session_runner.c'

    flags = '-std=gnu11 -march=armv7-a -mfloat-abi=softfp -O2 -Wall -Wextra -Werror -nostdlib -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=0 -U_TIME_BITS -D_TIME_BITS=32 -U_FILE_OFFSET_BITS -D_FILE_OFFSET_BITS=32 -fno-stack-protector'.split()
    cmd = [
        'arm-linux-gnueabi-gcc', *flags,
        '-Wl,-e,_start,-z,defs,-z,max-page-size=4096,--dynamic-linker=/lib/ld-linux.so.3',
        '-o', target.relative_to(ROOT).as_posix(),
        'tools/native_camera/snapshot_start.S',
        source.relative_to(ROOT).as_posix(),
        'tools/sony_sysroot/lib/libc.so',
        '-lgcc'
    ]
    if os.name == 'nt':
        cmd = ['wsl.exe', '--cd', '/mnt/' + ROOT.drive[0].lower() + ROOT.as_posix()[2:], '--exec', *cmd]
    subprocess.run(cmd, cwd=ROOT, check=True)

    files = [
        source,
        ROOT / 'tools/native_camera/native_freeze.h',
        ROOT / 'tools/native_camera/uvc_ptp_runner_stop.h',
        ROOT / 'tools/native_camera/uvc_ptp_stop_attest.h',
        ROOT / 'tools/native_camera/uvc_ptp_entry_hook.h',
        ROOT / 'tools/native_camera/snapshot_start.S',
        ROOT / 'tools/sony_sysroot/lib/libc.so',
        target
    ]
    report = dict(
        status='built_not_deployed',
        camera_access=False,
        build_command=cmd,
        files={str(p.relative_to(ROOT)): dict(bytes=p.stat().st_size, sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in files},
        scope='Standalone composite session runner: publish -> init -> hold -> stop -> retire'
    )
    (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
