#!/usr/bin/env python3
"""Follow a settings-cache field written by one ``av-cam.bin`` handler, and count its readers.

The ``av-cam`` layer is a settings store: a command handler receives a message, stores one
value into a global settings cache, and the store is what remains in the packaged image.  The
question this tool answers is whether anything in that image ever reads the value back.

It is deliberately mechanical, and it validates itself against a known-good reference before
its answer is trusted:

* the store is ``str{b,h}.w rT,[rB,#imm12]``; ``imm12`` is the field offset;
* ``rB`` is resolved through the PIC idiom ``ldr rD,[pc,#k]`` ; ``add rD,pc``, giving
  ``literal + address_of_add + 4`` where the address is the runtime address (ORIL base);
* every load/store in the image whose base register was materialised to that same absolute
  value and whose ``imm12`` equals the field offset is counted, and the walk stops where the
  base register is overwritten;
* access width must agree: ``strb.w`` at ``+0x540`` and ``str.w`` at ``+0x540`` touch
  different bytes of that word and are not the same field.

A negative (zero readers) result is a statement about the packaged image, never about a live
camera's application layer.

Usage::

    python3 -I tools/research/av_eyeaf_field.py <av-cam.bin> --command 0x413b
    python3 -I tools/research/av_eyeaf_field.py <av-cam.bin> --command 0x413b \
        --expect '0x6442ab54:0x5d0:1:0'
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs

ORIL_BASE = 0x635C6000
#: How far past a base-register materialisation the walk may run before giving up.  Access
#: blocks are short; a longer window only risks counting a reused register.
MAX_WINDOW = 0x400

_md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
_md.skipdata = True

_WIDTH = {"str.w": 4, "ldr.w": 4, "strb.w": 1, "ldrb.w": 1, "strh.w": 2, "ldrh.w": 2}

#: ``add rD, pc`` with rD in 0..15, as the 16-bit Thumb encoding allows r0..r7 only.
_ADDPC = {0x4478 + (d & 7) + ((d & 8) << 4) for d in range(16)}


def materialisations(data: bytes) -> dict[int, tuple[int, int]]:
    """file offset -> (register, absolute base value) for the ``ldr rD,[pc,#k]; add rD,pc`` idiom."""
    found: dict[int, tuple[int, int]] = {}
    for pos in range(0, len(data) - 4, 2):
        first = data[pos] | (data[pos + 1] << 8)
        if (first & 0xF800) != 0x4800:
            continue
        reg = (first >> 8) & 7
        literal = ((pos + 4) & ~3) + (first & 0xFF) * 4
        if literal + 4 > len(data):
            continue
        value = int.from_bytes(data[literal:literal + 4], "little")
        for step in (2, 4):
            if pos + step + 2 > len(data):
                continue
            here = data[pos + step] | (data[pos + step + 1] << 8)
            if here in _ADDPC and ((here - 0x4478) & 7) == reg:
                absolute = (value + ORIL_BASE + pos + step + 4) & 0xFFFFFFFF
                found.setdefault(pos, (reg, absolute))
                break
    return found


def _overwrites(ins, reg: int) -> bool:
    """True when the instruction ends the base register's life.

    The PC-relative load and the following ``add rD, pc`` *establish* the base, so they never
    kill it; everything that writes the register does.
    """
    dest = ins.op_str.split(",")[0].strip()
    if dest != f"r{reg}":
        if ins.mnemonic.startswith(("pop", "ldm")) and f"r{reg}" in ins.op_str:
            return True
        return False
    if ins.mnemonic.startswith("ldr") and "[pc," in ins.op_str:
        return False
    if ins.mnemonic in ("add", "adds") and "pc" in ins.op_str:
        return False
    return ins.mnemonic.startswith((
        "ldr", "mov", "movs", "movw", "movt", "add", "adds", "sub", "subs", "adr",
        "orr", "eor", "and", "lsl", "lsr", "asr", "bic", "mvn"))


def handler_store(data: bytes, handler_va: int):
    """(field offset, base register, store address, width) of the handler's first immediate store."""
    start = (handler_va & ~1) - ORIL_BASE
    if not 0 <= start < len(data):
        raise ValueError(f"handler {handler_va:#x} is outside the image")
    for ins in _md.disasm(data[start:start + 0x80], handler_va & ~1):
        if not ins.mnemonic.startswith("str"):
            continue
        if "[r" not in ins.op_str or ", #0x" not in ins.op_str:
            continue
        memory = ins.op_str[ins.op_str.index("["):]
        base_reg = int(memory[memory.index("r") + 1:].split(",")[0].split("]")[0], 10)
        field = int(memory.split("#")[1].split("]")[0], 16)
        return field, base_reg, ins.address, _WIDTH.get(ins.mnemonic, 4)
    raise ValueError(f"no immediate store in the first 0x80 bytes of handler {handler_va:#x}")


def count_accesses(data: bytes, reg: int, base: int, field: int, width: int) -> tuple[int, int]:
    """(writes, reads) of ``[reg, #field]`` while ``reg`` still holds ``base``."""
    writes = reads = 0
    for pos, (found_reg, value) in materialisations(data).items():
        if found_reg != reg or value != base:
            continue
        for ins in _md.disasm(data[pos:pos + MAX_WINDOW], ORIL_BASE + pos):
            if _overwrites(ins, reg):
                break
            if f"[r{reg}," not in ins.op_str or ", #0x" not in ins.op_str:
                continue
            try:
                offset = int(ins.op_str.split("#")[1].split("]")[0], 16)
            except (IndexError, ValueError):
                continue
            if offset != field or _WIDTH.get(ins.mnemonic) != width:
                continue
            if ins.mnemonic.startswith("str"):
                writes += 1
            else:
                reads += 1
    return writes, reads


def analyse(image: Path, command_id: int) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from av_command_table import find_table

    data = Path(image).read_bytes()
    table = find_table(data)
    record = table.get(command_id)
    if record is None:
        return {"image": str(image), "sha256": hashlib.sha256(data).hexdigest(),
                "command": command_id, "present": False}
    field, reg, at, width = handler_store(data, record.handler)
    before = [(pos, value) for pos, (r, value) in materialisations(data).items()
              if r == reg and pos < at - ORIL_BASE]
    if not before:
        raise ValueError(f"handler {record.handler:#x}: base register r{reg} never materialised")
    base = max(before)[1]
    writes, reads = count_accesses(data, reg, base, field, width)
    return {
        "image": str(image),
        "sha256": hashlib.sha256(data).hexdigest(),
        "command": command_id,
        "present": True,
        "handler": record.handler,
        "field": field,
        "cache": base,
        "width": width,
        "writes": writes,
        "reads": reads,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", type=Path, help="an unpacked av-cam.bin")
    parser.add_argument("--command", default="0x413b", help="command id to follow")
    parser.add_argument("--expect", help="cache:field:writes:reads assertion, e.g. 0x6442ab54:0x5d0:1:0")
    args = parser.parse_args(argv)

    result = analyse(args.image, int(args.command, 0))
    if not result["present"]:
        print(f"command {int(args.command, 0):#06x} is not in this table")
        return 0
    print(f"command {result['command']:#06x} handler {result['handler']:#010x} "
          f"field +{result['field']:#x} ({result['width']} byte) "
          f"cache {result['cache']:#010x} writes {result['writes']} reads {result['reads']}")
    if args.expect:
        want_cache, want_field, want_w, want_r = args.expect.split(":")
        ok = (result["cache"] == int(want_cache, 0)
              and result["field"] == int(want_field, 0)
              and result["writes"] == int(want_w)
              and result["reads"] == int(want_r))
        print("expectation satisfied" if ok else "EXPECTATION VIOLATED")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
