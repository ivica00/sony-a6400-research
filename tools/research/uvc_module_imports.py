#!/usr/bin/env python3
"""Classify one kernel module's undefined symbols against a body's kernel symbol table.

A module in a Sony firmware package imports from three places: the kernel, other modules of
the same package, and nothing else.  This tool separates the first from the rest and, with
``--package-dir``, names which sibling module exports each import — so "unresolved by the
kernel" is never reported as "unsatisfiable".

Usage::

    python3 -I tools/research/uvc_module_imports.py <module.ko> \
        --kernel-symbols <body-symbols.json> [--package-root <dir> ...]

``--kernel-symbols`` takes the JSON written by ``decode_kernel_kallsyms.py`` (a ``symbols``
list of ``{name, address}``); the file's own name is irrelevant.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

from elftools.elf.elffile import ELFFile


def undefined_symbols(path: Path) -> list[str]:
    """Undefined, named, non-compiler-generated symbols of an ELF object."""
    with open(path, "rb") as handle:
        elf = ELFFile(handle)
        table = elf.get_section_by_name(".symtab") or elf.get_section_by_name(".dynsym")
        if table is None:
            raise ValueError(f"{path.name}: no symbol table")
        return sorted({
            sym.name for sym in table.iter_symbols()
            if sym["st_shndx"] == "SHN_UNDEF" and sym.name and not sym.name.startswith("$")
        })


def defined_symbols(path: Path) -> set[str]:
    """Symbols an ELF object defines (exports) itself."""
    with open(path, "rb") as handle:
        elf = ELFFile(handle)
        out: set[str] = set()
        for name in (".symtab", ".dynsym"):
            table = elf.get_section_by_name(name)
            if table is None:
                continue
            for sym in table.iter_symbols():
                if sym["st_shndx"] != "SHN_UNDEF" and sym.name:
                    out.add(sym.name)
        return out


def kernel_symbol_names(path: Path) -> set[str]:
    data = json.loads(Path(path).read_text())
    table = data.get("symbols") or []
    return {entry["name"] for entry in table}


def _sibling_files(roots: list[Path]) -> list[Path]:
    """Every .ko under the given roots (a root may be a directory anywhere in the image)."""
    found: list[Path] = []
    for root in roots:
        if root.is_file():
            found.append(root)
        elif root.is_dir():
            found.extend(sorted(root.rglob("*.ko")))
    return found


def classify(module: Path, kernel: set[str], package_roots: list[Path]) -> dict:
    imports = undefined_symbols(module)
    in_kernel = [s for s in imports if s in kernel]
    not_in_kernel = [s for s in imports if s not in kernel]
    siblings: dict[str, set[str]] = {}
    for other in _sibling_files(package_roots):
        if other.resolve() == module.resolve():
            continue
        try:
            overlap = defined_symbols(other) & set(not_in_kernel)
        except Exception:  # noqa: BLE001 - a non-ELF file under kmod/ is not an error here
            continue
        if overlap:
            # two images of the body can each carry the same module; name the first only
            label = other.name if other.name not in siblings else str(other.parent.name) + "/" + other.name
            siblings[label] = overlap
    provided = {s: sorted(name for name, syms in siblings.items() if s in syms) for s in not_in_kernel}
    return {
        "module": module.name,
        "imports": len(imports),
        "in_kernel": len(in_kernel),
        "not_in_kernel": not_in_kernel,
        "provided_by": provided,
        "unexplained": sorted(s for s, p in provided.items() if not p),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("module", type=Path, help="the .ko to inspect")
    parser.add_argument("--kernel-symbols", type=Path, required=True,
                        help="JSON written by decode_kernel_kallsyms.py")
    parser.add_argument("--package-root", type=Path, nargs="*", default=[],
                        help="one or more directories to search for sibling modules, so a "
                             "missing import can be attributed to who exports it")
    args = parser.parse_args(argv)

    result = classify(args.module, kernel_symbol_names(args.kernel_symbols), args.package_root)
    print(f"{result['module']}: {result['imports']} imports, "
          f"{result['in_kernel']} satisfied by the kernel, "
          f"{len(result['not_in_kernel'])} not kernel symbols")
    for name in result["not_in_kernel"]:
        who = result["provided_by"][name]
        origin = ", ".join(who) if who else "not exported by any sibling module searched"
        print(f"  {name:30s} {origin}")
    if result["unexplained"]:
        print(f"\n{len(result['unexplained'])} import(s) are satisfied by neither the kernel nor a "
              f"sibling module in the given package dir; that is recorded, not explained.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
