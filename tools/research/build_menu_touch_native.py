"""Build native binding code for offline ARM execution; never deploys it."""
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    compiler = ['arm-linux-gnueabi-gcc'] if os.name == 'posix' else [
        'wsl.exe', '--cd', '/mnt/'+ROOT.drive[0].lower()+ROOT.as_posix()[2:],
        '--exec', 'arm-linux-gnueabi-gcc']
    output = 'devcrashday_a6400/menu_touch_native.elf'
    flags = ('-std=gnu11 -march=armv7-a -mthumb -mfpu=vfpv3-d16 -mfloat-abi=softfp '
             '-Os -Wall -Wextra -Werror -nostdlib -ffreestanding -fno-builtin '
             '-fno-stack-protector -fomit-frame-pointer -fno-unwind-tables '
             '-fno-asynchronous-unwind-tables').split()
    subprocess.run(compiler+flags+['-Wl,-Ttext=0x0700d708,-e,mt_native_context,--build-id=none',
        '-o', output, 'tools/native_camera/menu_touch_native.c'], cwd=ROOT, check=True)
    raw = (ROOT/output).read_bytes()
    report = dict(deployed=False, scope=__doc__, elf_sha256=hashlib.sha256(raw).hexdigest())
    (ROOT/'artifacts/analysis/menu-touch-native-build-e0131.json').write_text(json.dumps(report, indent=2))
    print('Built offline native bindings; not installed')


if __name__ == '__main__':
    main()
