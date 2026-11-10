"""Build the read-only display capture helper against the preserved Sony libc.

Offline only: this script compiles and hashes the helper.  It does not upload,
run or otherwise touch the camera.
"""
import hashlib
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    if os.name == 'posix':
        compiler = ['arm-linux-gnueabi-gcc']
    else:
        linux_root = '/mnt/' + ROOT.drive[0].lower() + ROOT.as_posix()[2:]
        compiler = ['wsl.exe', '--cd', linux_root, '--exec', 'arm-linux-gnueabi-gcc']
    common = ['-std=gnu11', '-march=armv7-a', '-mfloat-abi=softfp', '-O2',
              '-Wall', '-Wextra', '-Werror', '-nostdlib', '-U_FORTIFY_SOURCE',
              '-D_FORTIFY_SOURCE=0', '-U_TIME_BITS', '-D_TIME_BITS=32',
              '-U_FILE_OFFSET_BITS', '-D_FILE_OFFSET_BITS=32']
    executable = 'devcrashday_a6400/capture_display_readonly.elf'
    (ROOT / executable).parent.mkdir(parents=True, exist_ok=True)
    command = compiler + common + [
        '-fno-stack-protector',
        '-Wl,-e,_start,-z,defs,-z,max-page-size=4096,--dynamic-linker=/lib/ld-linux.so.3',
        '-o', executable,
        'tools/native_camera/debug_start.S',
        'tools/native_camera/capture_display_readonly.c',
        'tools/sony_sysroot/lib/libc.so', '-lgcc',
    ]
    print(' '.join(command))
    try:
        subprocess.run(command, check=True, cwd=ROOT)
    except subprocess.CalledProcessError as error:
        raise SystemExit('Build failed; if WSL reports E_ACCESSDENIED, run the printed '
                         'command from an interactive shell.') from error
    paths = [executable, 'tools/native_camera/capture_display_readonly.c',
             'tools/native_camera/debug_start.S', 'tools/sony_sysroot/lib/libc.so']
    manifest = {'deployed': False, 'files': {}}
    for path in paths:
        data = (ROOT / path).read_bytes()
        manifest['files'][path] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    destination = ROOT / 'artifacts/analysis' / (
        'capture-display-readonly-build-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.json')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(destination)


if __name__ == '__main__':
    main()
