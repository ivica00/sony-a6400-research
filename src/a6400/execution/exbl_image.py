"""Read-only EXBL boot-container parser (nflashaB0 boot area).

The a6400 boot area (``/dev/nflashaB0``, 252:126, 4 MiB) starts with a
0x200-byte EXBL container header: the u32 magic ``0x4C425845`` ("EXBL" bytes
45 58 42 4C) followed by seven 0x40-byte segment records.  The record field
offsets below were decoded from the updater's preserved ``pformat.elf``
(``firmware/extracted_a6400/updater.img_unpacked/bin/pformat.elf``), whose .data
key table at vaddr ``0x118d8`` maps config keys to record offsets::

    key                  offset  pformat string address
    start                0x00    0x962a
    size                 0x04    0x942c
    verstr               0x0c    0x960b
    load                 0x10    0x9606
    entry                0x14    0x9644
    awake_cmd0disable    0x24    0x9612
    awake_start          0x28    0x9624
    awake_memaddr        0x2c    0x9630
    awake_entry          0x30    0x963e
    awake_loadsize       0x34    0x964a
    bp_entry             0x38    0x9659
    bp_loadsize          0x3c    0x9662

``pformat.elf`` writes the 0x200-byte block (memset 0x200, magic at +0, then
seven records at ``0x40 + index*0x40``) and a parallel 7 x 0x24 file_param
array holding the source path/update flag per segment.

Observed semantics on the 2026-11-12 nflashaB0 dump (six used records):
``start``/``size`` are in 512-byte sectors; ``load = load_base + start*512`` for
all six records with ``load_base = record0.awake_memaddr = 0xFE040000``;
``entry`` names the per-segment execution address and record0's entry
``0xFE047000`` is the ARM reset vector table (``b`` to 0xFE047058).  This is
read-only parsing: no bytes are written to any image.
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

EXBL_MAGIC = 0x4C425845
EXBL_MAGIC_BYTES = b'EXBL'
BLOCK_SIZE = 0x200
RECORD_SIZE = 0x40
RECORD_COUNT = 7
SECTOR_SIZE = 512
DEFAULT_LOAD_BASE = 0xFE040000

#: Record field offsets decoded from pformat.elf (see module docstring).
FIELD_OFFSETS = {
    'start': 0x00,
    'size': 0x04,
    'verstr': 0x0C,
    'load': 0x10,
    'entry': 0x14,
    'awake_cmd0disable': 0x24,
    'awake_start': 0x28,
    'awake_memaddr': 0x2C,
    'awake_entry': 0x30,
    'awake_loadsize': 0x34,
    'bp_entry': 0x38,
    'bp_loadsize': 0x3C,
}

#: Boot-mode contract references observed in the loader payload (not the header).
BOOT_CONTRACT_TOKENS = {
    'boot_mode_backup_record_0x0051000F': struct.pack('<I', 0x0051000F),
    'boot_mode_log_string': b'BOM:<<BootMode:',
    'updater_mode_path': b'\\updater\\mode',
    'fat_mount_string': b'fat_mount',
}


class ExblError(ValueError):
    """The image is not a valid EXBL container."""


def _u32(raw: bytes, offset: int) -> int:
    return struct.unpack_from('<I', raw, offset)[0]


class ExblRecord:
    """One 0x40-byte segment record from the EXBL block."""

    __slots__ = ('index', 'raw', 'load_base')

    def __init__(self, index: int, raw: bytes, load_base: int):
        if len(raw) != RECORD_SIZE:
            raise ExblError(f'record {index}: expected {RECORD_SIZE} bytes')
        self.index = index
        self.raw = raw
        self.load_base = load_base

    def value(self, name: str) -> int:
        return _u32(self.raw, FIELD_OFFSETS[name])

    @property
    def start(self) -> int:
        """First sector of the segment inside the boot-area partition."""
        return self.value('start')

    @property
    def size(self) -> int:
        """Segment length in 512-byte sectors."""
        return self.value('size')

    @property
    def flash_offset(self) -> int:
        return self.start * SECTOR_SIZE

    @property
    def flash_end(self) -> int:
        return (self.start + self.size) * SECTOR_SIZE

    @property
    def load(self) -> int:
        return self.value('load')

    @property
    def entry(self) -> int:
        return self.value('entry')

    @property
    def awake_cmd0disable(self) -> int:
        return self.value('awake_cmd0disable')

    @property
    def awake_start(self) -> int:
        return self.value('awake_start')

    @property
    def awake_memaddr(self) -> int:
        return self.value('awake_memaddr')

    @property
    def awake_entry(self) -> int:
        return self.value('awake_entry')

    @property
    def awake_loadsize(self) -> int:
        return self.value('awake_loadsize')

    @property
    def bp_entry(self) -> int:
        return self.value('bp_entry')

    @property
    def bp_loadsize(self) -> int:
        return self.value('bp_loadsize')

    @property
    def present(self) -> bool:
        return bool(self.start or self.size)

    @property
    def mapping_consistent(self) -> bool:
        """``load`` equals ``load_base + flash_offset`` when both are set."""
        return not self.load or self.load == self.load_base + self.flash_offset

    def as_dict(self) -> dict:
        return {
            'index': self.index,
            'present': self.present,
            'start_sector': self.start,
            'sector_count': self.size,
            'flash_offset': self.flash_offset,
            'load': self.load,
            'entry': self.entry,
            'awake_cmd0disable': self.awake_cmd0disable,
            'awake_start': self.awake_start,
            'awake_memaddr': self.awake_memaddr,
            'awake_entry': self.awake_entry,
            'awake_loadsize': self.awake_loadsize,
            'bp_entry': self.bp_entry,
            'bp_loadsize': self.bp_loadsize,
            'mapping_consistent': self.mapping_consistent,
        }


class ExblImage:
    """Validated read-only view of an EXBL boot-area container."""

    def __init__(self, image: bytes, *, image_sha256: str | None = None,
                 expected_size: int | None = None):
        if expected_size is not None and len(image) != expected_size:
            raise ExblError(f'image size {len(image)} != expected {expected_size}')
        if len(image) < BLOCK_SIZE:
            raise ExblError(f'image shorter than the {BLOCK_SIZE}-byte EXBL block')
        if image[:4] != EXBL_MAGIC_BYTES:
            raise ExblError('EXBL magic not found at offset 0')
        if _u32(image, 0) != EXBL_MAGIC:
            raise ExblError('EXBL magic word mismatch')
        self.image = image
        self.sha256 = image_sha256
        self.records = []
        # Record 0 carries awake_memaddr, so parse it first with the default base.
        first = ExblRecord(0, image[RECORD_SIZE:2 * RECORD_SIZE], DEFAULT_LOAD_BASE)
        load_base = first.awake_memaddr if first.awake_memaddr >= DEFAULT_LOAD_BASE else DEFAULT_LOAD_BASE
        self.load_base = load_base
        for index in range(RECORD_COUNT):
            start = RECORD_SIZE * (index + 1)
            record = ExblRecord(index, image[start:start + RECORD_SIZE], load_base)
            if record.present and record.flash_end > len(image):
                raise ExblError(f'record {index}: segment exceeds the image '
                                f'({record.flash_end} > {len(image)})')
            self.records.append(record)

    @classmethod
    def from_path(cls, path: str | Path, *, expected_size: int | None = None,
                  expected_sha256: str | None = None) -> 'ExblImage':
        raw = Path(path).read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if expected_sha256 is not None and sha != expected_sha256:
            raise ExblError('boot-area dump identity mismatch')
        return cls(raw, image_sha256=sha, expected_size=expected_size)

    @property
    def segments(self) -> list[ExblRecord]:
        return [record for record in self.records if record.present]

    @property
    def entry(self) -> int:
        for record in self.records:
            if record.entry:
                return record.entry
        for record in self.records:
            if record.load:
                return record.load
        return 0

    @property
    def extent_bytes(self) -> int:
        """Highest ``(start + size) * 512`` over the records."""
        return max((record.flash_end for record in self.records), default=0)

    @property
    def payload_bytes(self) -> int:
        return sum(record.size * SECTOR_SIZE for record in self.records)

    def segment_data(self, index: int) -> bytes:
        record = self.records[index]
        return self.image[record.flash_offset:record.flash_end]

    def mapping_consistent(self) -> bool:
        return all(record.mapping_consistent for record in self.segments)

    def boot_contract_references(self) -> dict:
        """Offsets of the boot-mode/updater tokens inside the partition image."""
        references = {}
        for name, needle in BOOT_CONTRACT_TOKENS.items():
            offsets = []
            start = 0
            while True:
                offset = self.image.find(needle, start)
                if offset < 0:
                    break
                offsets.append(offset)
                start = offset + 1
            references[name] = offsets
        return references

    def summary(self) -> dict:
        return {
            'sha256': self.sha256,
            'bytes': len(self.image),
            'load_base': self.load_base,
            'entry': self.entry,
            'extent_bytes': self.extent_bytes,
            'payload_bytes': self.payload_bytes,
            'records': [record.as_dict() for record in self.records],
            'segments': [record.index for record in self.segments],
            'mapping_consistent': self.mapping_consistent(),
        }


#: Identity of the 2026-11-12 read-only nflashaB0 dump (E0414).
NFLASHA_B0_SIZE = 4194304
NFLASHA_B0_SHA256 = '3db81064bbb62f2af3937bc68adac7b37482a8f3a582734cb2036fd5a3f4d260'
