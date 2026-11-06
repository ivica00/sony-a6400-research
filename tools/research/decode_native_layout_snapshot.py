"""Validate a complete bounded native layout snapshot before using its bytes."""
import argparse
import hashlib
import json
import struct
from pathlib import Path


def decode(data):
    if len(data) < 16:
        raise ValueError('Truncated snapshot header')
    magic, version, count, size = struct.unpack_from('<4I', data)
    if magic != 0x534c4159 or version != 2 or count > 2048 or size > 512 * 1024:
        raise ValueError('Unsupported or out-of-bounds snapshot header')
    start = 16 + count * 12
    if len(data) != start + size:
        raise ValueError('Snapshot length does not match the declared complete payload')
    records, seen = [], {}
    for i in range(count):
        address, length, offset = struct.unpack_from('<3I', data, 16 + i * 12)
        if not 0 < length <= 0x186bc or offset + length > size or not 0x14000 <= address < address + length <= 0x5f000000:
            raise ValueError('Invalid snapshot record range')
        raw = data[start + offset:start + offset + length]
        for j, value in enumerate(raw):
            if address + j in seen and seen[address + j] != value:
                raise ValueError('Conflicting non-atomic snapshot bytes at ' + hex(address + j))
            seen[address + j] = value
        records.append(dict(address=hex(address), size=length, data=raw.hex()))
    return dict(atomic=False, complete_binary=True, raw_bytes=size,
                sha256=hashlib.sha256(data).hexdigest(), records=records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = decode(args.binary.read_bytes())
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(dict(records=len(report['records']), raw_bytes=report['raw_bytes'], sha256=report['sha256']), indent=2))


if __name__ == '__main__':
    main()
