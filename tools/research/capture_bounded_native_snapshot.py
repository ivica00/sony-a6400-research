"""Archive a small CPU-thread-consistent native subset, never an application call."""
import argparse
import hashlib
import json
import re
import struct
from tools.camera_debugger import connect
from tools.research.active_menu_snapshot_probe import ROOT, HW
from tools.research.decode_native_layout_snapshot import decode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--range', action='append', required=True, dest='ranges', help='user address:size, both decimal or hex')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.label): raise ValueError('Label must be a simple artifact basename')
    ranges = [tuple(int(part, 0) for part in item.split(':')) for item in args.ranges]
    if not 1 <= len(ranges) <= 64 or any(len(item) != 2 for item in ranges): raise ValueError('Range count/format')
    if any(not 0 < size <= 0x186bc or not 0x14000 <= address < address + size <= 0x5f000000 for address, size in ranges) or sum(size for _, size in ranges) > 128*1024:
        raise ValueError('Capture exceeds native bounds')
    base = HW / args.label
    if base.with_suffix('.json').exists(): raise FileExistsError('Use a new label to preserve evidence')
    request = struct.pack('<4I', 0x52444d41, 1, len(ranges), 0) + b''.join(struct.pack('<2I', *item) for item in ranges)
    binary = (ROOT / 'devcrashday_a6400/native_bounded_snapshot.elf').read_bytes()
    manifest = dict(requested_ranges=[dict(address=hex(a), size=n) for a, n in ranges],
                    payload_sha256=hashlib.sha256(binary).hexdigest(), request_sha256=hashlib.sha256(request).hexdigest(),
                    application_calls=False, application_memory_writes=False, dma_atomic=False)
    with connect() as debugger:
        for remote, raw in [('/setting/native_bounded_snapshot.elf', binary), ('/setting/native_bounded_snapshot.req', request)]:
            debugger.push(remote, raw)
            actual, truncated = debugger.read_all(remote)
            if truncated or actual != raw: raise ValueError('Read-back mismatch')
        result = debugger.request(3, b'chmod 755 /setting/native_bounded_snapshot.elf; /setting/native_bounded_snapshot.elf')
        manifest.update(status=result['status'], flags=result['flags'], log=result['payload'].decode())
        base.with_suffix('.log').write_text(manifest['log'], encoding='utf-8')
        base.with_name(base.name + '-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print(manifest['log'])
        if result['status'] or result['flags'] or 'END result=0' not in manifest['log']:
            raise ValueError('Native capture/resume/output did not complete')
        raw, truncated = debugger.read_all('/tmp_bt/native_bounded_snapshot.bin', 132*1024)
        base.with_suffix('.bin').write_bytes(raw)
        if truncated: raise ValueError('Native snapshot truncated')
    capture = decode(raw)
    if [(int(row['address'], 16), row['size']) for row in capture['records']] != ranges:
        raise ValueError('Snapshot differs from requested ranges')
    capture.update(cpu_threads_stopped_during_capture=True, dma_atomic=False, whole_application_snapshot=False)
    base.with_suffix('.json').write_text(json.dumps(capture, indent=2), encoding='utf-8')
    print('Archived', len(raw), 'bytes', capture['sha256'])


if __name__ == '__main__': main()
