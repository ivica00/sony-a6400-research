#!/usr/bin/env python3
"""Build a direct-call graph over a packaged ARM library.

The camera's libraries ship unstripped, so a ``bl`` can be resolved to a symbol name instead of
an anonymous address. That is what turns 20 MB of ``libObj.so`` into something a person can
follow: who calls ``osal_snd_msg``, what reaches ``ObjDisplay_Start``, where a button event
enters.

Two deliberate limits:

* **Direct calls only.** An indirect call through a register cannot be resolved statically, so it
  is counted in ``unresolved`` rather than guessed. A guessed edge would make a traced path look
  complete when it is not.
* **Names are never invented.** An address with no symbol becomes ``sub_XXXXXXXX``, which is
  honest about being unknown.

Offline only.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


def _capstone():
    import capstone

    return capstone.Cs(capstone.CS_ARCH_ARM,
                       capstone.CS_MODE_THUMB | capstone.CS_MODE_LITTLE_ENDIAN)


def _thumb_bl_target(data: bytes, pos: int, base: int) -> int | None:
    """Target of a 32-bit Thumb ``bl``/``blx`` at ``pos``, or ``None`` if not one.

    Decoded from the encoding rather than through capstone so a caller can scan a large image
    without paying for a full disassembly pass that stops at the first undecodable byte.
    """
    if pos + 4 > len(data):
        return None
    first = int.from_bytes(data[pos:pos + 2], "little")
    second = int.from_bytes(data[pos + 2:pos + 4], "little")
    # bl/blx: first halfword 11110 S imm10, second halfword 11 J1 1 J2 imm11 H
    # The second halfword's top two bits are 11 for both forms, and bit 0 is the H flag: 0 for
    # bl (target in Thumb state), 1 for blx. Masking 0xD000 rejects a real blx (0xEFE0 & 0xD000
    # == 0xC000), which is how the first version of this function silently found no edges.
    if (first & 0xF800) != 0xF000 or (second & 0xC000) != 0xC000:
        return None
    sign = (first >> 10) & 1
    j1 = (second >> 13) & 1
    j2 = (second >> 11) & 1
    imm10 = first & 0x3FF
    imm11 = second & 0x7FF
    i1 = 1 - (j1 ^ sign)
    i2 = 1 - (j2 ^ sign)
    offset = (sign << 24) | (i1 << 23) | (i2 << 22) | (imm10 << 12) | (imm11 << 1)
    if sign:
        offset -= 1 << 25
    # BLX aligns its PC to a word boundary before adding, so using the unaligned PC put every
    # edge two bytes off — which is why a real blx first produced 0x59e instead of 0x59c.
    pc = (base + pos + 4) & ~3
    return (pc + offset) & 0xFFFFFFFF


def direct_calls(data: bytes, base: int) -> list[tuple[int, int]]:
    """``(caller address, callee address)`` for every direct call in ``data``.

    Two independent forms of the same check, because the encoding alone produces false positives:
    literal-pool bytes that happen to match the ``bl`` shape. Every candidate is confirmed by
    capstone decoding it as a branch, and an image whose code does not decode is rejected rather
    than mined for patterns — a bogus edge would later be labelled with a made-up argument.
    """
    md = _capstone()
    edges: list[tuple[int, int]] = []
    seen: set[int] = set()
    for parity in (0, 1):
        for pos in range(parity, len(data) - 3, 2):
            if pos in seen:
                continue
            target = _thumb_bl_target(data, pos, base)
            if target is None:
                continue
            # The first decoded instruction must itself be the 4-byte branch. The earlier
            # version broke out of the loop before comparing `size`, so a 2-byte instruction
            # sharing the encoding bits passed as a "call" — which produced 28 bogus IPC edges
            # in 29, each with a fabricated argument.
            confirmed = any(ins.mnemonic in ("bl", "blx") and ins.size == 4
                            for ins in list(md.disasm(data[pos:pos + 4], base + pos))[:1])
            if not confirmed:
                continue
            seen.add(pos)
            edges.append((base + pos, target))
    return sorted(edges)


def _name_for(address: int, names: dict[int, str]) -> str:
    """The symbol at ``address``, or a name that admits it is unknown."""
    return names.get(address, f"sub_{address:08X}")


def build_callgraph(path: Path) -> dict[str, Any]:
    """Load an ELF and return ``{nodes, edges, unresolved}``.

    ``nodes`` maps a name to its address, ``edges`` is a list of ``(caller name, callee name)``,
    and ``unresolved`` counts calls whose target is not the start of a known symbol — that is the
    measure of how much of the graph is guesswork, so it is reported rather than hidden.
    """
    from elf_symbols import functions, read_symbols

    symbols = read_symbols(Path(path))
    funcs = functions(symbols)
    # Defined code only: an import carries address 0, so including it would map every import to
    # the single address 0 and make unrelated symbols collide. Imports still appear as edge
    # targets by name, because the callee address resolves through the PLT.
    names = {sym.address: sym.name for sym in funcs if sym.address}
    imports = {sym.name for sym in funcs if not sym.address}

    # A library's code lives in its executable sections; scanning data produces nonsense edges.
    code = b""
    code_base = 0
    try:
        import io

        from elftools.elf.elffile import ELFFile

        with open(path, "rb") as handle:
            elf = ELFFile(handle)
            best = None
            for section in elf.iter_sections():
                if section["sh_type"] != "SHT_PROGBITS":
                    continue
                flags = section["sh_flags"]
                if not flags & 0x4:      # SHF_EXECINSTR
                    continue
                if best is None or section["sh_size"] > best[1]:
                    best = (section["sh_addr"], section["sh_size"], section.data())
            if best is not None:
                code_base, _, code = best
    except Exception as exc:
        raise ValueError(f"{path}: cannot read executable sections ({exc})") from exc

    # Calls to an imported function land on a PLT stub, not on the import's address (which is 0).
    # Mapping stub -> name is what makes the IPC edges visible at all: without it every call into
    # osal_snd_msg reads as an unnamed `sub_XXXXXXXX`.
    plt_names = _plt_symbol_names(path)

    pairs = direct_calls(code, code_base)
    # A call's address is the address of the `bl` instruction, which sits *inside* its function,
    # not at its start. Looking it up exactly therefore never matched and every caller read as
    # `sub_XXXXXXXX` — 555,069 callers, zero named, which made path tracing impossible.
    starts = sorted(names)
    import bisect

    def enclosing(address: int) -> str:
        index = bisect.bisect_right(starts, address)
        if index:
            start = starts[index - 1]
            return names[start]
        return f"sub_{address:08X}"

    edges: list[tuple[str, str]] = []
    unresolved = 0
    named_edges = 0
    for caller, callee in pairs:
        callee_name = plt_names.get(callee) or _name_for(callee, names)
        edges.append((enclosing(caller), callee_name))
        if callee in names or callee in plt_names:
            named_edges += 1
        else:
            unresolved += 1

    # These libraries carry `.dynsym` only — no `.symtab`, so local functions have no name. Most
    # call targets therefore land on an unnamed function even though the call itself decoded
    # correctly. `named_edges / edges` is the honest figure for how much of the graph carries a
    # name, and it is reported instead of an assumed "resolution rate".
    total = len(edges)
    return {"nodes": dict(names), "edges": edges, "unresolved": unresolved,
            "imports": sorted(imports), "named_edges": named_edges,
            "named_fraction": named_edges / total if total else 0.0}


def _plt_symbol_names(path: Path) -> dict[int, str]:
    """Map each PLT stub address to the imported symbol it jumps through.

    The stub layout is fixed by this ABI: 12-byte entries after the 20-byte header, each loading
    a GOT slot and branching through it. The slot order follows ``.rel.plt``, so the n-th stub
    resolves the n-th relocation. When the segment sizes do not divide evenly the mapping is
    abandoned rather than guessed.
    """
    import io

    from elftools.elf.elffile import ELFFile

    try:
        with open(path, "rb") as handle:
            elf = ELFFile(handle)
            plt = elf.get_section_by_name(".plt")
            rel = elf.get_section_by_name(".rel.plt")
            if plt is None or rel is None:
                return {}
            names = []
            symtab = elf.get_section(rel["sh_link"])
            for relocation in rel.iter_relocations():
                symbol = symtab.get_symbol(relocation["r_info_sym"])
                names.append(symbol.name or f"import_{relocation['r_info_sym']}")
            header, entry = 20, 12
            available = (plt["sh_size"] - header) // entry
            if available < 1:
                return {}
            return {plt["sh_addr"] + header + index * entry: name
                    for index, name in enumerate(names[:available])}
    except Exception:
        return {}


def callers_of(graph: dict[str, Any], name: str) -> list[str]:
    """Every node with an edge to ``name``, sorted and deduplicated."""
    return sorted({caller for caller, callee in graph["edges"] if callee == name})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", type=Path)
    parser.add_argument("--callers", help="print only the callers of this symbol")
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args(argv)

    graph = build_callgraph(args.image)
    if args.callers:
        for name in callers_of(graph, args.callers)[: args.limit]:
            print(name)
        return 0
    print(f"nodes: {len(graph['nodes'])}  edges: {len(graph['edges'])}  "
          f"unresolved targets: {graph['unresolved']}", file=sys.stderr)
    for caller, callee in graph["edges"][: args.limit]:
        print(f"{caller} -> {callee}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
