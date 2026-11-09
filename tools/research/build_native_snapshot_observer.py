"""Build a bounded native observer with the existing Sony libc toolchain."""
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version', choices=['v7', 'v8', 'v9', 'v10', 'v11', 'v12', 'touch_geometry'])
    args = parser.parse_args()
    stem = 'native_layout_resource_snapshot_' + args.version
    if args.version == 'touch_geometry': stem = 'native_touch_geometry'
    source = 'tools/native_camera/' + stem + '.c'
    output = 'devcrashday_a6400/' + stem + '.elf'
    compiler = ['arm-linux-gnueabi-gcc'] if os.name == 'posix' else ['wsl.exe', '--cd', '/mnt/' + ROOT.drive[0].lower() + ROOT.as_posix()[2:], '--exec', 'arm-linux-gnueabi-gcc']
    flags = '-std=gnu11 -march=armv7-a -mfloat-abi=softfp -O2 -Wall -Wextra -Werror -nostdlib -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=0 -U_TIME_BITS -D_TIME_BITS=32 -U_FILE_OFFSET_BITS -D_FILE_OFFSET_BITS=32 -fno-stack-protector'.split()
    subprocess.run(compiler + flags + ['-Wl,-e,_start,-z,defs,-z,max-page-size=4096,--dynamic-linker=/lib/ld-linux.so.3', '-o', output, 'tools/native_camera/snapshot_start.S', source, 'tools/sony_sysroot/lib/libc.so', '-lgcc'], cwd=ROOT, check=True)
    manifest = {'deployed': False, 'files': {}}
    for name in [source, 'tools/native_camera/native_freeze.h', 'tools/native_camera/snapshot_start.S', output]:
        raw = (ROOT / name).read_bytes()
        manifest['files'][name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    if args.version == 'touch_geometry':
        name = 'tools/native_camera/native_layout_resource_snapshot_v12.c'
        raw = (ROOT / name).read_bytes()
        manifest['files'][name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    path = ROOT / 'artifacts/analysis' / (stem + '-build.json')
    path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(path)
if __name__ == '__main__': main()
