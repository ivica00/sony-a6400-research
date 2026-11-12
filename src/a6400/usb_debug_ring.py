"""Warm-boot kernel-log ring parser for the a6400 USB debugger (E0401).

The camera kernel keeps its boot log in a fixed physical buffer declared by the
verified kernel command line:

    klog.addr=0x035a5000 klog.size=0x20000

Header (12 bytes, little-endian)::

    magic[4] = b"klog"      # kernel compares its bit distance to "klog"
    u32      write_position # bytes of text written after the header
    u32      wrap           # observed 0; not interpreted unless a wrap is seen

A warm reboot keeps the buffer when the magic survives (at most two differing
bits) and ``write_position`` is inside the capacity; the next boot appends its
own log at the retained position.  This module only parses captured bytes; it
never guesses a different address or invents content.
"""
from __future__ import annotations

import re
import struct
import zlib

MAGIC = b'klog'
MAGIC_WORD = 0x676F6C6B
HEADER_SIZE = 12
DEFAULT_CAPACITY = 0x20000
MAX_MAGIC_BIT_DISTANCE = 2

_BOOT_START = re.compile(rb'(?m)^\[[ 0-9.]+\] WARMBOOT\n')
_KEEP = rb'klog: keep logging buffer'
_INITIALIZE = rb'klog: initialize logging buffer'


class RingFormatError(ValueError):
    """The captured bytes are not a verifiable a6400 klog ring."""


def magic_bit_distance(word: int) -> int:
    """Number of differing bits between a candidate magic and the klog magic."""
    return (word ^ MAGIC_WORD).bit_count()


def parse_header(raw: bytes) -> dict:
    if len(raw) < HEADER_SIZE:
        raise RingFormatError('ring shorter than the 12-byte header')
    magic = raw[:4]
    write_position, wrap = struct.unpack_from('<II', raw, 4)
    distance = magic_bit_distance(struct.unpack_from('<I', raw, 0)[0])
    return {
        'magic': magic.decode('latin1'),
        'magic_hex': raw[:4].hex(),
        'magic_bit_distance': distance,
        'write_position': write_position,
        'wrap': wrap,
    }


def analyze(raw: bytes, capacity: int = DEFAULT_CAPACITY) -> dict:
    """Validate and decode a captured klog ring image.

    ``raw`` is the full captured region (``capacity`` bytes, header first).
    Raises RingFormatError for any identity/range violation; never truncates.
    """
    if not 0 < capacity <= 0x100000:
        raise RingFormatError(f'capacity outside supported range: {capacity}')
    if len(raw) < HEADER_SIZE:
        raise RingFormatError('ring shorter than the header')
    header = parse_header(raw)
    if header['magic_bit_distance'] > MAX_MAGIC_BIT_DISTANCE:
        raise RingFormatError(
            f"magic mismatch: {header['magic_hex']} differs from klog in "
            f"{header['magic_bit_distance']} bits")
    write_position = header['write_position']
    if write_position > capacity:
        raise RingFormatError(
            f'write position {write_position} exceeds capacity {capacity}')
    end = HEADER_SIZE + write_position
    if len(raw) < end:
        raise RingFormatError(
            f'capture holds {len(raw)} bytes but the header claims {end}')
    data = raw[HEADER_SIZE:end]
    crc = zlib.crc32(raw[:end]) & 0xffffffff
    boots = []
    matches = list(_BOOT_START.finditer(data))
    for index, match in enumerate(matches):
        segment_end = matches[index + 1].start() if index + 1 < len(matches) else len(data)
        segment = data[match.start():segment_end]
        boots.append({
            'index': index,
            'offset': match.start(),
            'end': segment_end,
            'bytes': segment_end - match.start(),
            'kept_previous_buffer': _KEEP in segment,
            'initialized_buffer': _INITIALIZE in segment,
        })
    return {
        'valid': True,
        'capacity': capacity,
        'header': header,
        'data_bytes': write_position,
        'crc32': crc,
        'boot_count': len(boots),
        'boots': boots,
        'preamble_bytes': matches[0].start() if matches else len(data),
        'text': data,
    }


def parse_ring_info(text: str) -> dict:
    """Parse the daemon's KLOG_RING_V1 key=value receipt; fail closed."""
    lines = [line for line in text.splitlines() if line]
    if not lines or lines[0] != 'KLOG_RING_V1':
        raise RingFormatError('not a KLOG_RING_V1 receipt')
    values = {}
    for line in lines[1:]:
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key] = value
    if values.get('valid') == '0':
        return {'valid': False, 'error': values.get('error', 'unknown')}
    if values.get('valid') != '1':
        raise RingFormatError('receipt does not state validity')
    for key in ('klog.addr', 'klog.size', 'header.write_position', 'crc32', 'data_bytes'):
        if key not in values:
            raise RingFormatError(f'receipt missing {key}')
    values['klog.address'] = int(values['klog.addr'], 16)
    values['klog.capacity'] = int(values['klog.size'], 16)
    values['header.write_position'] = int(values['header.write_position'], 10)
    values['data_bytes'] = int(values['data_bytes'], 10)
    values['crc32'] = int(values['crc32'], 16)
    values['valid'] = True
    return values


def cross_check(analysis: dict, receipt: dict) -> dict:
    """Cross-check a captured ring against the daemon receipt; raise on mismatch."""
    if not receipt.get('valid'):
        raise RingFormatError('daemon reports an invalid ring: %s' % receipt.get('error'))
    checks = {
        'capacity': analysis['capacity'] == receipt['klog.capacity'],
        'write_position': analysis['header']['write_position'] == receipt['header.write_position'],
        'crc32': analysis['crc32'] == receipt['crc32'],
        'data_bytes': analysis['data_bytes'] == receipt['data_bytes'],
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise RingFormatError('ring/receipt mismatch: ' + ', '.join(failed))
    return {'verified': True, 'checks': checks}
