#!/usr/bin/env python3
"""Enumerate the camera's IPC call sites and the queue id each one passes.

The application layer talks over OSAL messages, and a queue id is what links a producer to a
consumer. This module produces the table: every call to ``osal_snd_msg``, ``osal_rcv_msg_tmo`` or
an ``ioctl``, the function it happens in, and the constant argument when there is one.

The discipline that matters: **an argument is only reported when it is actually a constant.**
``constant_arguments`` walks back from the call site looking for an immediate written into the
register. A register copied from another register, loaded from memory or computed has no static
value, and guessing one would put a wrong queue id in the table — worse than an empty cell,
because an empty cell is visibly unknown.

Offline only.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

# Sibling tools are imported as modules, so the directory must be importable even when this file
# is run with ``-I`` (which drops the script directory from sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parent))

#: The imports whose call sites are worth tabulating.
_IPC_CALLEES = ("osal_snd_msg", "osal_rcv_msg_tmo", "osal_snd_sync_msg", "ioctl")


def _capstone():
    import capstone

    return capstone.Cs(capstone.CS_ARCH_ARM,
                       capstone.CS_MODE_THUMB | capstone.CS_MODE_LITTLE_ENDIAN)


def constant_arguments(data: bytes, base: int, site: int, register: int,
                       window: int = 0x40) -> int | None:
    """The immediate last written to ``register`` before ``site``, or ``None``.

    Returns ``None`` when the register is copied from another register or loaded from memory:
    the value is not statically knowable and reporting a number would be an invention.
    """
    start = max(base, site - window)
    md = _capstone()
    region = data[start - base:site - base]
    if not region:
        return None
    seen: int | None = None
    for ins in md.disasm(region, start):
        op = ins.op_str
        if ins.mnemonic.startswith("mov"):
            # movs r0,#0x2a / mov.w r0,#0x2a / movw r0,#0xe002
            head, _, tail = op.partition(",")
            if head.strip() != f"r{register}":
                continue
            tail = tail.strip()
            if tail.startswith("#"):
                try:
                    seen = int(tail[1:], 0)
                except ValueError:
                    seen = None
            else:
                seen = None          # copied from a register or memory: unknown
            continue
        if ins.mnemonic in ("add", "adds", "addw") and "pc" in op:
            head, _, tail = op.partition(",")
            if head.strip() == f"r{register}":
                seen = None          # a PC-relative address, not a queue id
            continue
        if ins.mnemonic.startswith("ldr"):
            head, _, _ = op.partition(",")
            if head.strip() == f"r{register}":
                seen = None          # loaded from memory: unknown
    return seen


def _literal_loads(data: bytes, base: int) -> dict[int, tuple[int, int]]:
    """``address -> (register, immediate)`` for Thumb PC-relative loads.

    Used because the compiler materialises a queue id either with ``movw``/``movt`` or by loading
    a literal from the pool, and both forms are common in this code.
    """
    out: dict[int, tuple[int, int]] = {}
    for pos in range(0, len(data) - 4, 2):
        first = int.from_bytes(data[pos:pos + 2], "little")
        if (first >> 11) == 0b01001:          # 16-bit ldr rX,[pc,#imm8]
            register = (first >> 8) & 0x7
            immediate = (first & 0xFF) * 4
            out[base + pos] = (register, immediate)
            continue
        second = int.from_bytes(data[pos + 2:pos + 4], "little")
        if (first & 0xFF7F) == 0xF85F:        # 32-bit ldr.w rX,[pc,#imm12]
            register = (second >> 12) & 0xF
            immediate = second & 0xFFF
            out[base + pos] = (register, immediate)
    return out


def ipc_edges(path: Path) -> list[dict[str, Any]]:
    """One entry per IPC call site found in ``path``.

    Each entry: ``{"caller", "callee", "site", "queue_or_cmd"}``. ``caller`` is the enclosing
    function's name when the symbol table answers, else ``sub_XXXXXXXX``.
    """
    from callgraph import _plt_symbol_names, build_callgraph, direct_calls

    graph = build_callgraph(Path(path))
    names_by_address = graph["nodes"]
    plt_names = _plt_symbol_names(Path(path))

    data = Path(path).read_bytes()
    try:
        import io

        from elftools.elf.elffile import ELFFile

        with open(path, "rb") as handle:
            elf = ELFFile(handle)
            section = None
            for candidate in elf.iter_sections():
                if candidate["sh_type"] != "SHT_PROGBITS":
                    continue
                if not candidate["sh_flags"] & 0x4:
                    continue
                if section is None or candidate["sh_size"] > section["sh_size"]:
                    section = candidate
            code = section.data()
            code_base = section["sh_addr"]
    except Exception as exc:
        raise ValueError(f"{path}: cannot read executable sections ({exc})") from exc

    # Map an instruction address to the symbol that contains it, so a call site names its
    # enclosing function rather than a bare address.
    spans = sorted((addr, name) for addr, name in names_by_address.items())

    def enclosing(address: int) -> str:
        found = f"sub_{address:08X}"
        for start, name in spans:
            if start > address:
                break
            found = name
        return found

    edges: list[dict[str, Any]] = []
    for caller, callee in direct_calls(code, code_base):
        resolved = plt_names.get(callee) or names_by_address.get(callee) or ""
        if resolved not in _IPC_CALLEES:
            continue
        # The first argument of an OSAL send is the queue id in r0; for ioctl the command sits
        # in r1 after the file descriptor.
        register = 1 if resolved == "ioctl" else 0
        # Only an immediate counts. The earlier literal-pool fallback read the *instruction*
        # bytes instead of the pool and so invented numbers (0x4604490f for a value actually
        # loaded from memory). A value that is not an immediate stays None, which the TSV shows
        # as an empty field.
        value = constant_arguments(code, code_base, caller, register)
        edges.append({
            "caller": enclosing(caller),
            "callee": resolved,
            "site": caller,
            "queue_or_cmd": value,
        })
    return edges


def edges_to_tsv(edges: list[dict[str, Any]]) -> str:
    """The table, with an unknown id written as an empty field rather than a zero."""
    lines = ["caller\tcallee\tsite\tqueue_or_cmd"]
    for edge in edges:
        value = edge["queue_or_cmd"]
        rendered = "" if value is None else f"0x{value:x}"
        lines.append(f"{edge['caller']}\t{edge['callee']}\t0x{edge['site']:x}\t{rendered}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", type=Path)
    parser.add_argument("--tsv", action="store_true", help="write the table instead of a summary")
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args(argv)

    edges = ipc_edges(args.image)
    if args.tsv:
        sys.stdout.write(edges_to_tsv(edges))
        return 0
    with_constant = sum(1 for e in edges if e["queue_or_cmd"] is not None)
    print(f"edges: {len(edges)}  with a constant id: {with_constant}  "
          f"unknown: {len(edges) - with_constant}", file=sys.stderr)
    for edge in edges[: args.limit]:
        value = "-" if edge["queue_or_cmd"] is None else f"0x{edge['queue_or_cmd']:x}"
        print(f"0x{edge['site']:x} {edge['caller']} -> {edge['callee']} {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
