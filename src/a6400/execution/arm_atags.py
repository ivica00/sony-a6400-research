"""ARM ATAGS builder/parser for the CXD90045 update and main boot contract.

The a6400 boot set splits the boot handoff into (a) kernel load, (b) initrd load and
(c) a boot-parameter block: nflasha1 ``boot/loadaddr.txt`` is
``0x00108000,0x00700000,0x00103000`` and the live nflasha3 cmdline carries
``initrd=0x700000,8M``.  The third address is the ATAGS block the loader leaves for the
kernel; the updater kernel parses it in ``setup_machine_tags`` after
``__lookup_machine_type`` reads the machine ID from r1.

This module only *constructs and parses* the standard ARM tag list (ATAG_CORE,
ATAG_MEM, ATAG_CMDLINE, ATAG_NONE) from observed inputs.  It is a reconstruction:
the loader-derived bytes at ``0x00103000`` are not present in any read-only dump, so
the tag order/values are validated by kernel boot progress, not by a captured image.
"""
from __future__ import annotations

import struct

ATAG_NONE = 0x00000000
ATAG_CORE = 0x54410001
ATAG_MEM = 0x54410002
ATAG_VIDEOTEXT = 0x54410003
ATAG_RAMDISK = 0x54410004
ATAG_INITRD = 0x54410005
ATAG_SERIAL = 0x54410006
ATAG_REVISION = 0x54410007
ATAG_VIDEOLFB = 0x54410008
ATAG_CMDLINE = 0x54410009

DEFAULT_BOOT_PARAMS = 0x00103000
KERNEL_LOAD = 0x00108000
INITRD_LOAD = 0x00700000

#: Byte sizes for the observed ``mem=`` syntax (K/M/G, power of two).
_SUFFIX = {'': 1, 'K': 1024, 'M': 1024 * 1024, 'G': 1024 * 1024 * 1024}


class AtagsError(ValueError):
    """The tag list is malformed or does not match the observed contract."""


def parse_size(text: str) -> int:
    """Parse ``1G`` / ``1016M`` / ``0x1000`` into bytes."""
    text = text.strip()
    if not text:
        raise AtagsError('empty size')
    suffix = ''
    if text[-1] in 'KkMmGg':
        suffix = text[-1].upper()
        text = text[:-1]
    try:
        value = int(text, 0)
    except ValueError as error:
        raise AtagsError(f'bad size {text!r}: {error}') from error
    if value < 0:
        raise AtagsError('negative size')
    return value * _SUFFIX[suffix]


def parse_mem_parameters(cmdline: str) -> list[dict]:
    """Parse observed ``mem=SIZE@START[@NODE]`` options into memory banks.

    The a6400 kernel cmdlines use ``mem=1G@0`` and ``mem=1016M@0x80000000@1``.
    ``memrsv=`` reservations are returned separately, not as banks.
    """
    banks = []
    reservations = []
    for token in cmdline.split():
        if token.startswith('mem='):
            body = token[4:]
        elif token.startswith('memrsv='):
            body = token[7:]
        else:
            continue
        fields = body.split('@')
        if len(fields) < 2:
            raise AtagsError(f'{token!r}: expected SIZE@START')
        size = parse_size(fields[0])
        start_field = fields[1]
        attributes = []
        if ':' in start_field:
            start_field, _, attribute_text = start_field.partition(':')
            attributes = [item for item in attribute_text.split(',') if item]
        try:
            start = int(start_field, 0)
        except ValueError as error:
            raise AtagsError(f'{token!r}: bad start address: {error}') from error
        record = {'start': start, 'size': size}
        if attributes:
            record['attributes'] = attributes
        if len(fields) > 2 and fields[2]:
            try:
                record['node'] = int(fields[2], 0)
            except ValueError as error:
                raise AtagsError(f'{token!r}: bad node: {error}') from error
        if token.startswith('memrsv='):
            reservations.append(record)
        else:
            banks.append(record)
    # Merge banks with the same start keeping the larger size (the kernel does the
    # same for a cmdline/ATAG duplicate); keep declaration order otherwise.
    merged: list[dict] = []
    for bank in banks:
        for existing in merged:
            if existing['start'] == bank['start']:
                existing['size'] = max(existing['size'], bank['size'])
                break
        else:
            merged.append(dict(bank))
    return merged + [dict(record, reserved=True) for record in reservations]


def build_atags(cmdline: str | bytes, memory_banks: list[tuple[int, int]],
                *, core: tuple[int, int, int] = (0, 0, 0),
                boot_params: int = DEFAULT_BOOT_PARAMS) -> bytes:
    """Build a standard ATAG list (CORE, MEM*, CMDLINE, NONE)."""
    if isinstance(cmdline, str):
        cmdline = cmdline.encode('utf-8')
    if not memory_banks:
        raise AtagsError('at least one memory bank is required')
    tags = bytearray()
    # ATAG_CORE: {size=5, tag, flags, pagesize, rootdev}
    tags += struct.pack('<5I', 5, ATAG_CORE, core[0], core[1], core[2])
    for start, size in memory_banks:
        if start < 0 or size <= 0 or start + size > 0x100000000:
            raise AtagsError(f'invalid memory bank 0x{start:x}+0x{size:x}')
        # ATAG_MEM: {size=4, tag, start, size}
        tags += struct.pack('<4I', 4, ATAG_MEM, start, size)
    payload = cmdline + b'\x00'
    padded = (len(payload) + 3) & ~3
    tags += struct.pack('<2I', 2 + padded // 4, ATAG_CMDLINE) + payload.ljust(padded, b'\x00')
    tags += struct.pack('<2I', 0, ATAG_NONE)
    return bytes(tags)


def parse_atags(blob: bytes, *, limit: int = 0x4000, base: int = DEFAULT_BOOT_PARAMS) -> list[dict]:
    """Parse and validate a tag list (bounds, word alignment, terminator)."""
    if len(blob) > limit:
        raise AtagsError(f'tag list longer than {limit} bytes')
    tags = []
    offset = 0
    while offset + 8 <= len(blob):
        size, tag = struct.unpack_from('<2I', blob, offset)
        if tag == ATAG_NONE:
            tags.append({'tag': ATAG_NONE, 'size': 0, 'offset': offset})
            return tags
        if size < 2 or size > (len(blob) - offset) // 4:
            raise AtagsError(f'tag 0x{tag:08x} at 0x{offset:x}: bad word size {size}')
        body = blob[offset + 8:offset + size * 4]
        record = {'tag': tag, 'size': size, 'offset': offset, 'body': body}
        if tag == ATAG_CORE:
            if size != 5:
                raise AtagsError('ATAG_CORE must be 5 words')
            flags, pagesize, rootdev = struct.unpack('<3I', body)
            record.update(flags=flags, pagesize=pagesize, rootdev=rootdev)
        elif tag == ATAG_MEM:
            if size != 4:
                raise AtagsError('ATAG_MEM must be 4 words')
            start, length = struct.unpack('<2I', body)
            record.update(start=start, bytes=length)
        elif tag == ATAG_CMDLINE:
            raw = body.split(b'\x00', 1)[0]
            record['cmdline'] = raw.decode('latin1')
        tags.append(record)
        offset += size * 4
    raise AtagsError('tag list has no ATAG_NONE terminator within the bounded blob')


def atags_receipt(blob: bytes, *, base: int = DEFAULT_BOOT_PARAMS) -> dict:
    """Machine-readable summary of a built tag list."""
    tags = parse_atags(blob, base=base)
    banks = [{'start': tag['start'], 'size': tag['bytes']}
             for tag in tags if tag['tag'] == ATAG_MEM]
    cmdline = next((tag['cmdline'] for tag in tags if tag['tag'] == ATAG_CMDLINE), '')
    return {'address': base, 'bytes': len(blob),
            'tags': [{'tag': tag['tag'], 'size': tag['size'], 'offset': tag['offset']}
                     for tag in tags],
            'memory_banks': banks, 'cmdline': cmdline}
