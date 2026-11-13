#!/usr/bin/env python3
"""Take the firmware payload out of an official Sony updater executable.

Two container shapes occur in the published A6xxx/A7/ZV/RX updaters:

* **UFU** — magic ``89 55 46 55 0d 0a 1a 0a`` followed by repeated
  ``<u32 big-endian length> <4-byte tag> <payload>`` records (``DATV``, ``PROV``, ``UDID``,
  ``FDAT``, ``SDAT``), terminated by ``DEND``.  The container ends at the end of the
  ``DEND`` payload.  A naive first-``DEND`` byte search truncates *inside* ``FDAT``,
  because that byte sequence can occur in compressed data.
* **PackMan** — a bitwise-NOT of an ``MSCF`` cabinet.  Inverting the bytes from the
  inverted-``MSCF`` offset yields a cabinet whose ``FirmwareData_*.dat`` member is the same
  encrypted ``.dat`` the UFU path produces.

The extracted payload is byte-identical to what the updater itself would hand to the
camera.  Nothing here decrypts, executes or writes to a device, and the source ``.exe`` is
opened read-only.

Usage::

    python3 -I tools/research/sony_updater_payload.py <dir-with-exes> <out-dir>
    python3 -I tools/research/sony_updater_payload.py <one.exe> <out-dir>

Exit code is 0 when every input produced a payload, 2 when any input was rejected.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

UFU_MAGIC = b"\x89UFU\r\n\x1a\n"
INVERTED_MSCF = bytes(b ^ 0xFF for b in b"MSCF")
#: Chunk tags this parser accepts.  An unknown tag inside the container is an error, not a
#: guess: guessing is how a truncated read silently becomes a wrong payload.
KNOWN_TAGS = frozenset(b"DATV PROV UDID FDAT SDAT DEND".split())


def ufu_extent(data: bytes, start: int) -> int:
    """Return the offset one past the container that begins at ``start``."""
    pos = start + len(UFU_MAGIC)
    while pos + 8 <= len(data):
        (size,) = struct.unpack_from(">I", data, pos)
        tag = data[pos + 4:pos + 8]
        if tag not in KNOWN_TAGS:
            raise ValueError(f"unknown chunk tag {tag!r} at {pos:#x}")
        if tag == b"DEND":
            end = pos + 8 + size
            if end > len(data):
                raise ValueError(f"DEND at {pos:#x} runs past end of file")
            return end
        pos += 8 + size
        if pos > len(data):
            break
    raise ValueError("container did not terminate with DEND")


def packman_extent(data: bytes, start: int) -> bytes:
    """Invert from the inverted-MSCF offset and return exactly ``cbCabinet`` bytes."""
    raw = bytes(b ^ 0xFF for b in data[start:])
    if raw[:4] != b"MSCF":
        raise ValueError("inverted header is not MSCF")
    (cb_cabinet,) = struct.unpack_from("<I", raw, 8)
    if not 36 <= cb_cabinet <= len(raw):
        raise ValueError(f"implausible cabinet size {cb_cabinet}")
    return raw[:cb_cabinet]


def extract(exe: Path, outdir: Path) -> tuple[Path, str]:
    data = exe.read_bytes()
    offset = data.find(UFU_MAGIC)
    if offset >= 0:
        end = ufu_extent(data, offset)
        outdir.mkdir(parents=True, exist_ok=True)
        dst = outdir / (exe.stem + ".ufu")
        dst.write_bytes(data[offset:end])
        return dst, f"UFU    {offset:#x}..{end:#x}"
    offset = data.find(INVERTED_MSCF)
    if offset >= 0:
        raw = packman_extent(data, offset)
        outdir.mkdir(parents=True, exist_ok=True)
        dst = outdir / (exe.stem + ".cab")
        dst.write_bytes(raw)
        return dst, f"CAB    {offset:#x} (bitwise-NOT of MSCF)"
    raise ValueError("neither a UFU container nor an inverted PackMan cabinet")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="an updater .exe or a directory of them")
    parser.add_argument("outdir", type=Path, help="where to write the payloads")
    args = parser.parse_args(argv)

    if args.source.is_dir():
        inputs = sorted(args.source.glob("*.exe"))
        if not inputs:
            print(f"no .exe files under {args.source}", file=sys.stderr)
            return 2
    else:
        inputs = [args.source]

    failed = 0
    for exe in inputs:
        try:
            dst, how = extract(exe, args.outdir)
        except ValueError as exc:
            print(f"REJECT {exe.name}: {exc}", file=sys.stderr)
            failed += 1
            continue
        print(f"{exe.name:30s} {how:34s} -> {dst.name} ({dst.stat().st_size:,} B)")
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
