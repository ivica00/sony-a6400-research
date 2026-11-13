#!/usr/bin/env python3
"""Locate and decode the ``av-cam.bin`` command table of a BIONZ X body.

The table is an array of 16-byte records ``<IIII>`` = (command id, handler address, a 0/1
word, checker address).  This module finds it **by shape**, so the same code works on a
body nobody has looked at before:

* the record's id lies in ``0x4000..0x4200``;
* the handler lies inside the image's mapped range (the image is ORIL-mapped at
  ``0x635c6000`` in every body observed so far, so a handler is ``0x63xxxxxx``);
* the third word is 0 or 1.

The longest contiguous run of records satisfying that shape is the table.  Locating it by
shape rather than by a per-model file offset is what makes a cross-body comparison
possible without copying a constant from one body into another.

Reading the same shape twice is not a claim about behaviour: a decoded table says which
command ids a body *carries*, not which ones its UI can reach.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

ORIL_BASE = 0x635C6000
RECORD = struct.Struct("<IIII")
ID_MIN, ID_MAX = 0x4000, 0x4200
HANDLER_MIN, HANDLER_MAX = 0x63000000, 0x65000000
#: A real table has hundreds of records; a short run is a coincidence inside data.
MIN_RECORDS = 40


@dataclass(frozen=True)
class Command:
    command_id: int
    handler: int
    flag: int
    checker: int

    @property
    def handler_va(self) -> int:
        """Handler address as a file offset relative to the ORIL mapping."""
        return self.handler


@dataclass(frozen=True)
class CommandTable:
    offset: int
    records: tuple[Command, ...]

    def __len__(self) -> int:
        return len(self.records)

    @property
    def ids(self) -> tuple[int, ...]:
        return tuple(r.command_id for r in self.records)

    def get(self, command_id: int) -> Command | None:
        for r in self.records:
            if r.command_id == command_id:
                return r
        return None

    @property
    def zero_handlers(self) -> int:
        return sum(1 for r in self.records if r.handler == 0)


def _records_from(data: bytes, offset: int) -> int:
    """How many consecutive shape-valid records start at ``offset``."""
    count, pos = 0, offset
    while pos + RECORD.size <= len(data):
        cid, handler, flag, _checker = RECORD.unpack_from(data, pos)
        if not (ID_MIN <= cid <= ID_MAX):
            break
        if not (HANDLER_MIN <= handler < HANDLER_MAX):
            break
        if flag not in (0, 1):
            break
        count += 1
        pos += RECORD.size
    return count


def find_table(data: bytes) -> CommandTable:
    """Return the longest shape-valid record run in ``data``.

    Raises ``ValueError`` when no run is long enough to be a command table, so a caller
    never silently gets a bogus table for an image that does not follow this layout.
    """
    best_offset, best_count = 0, 0
    # The table is a record array, but its file offset is aligned to the record size only
    # when the enclosing section happens to be; observed offsets (0xfb13c8, 0xfd628c,
    # 0x1043414) are 4-byte aligned, not 16, so every 4-byte offset must be considered.
    for offset in range(0, len(data) - RECORD.size * MIN_RECORDS, 4):
        count = _records_from(data, offset)
        if count > best_count:
            best_offset, best_count = offset, count
    if best_count < MIN_RECORDS:
        raise ValueError(
            f"no command table found: longest shape-valid run was {best_count} records, "
            f"minimum is {MIN_RECORDS}"
        )
    records = tuple(
        Command(*RECORD.unpack_from(data, best_offset + i * RECORD.size))
        for i in range(best_count)
    )
    return CommandTable(best_offset, records)


def read_table(path: Path) -> CommandTable:
    return find_table(Path(path).read_bytes())


def is_avcam(path: Path) -> bool:
    """Cheap identity check: the ORIL container puts its magic at byte 4."""
    try:
        head = Path(path).read_bytes()[:8]
    except OSError:
        return False
    return head[4:8] == b"ORIL"


if __name__ == "__main__":
    import argparse
    import hashlib

    parser = argparse.ArgumentParser(description="decode the av-cam.bin command table")
    parser.add_argument("image", type=Path, help="an unpacked av-cam.bin")
    parser.add_argument("--json", action="store_true", help="emit ids as JSON")
    args = parser.parse_args()

    data = args.image.read_bytes()
    table = find_table(data)
    print(f"# {args.image.name} sha256={hashlib.sha256(data).hexdigest()}")
    print(f"offset={table.offset:#x} records={len(table)} "
          f"unique={len(set(table.ids))} zero_handlers={table.zero_handlers}")
    if args.json:
        import json
        print(json.dumps(list(table.ids)))
    else:
        for cmd in table.records:
            print(f"  {cmd.command_id:#06x} handler={cmd.handler:#010x} "
                  f"flag={cmd.flag} checker={cmd.checker:#010x}")
