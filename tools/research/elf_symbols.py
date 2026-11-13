#!/usr/bin/env python3
"""Read an ELF's symbol tables into a name-to-address map, without disassembling.

The camera's libraries ship unstripped: ``libObj.so`` alone exports 3,297 code symbols with
their C++ mangled names intact. That makes a whole library legible before a single instruction
is decoded, which is why this is the first tool the platform work needs.

Reads both tables on purpose. ``.dynsym`` holds what the loader resolves and is always present;
``.symtab`` holds the local symbols too and is present because Sony did not strip. A symbol
appearing in both is kept once, and the record says which table it came from so a later reader
can tell an exported entry point from an internal helper.

Offline only: no camera, no firmware execution.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NamedTuple

_ELF_MAGIC = b"\x7fELF"

#: pyelftools reports ``st_info`` as its symbolic names ("STT_FUNC", "STB_LOCAL"), not numbers.
_CODE_TYPES = ("STT_FUNC",)
_BIND_LOCAL = ("STB_LOCAL",)


class Symbol(NamedTuple):
    """One entry from a symbol table."""

    name: str
    address: int
    size: int
    type: str
    source: str


def _letter(bind, stype) -> str:
    """readelf's letter for a symbol, limited to the distinction this project uses.

    Accepts pyelftools' symbolic names and plain integers alike, so a caller that builds a
    Symbol by hand (as the tests do) is not held to the library's representation.
    """
    is_code = stype in _CODE_TYPES or stype == 2
    is_local = bind in _BIND_LOCAL or bind == 0
    if is_code:
        return "t" if is_local else "T"
    if stype in (0, "STT_NOTYPE"):
        return "U" if is_local else "?"
    if stype in (1, "STT_OBJECT"):
        return "D"
    return "?"


def read_symbols(path: Path) -> list[Symbol]:
    """Every named symbol in ``path``'s static and dynamic tables, sorted by address.

    Raises ``ValueError`` when the file is not a readable ELF: a caller that asked for symbols
    must not silently receive an empty list, because an empty map reads as "stripped or absent"
    and would make a downstream absence claim wrong.
    """
    path = Path(path)
    try:
        head = path.read_bytes()[:4]
    except OSError as exc:
        raise ValueError(f"{path}: cannot read ({exc})") from exc
    if head != _ELF_MAGIC:
        raise ValueError(f"{path}: not an ELF file")

    try:
        from elftools.elf.elffile import ELFFile
    except ImportError as exc:  # pragma: no cover - pinned in requirements.txt
        raise ValueError("pyelftools is required to read symbol tables") from exc

    found: dict[tuple[str, int], Symbol] = {}
    try:
        with open(path, "rb") as handle:
            elf = ELFFile(handle)
            for section_name, source in ((".dynsym", "dynsym"), (".symtab", "symtab")):
                table = elf.get_section_by_name(section_name)
                if table is None:
                    continue
                for sym in table.iter_symbols():
                    name = sym.name
                    if not name:
                        continue
                    info = sym["st_info"]
                    address = sym["st_value"]
                    candidate = Symbol(
                        name=name,
                        address=address,
                        size=sym["st_size"],
                        type=_letter(info["bind"], info["type"]),
                        source=source,
                    )
                    key = (name, address)
                    # Prefer the dynamic table when a name appears in both: that is the entry
                    # another module can actually resolve.
                    existing = found.get(key)
                    if existing is None or (existing.source == "symtab" and source == "dynsym"):
                        found[key] = candidate
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"{path}: not a readable ELF ({exc})") from exc

    return sorted(found.values(), key=lambda s: (s.address, s.name))


def functions(symbols: list[Symbol]) -> list[Symbol]:
    """Only the code symbols (``T`` and ``t``)."""
    return [s for s in symbols if s.type in ("T", "t")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", type=Path, help="ELF file to read")
    parser.add_argument("--functions", action="store_true", help="code symbols only")
    parser.add_argument("--names", action="store_true", help="print names without addresses")
    args = parser.parse_args(argv)

    symbols = read_symbols(args.image)
    if args.functions:
        symbols = functions(symbols)
    for sym in symbols:
        if args.names:
            print(sym.name)
        else:
            print(f"0x{sym.address:08x} {sym.size:6d} {sym.type} {sym.source:6s} {sym.name}")
    print(f"-- {len(symbols)} symbols from {args.image}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
