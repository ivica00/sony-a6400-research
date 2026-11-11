#!/bin/sh
# Build the camera-side daemon as a statically linked ARM (armel, softfp) binary.
#
# Driven from Windows through WSL, e.g.
#   wsl -d Ubuntu -- bash -lc "cd '/mnt/c/.../camera-daemon' && ./build.sh"
# or through the Makefile (`make arm` / `mingw32-make arm`).
#
# Nothing here touches a camera: this is a host build only. The output manifest
# records status "built_not_deployed" so the artifact cannot be mistaken for a
# verified camera binary.
set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$here"

CC=${CC:-arm-linux-gnueabi-gcc}
CFLAGS=${CFLAGS:-"-std=gnu11 -march=armv7-a -mfloat-abi=softfp -O2 -Wall -Wextra -Werror -Iinclude"}
OUT=${OUT:-build/a6400-lived}

command -v "$CC" >/dev/null 2>&1 || {
    echo "build.sh: compiler not found: $CC" >&2
    echo "build.sh: install gcc-arm-linux-gnueabi (armel, softfp) first" >&2
    exit 1
}

mkdir -p build

# Every source in src/ is part of the daemon; there are no optional objects.
# shellcheck disable=SC2086
"$CC" $CFLAGS -o "$OUT" src/*.c -static

chmod 0755 "$OUT"

SIZE=$(wc -c < "$OUT" | tr -d ' ')
SHA=$(sha256sum "$OUT" | cut -d' ' -f1)
VER=$("$CC" --version | head -n 1)

if ! command -v python3 >/dev/null 2>&1; then
    echo "build.sh: python3 is required to write build/manifest.json" >&2
    exit 1
fi

python3 - "$OUT" "$SIZE" "$SHA" "$VER" "$CFLAGS" <<'PY'
import hashlib
import json
import os
import sys

out, size, sha, compiler, flags = sys.argv[1:6]
sources = sorted(p for p in os.listdir('src') if p.endswith('.c'))
manifest = {
    'status': 'built_not_deployed',
    'camera_access': False,
    'binary': out,
    'bytes': int(size),
    'sha256': sha,
    'linkage': 'static',
    'target': 'armv7-a softfp (ARM EABI, Linux)',
    'compiler': compiler,
    'flags': flags,
    'sources': ['src/' + p for p in sources],
    'limitations': [
        'Offline host build only. Never deployed, never executed on a camera.',
        'The composite transport it drives is unauditable today (boundary B5) and its '
        'START bridge matches only EP 0x81 while the composite descriptor advertises 0x84 '
        '(boundary B3), so a successful build is not evidence that frames would stream.',
        'WAIT (0xf002) semantics are undecoded (boundary B4); the daemon bounds the call '
        'with an interval timer but cannot bound an uninterruptible kernel sleep.',
    ],
}
with open(os.path.join('build', 'manifest.json'), 'w', encoding='utf-8', newline='\n') as handle:
    json.dump(manifest, handle, indent=2, sort_keys=True)
    handle.write('\n')
PY

echo "built $OUT"
echo "  bytes  $SIZE"
echo "  sha256 $SHA"
echo "  cc     $VER"
