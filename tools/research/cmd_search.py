#!/usr/bin/env python3
"""Search for a struct-field access two independent ways, and compare.

A single linear disassembly sweep is how a wrong absence claim gets published: the sweep walks
the image two bytes at a time and desynchronises the moment it crosses data or a misaligned
literal pool, after which every following instruction is decoded from the wrong offset and the
site is invisible. It looks like "there are no readers" when it means "my reader stopped
looking".

The second method does not decode at all. A 32-bit Thumb load/store carries its 12-bit immediate
in the *second* halfword, so the immediate can be matched by masking that halfword — a test that
cannot desynchronise, because it is a byte comparison. 16-bit forms cannot reach an offset this
far into a struct (their immediate is scaled, maximum 124 bytes), so ignoring them loses nothing
here and the function says so.

Neither method is correct alone. ``corroborate`` runs both and reports whether they agree,
naming any site only one of them found.

Offline only.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_IMM16_MASK = 0xFFF


def _capstone():
    import capstone

    return capstone.Cs(capstone.CS_ARCH_ARM,
                       capstone.CS_MODE_THUMB | capstone.CS_MODE_LITTLE_ENDIAN)


def scan_encoding(data: bytes, field: int) -> list[int]:
    """Offsets where a 32-bit Thumb load/store names ``field`` in its immediate.

    Matches the encoding, not the decode, so a preceding stray byte cannot hide a site.
    """
    hits: list[int] = []
    for pos in range(0, len(data) - 3):
        second = int.from_bytes(data[pos + 2:pos + 4], "little")
        if (second & _IMM16_MASK) != field:   # parentheses matter: != binds tighter
            continue
        hits.append(pos)
    return hits


def scan_linear(data: bytes, base: int, mnemonic_prefix: tuple[str, ...],
                field: int) -> list[tuple[int, str, str]]:
    """``(address, mnemonic, operands)`` for matching accesses found by a linear sweep.

    This is the weaker method, kept because it names the instruction. Its weakness is bigger than
    desynchronisation: given a whole firmware blob, ``disasm`` stops at the first byte it cannot
    decode and does not resume, so on a real image it can stop after a few dozen instructions out
    of sixteen megabytes and report nothing. The coverage is returned by ``sweep_coverage`` so a
    caller cannot mistake that silence for an absence.
    """
    md = _capstone()
    hits: list[tuple[int, str, str]] = []
    for ins in md.disasm(data, base):
        if not ins.mnemonic.startswith(mnemonic_prefix):
            continue
        if f"#0x{field:x}]" not in ins.op_str and f"#{field}]" not in ins.op_str:
            continue
        hits.append((ins.address, ins.mnemonic, ins.op_str))
    return hits


def sweep_coverage(data: bytes, base: int) -> dict[str, object]:
    """How much of ``data`` the linear sweep actually reached.

    A linear sweep of a firmware image is not coverage of the image: it stops at the first
    undecodable byte. This reports the stop so an "absent" answer can be judged against what was
    really examined.
    """
    md = _capstone()
    count = 0
    last = base
    for ins in md.disasm(data, base):
        count += 1
        last = ins.address + ins.size
    reached = max(0, last - base)
    return {
        "instructions": count,
        "bytes_reached": reached,
        "bytes_total": len(data),
        "fraction": reached / len(data) if data else 0.0,
    }


def corroborate(data: bytes, base: int, field: int,
                mnemonic_prefix: tuple[str, ...] = ("ldr", "str")) -> dict[str, object]:
    """Compare the two methods and say whether the absence of a site may be stated.

    ``agrees`` is ``False`` when the encoding scan found a site the linear sweep did not, which
    is exactly the case that would have published a wrong "no readers" claim.
    """
    encoding_offsets = scan_encoding(data, field)
    encoding_addresses = {base + offset for offset in encoding_offsets}
    linear_addresses = {address for address, _, _ in
                        scan_linear(data, base, mnemonic_prefix, field)}
    encoding_only = sorted(encoding_addresses - linear_addresses)
    linear_only = sorted(linear_addresses - encoding_addresses)
    coverage = sweep_coverage(data, base)
    # Agreement means the two methods found the same sites *and* the linear sweep actually
    # covered enough of the image for its silence to mean anything. A sweep that stopped after
    # 33 instructions agrees with nothing.
    agrees = (not encoding_only and not linear_only
              and coverage["instructions"] > 0
              and (coverage["fraction"] >= 0.5 or len(encoding_addresses) == 0))
    return {
        "encoding_hits": len(encoding_addresses),
        "linear_hits": len(linear_addresses),
        "agrees": agrees,
        "encoding_only": encoding_only,
        "linear_only": linear_only,
        "linear_coverage": coverage,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--base", type=lambda v: int(v, 0), required=True,
                        help="runtime virtual address of the image start")
    parser.add_argument("--field", type=lambda v: int(v, 0), required=True)
    parser.add_argument("--mnemonics", default="ldr,str")
    parser.add_argument("--expect", default=None,
                        help="fail unless the summary equals this, e.g. "
                             "'agrees=True encoding=85 linear=85'")
    args = parser.parse_args(argv)

    data = args.image.read_bytes()
    result = corroborate(data, args.base, args.field, tuple(args.mnemonics.split(",")))
    coverage = result["linear_coverage"]
    summary = (f"agrees={result['agrees']} encoding={result['encoding_hits']} "
               f"linear={result['linear_hits']} "
               f"coverage={coverage['fraction']:.3f}")
    print(summary)
    for address in result["encoding_only"]:
        print(f"  encoding-only site: 0x{address:x}")
    for address in result["linear_only"]:
        print(f"  linear-only site:   0x{address:x}")
    if args.expect is not None and summary != args.expect:
        print(f"expected {args.expect!r}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
