#!/usr/bin/env python3
"""Cross-model report over unpacked BIONZ X (CXD90045) bodies.

Answers, for any set of unpacked bodies, the questions this repository's per-body profile
schema needs — without a camera:

* which kernel build each body runs, and which bodies share one kernel;
* how each body's kernel symbol set differs from a reference body;
* the ``av-cam.bin`` command-table delta against the reference;
* whether a body ships the ZV-E10 UVC module package.

Sharing is decided by an **identical kernel symbol-name set**, never by a file hash: two
bodies whose kernels differ only in embedded version strings still share every address and
every code object.  The report states both the shared-symbol count and how many of those
symbols have equal addresses, so the strong case (one code object) and the weak case (one
symbol set, shifted addresses) can never be confused.

Usage::

    python3 -I tools/research/cross_model_report.py <unpacked-root> [--json out.json]
    python3 -I tools/research/cross_model_report.py <unpacked-root> --reference ILCE-6400

``<unpacked-root>`` is a directory whose immediate children are bodies, each shaped like
``<root>/<body>/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/...``, i.e. the
output of ``fwtool unpack``.  Bodies that lack ``vmlinux.bin`` or ``av-cam.bin`` are listed
as ``incomplete`` and never silently dropped.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from av_command_table import find_table  # noqa: E402

#: Compiler-generated literal names carry no source identity: they are renumbered freely
#: between builds, so including them would hide real set equality behind noise.
_LITERAL_PREFIXES = ("C.", "$", "__func__", "CSWTCH")

DEV_PATH = Path("firmware.tar_unpacked/0700_part_image/dev")


@dataclass
class Body:
    name: str
    kernel: Path | None = None
    avcam: Path | None = None
    libobj: Path | None = None
    kernel_sha256: str | None = None
    build: str | None = None
    builder: str | None = None
    symbols: dict[str, int] = field(default_factory=dict)
    #: Symbol type letter from the decoded kallsyms table ("T"/"t" code, "R"/"r"/"D"/"d" data).
    #: Used to say whether a differing address is code or data instead of guessing.
    types: dict[str, str] = field(default_factory=dict)
    command_ids: tuple[int, ...] = ()
    table_offset: int | None = None
    uvc: dict[str, str | None] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return bool(self.symbols) and bool(self.command_ids)


def _find(roots: list[Path], body: str, name: str) -> Path | None:
    """First match for ``name`` under any root's ``<body>/firmware.tar_unpacked/...``."""
    for root in roots:
        base = root / body / DEV_PATH
        if not base.is_dir():
            continue
        hits = sorted(base.rglob(name))
        if hits:
            return hits[0]
    return None


def _kernel_identity(raw: bytes) -> tuple[str | None, str | None]:
    """(build, builder) out of the Linux banner printed by the image."""
    import re
    match = re.search(
        rb"Linux version \S+ \(([^)]+)\) \(gcc version [^)]*\(([^)]*)\)", raw
    )
    if not match:
        return None, None
    return match.group(2).decode("ascii", "replace").strip(), match.group(1).decode("ascii", "replace")


def _decode_symbols(kernel: Path) -> tuple[dict[str, int], dict[str, str]]:
    """Decode kallsyms through the repository's own decoder.

    Returns addresses and, where the decoder supplies it, each symbol's type letter.  The
    type is what lets the group verdict say whether a shifted address is code or data; without
    it the caller must not call anything data, so an empty map is the honest answer.
    """
    from tools.research.decode_kernel_kallsyms import decode

    result = decode(kernel.read_bytes())
    if isinstance(result, tuple):
        result = result[0]
    if isinstance(result, dict):
        table = result.get("symbols") or result.get("entries") or []
        if table:
            return ({s["name"]: s["address"] for s in table},
                    {s["name"]: s["type"] for s in table if s.get("type")})
        pairs = result.get("names"), result.get("addresses")
        if pairs[0] and pairs[1]:
            return dict(zip(pairs[0], pairs[1])), {}
    if isinstance(result, list):
        return ({s["name"]: s["address"] for s in result},
                {s["name"]: s["type"] for s in result if s.get("type")})
    raise SystemExit(f"unexpected decoder result shape: {type(result)!r}")


def load_body(roots: list[Path], name: str) -> Body:
    body = Body(name)
    body.kernel = _find(roots, name, "vmlinux.bin")
    body.avcam = _find(roots, name, "av-cam.bin")
    body.libobj = _find(roots, name, "libObj.so")
    if body.kernel is None:
        body.notes.append("no vmlinux.bin in this body's unpacked tree")
    else:
        raw = body.kernel.read_bytes()
        body.kernel_sha256 = hashlib.sha256(raw).hexdigest()
        body.build, body.builder = _kernel_identity(raw)
        try:
            body.symbols, body.types = _decode_symbols(body.kernel)
        except Exception as exc:  # noqa: BLE001 - the decoder is fail-closed by design
            body.notes.append(f"kallsyms decode refused: {exc}")
    if body.avcam is None:
        body.notes.append("no av-cam.bin in this body's unpacked tree")
    else:
        try:
            table = find_table(body.avcam.read_bytes())
            body.command_ids = table.ids
            body.table_offset = table.offset
        except ValueError as exc:
            body.notes.append(str(exc))
    for module in ("usbg_video.ko", "usbg_audio.ko"):
        hit = _find(roots, name, module)
        body.uvc[module] = (hashlib.sha256(hit.read_bytes()).hexdigest() if hit else None)
    return body


def _nominal(name: str) -> bool:
    return not name.startswith(_LITERAL_PREFIXES)


#: Two kernels that agree on all but a handful of addresses differ only in embedded version
#: strings, which are themselves kernel symbols (``linux_proc_banner`` and friends).  A
#: threshold keeps the claim mechanical instead of an eyeball judgement.
ONE_CODE_OBJECT_TOLERANCE = 64


_CODE_TYPES = frozenset("Tt")


def _verdict(equal: int, shared: int, members: int, sample: "Body",
             differing: list[str] | None = None) -> str:
    if members == 1:
        return "unique build"
    if equal == shared:
        return "one code object"
    if shared - equal <= ONE_CODE_OBJECT_TOLERANCE:
        differing = differing or []
        if not sample.types:
            # No type information: say the count and nothing about what kind of symbol it is.
            return (f"one code object, {len(differing)} addresses differ "
                    f"(build {sample.build}); symbol types unavailable, so code and data are "
                    f"not distinguished")
        code = [n for n in differing if sample.types.get(n) in _CODE_TYPES]
        # Name the kinds of symbol that moved rather than calling every one a version string:
        # the nine that move between two real bodies include sqrt_oddadjust and six __func__.
        if code:
            return (f"one code object; {len(code)} of {len(differing)} differing addresses are "
                    f"function symbols (build {sample.build})")
        return (f"one code object; all {len(differing)} differing addresses are data "
                f"(build {sample.build})")
    if not sample.types:
        return f"one symbol set, {shared - equal:,} addresses shifted"
    code_diff = sum(1 for n in (differing or []) if sample.types.get(n) in _CODE_TYPES)
    if differing and code_diff == 0:
        return (f"one symbol set, {shared - equal:,} addresses shifted, "
                f"none of them function symbols")
    return f"one symbol set, {shared - equal:,} addresses shifted"


def compare(bodies: list[Body], reference: str) -> dict:
    ref = next((b for b in bodies if b.name == reference), None)
    if ref is None or not ref.symbols:
        raise SystemExit(f"reference body {reference!r} has no decoded kernel")
    ref_names = {n for n in ref.symbols if _nominal(n)}

    sets: dict[frozenset[str], list[str]] = {}
    for body in bodies:
        if body.symbols:
            sets.setdefault(frozenset(body.symbols), []).append(body.name)

    groups = []
    for names, members in sorted(sets.items(), key=lambda kv: (-len(kv[1]), kv[1][0])):
        sample = next(b for b in bodies if b.name == members[0])
        differing = [n for n in names if not all(
            next(b for b in bodies if b.name == m).symbols[n] == sample.symbols[n]
            for m in members)]
        equal = len(names) - len(differing)
        groups.append({
            "bodies": members,
            "builds": sorted({next(b for b in bodies if b.name == m).build or "?"
                              for m in members}),
            "shared_symbols": len(names),
            "identical_addresses": equal,
            "verdict": _verdict(equal, len(names), len(members), sample, differing),
        })

    per_body = {}
    ref_ids = set(ref.command_ids)
    for body in bodies:
        entry: dict[str, object] = {
            "complete": body.complete,
            "kernel_sha256": body.kernel_sha256,
            "build": body.build,
            "builder": body.builder,
            "kernel_symbols": len(body.symbols),
            "command_count": len(body.command_ids),
            "table_offset": body.table_offset,
            "uvc_modules": body.uvc,
            "notes": body.notes,
        }
        if body.symbols:
            names = {n for n in body.symbols if _nominal(n)}
            entry["added_vs_reference"] = len(names - ref_names)
            entry["removed_vs_reference"] = len(ref_names - names)
            entry["same_address_vs_reference"] = sum(
                1 for n in names & ref_names if body.symbols[n] == ref.symbols[n])
        if body.command_ids:
            ids = set(body.command_ids)
            entry["commands_added"] = sorted(ids - ref_ids)
            entry["commands_removed"] = sorted(ref_ids - ids)
        per_body[body.name] = entry

    return {
        "reference": reference,
        "bodies": per_body,
        "kernel_groups": groups,
        "distinct_kernel_sets": len(groups),
    }


def render(report: dict) -> str:
    out = [f"reference body: {report['reference']}",
           f"bodies: {len(report['bodies'])}  distinct kernel symbol sets: "
           f"{report['distinct_kernel_sets']}", ""]
    header = f"{'body':12s} {'build':22s} {'syms':>7s} {'+':>5s} {'-':>5s} {'cmds':>5s} {'uvc':>4s}"
    out += [header, "-" * len(header)]
    for name, e in sorted(report["bodies"].items(),
                          key=lambda kv: -(kv[1].get("kernel_symbols") or 0)):
        if not e["complete"]:
            out.append(f"{name:12s} incomplete: {'; '.join(e['notes'])}")
            continue
        out.append(
            f"{name:12s} {str(e['build']):22s} {e['kernel_symbols']:>7,} "
            f"{e['added_vs_reference']:>5} {e['removed_vs_reference']:>5} "
            f"{e['command_count']:>5} {'yes' if e['uvc_modules']['usbg_video.ko'] else 'no':>4}")
    out += ["", "shared kernels:"]
    for g in report["kernel_groups"]:
        if len(g["bodies"]) > 1:
            out.append(f"  {', '.join(g['bodies'])}: {g['verdict']} "
                       f"({g['shared_symbols']:,} symbols, "
                       f"{g['identical_addresses']:,} identical addresses)")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", type=Path, nargs="+",
                        help="one or more directories of unpacked bodies; a body is looked up "
                             "in each in turn")
    parser.add_argument("--reference", default="a6400", help="body to diff against")
    parser.add_argument("--json", type=Path, help="also write the full report here")
    parser.add_argument("--only", nargs="*", help="restrict to these body directory names")
    parser.add_argument("--eyeaf-table", action="store_true",
                        help="also run the 0x413b field sweep for every body (E0432)")
    args = parser.parse_args(argv)

    for root in args.root:
        if not root.is_dir():
            print(f"not a directory: {root}", file=sys.stderr)
            return 2
    seen: list[str] = []
    for root in args.root:
        for p in sorted(root.iterdir()):
            if p.is_dir() and p.name not in seen:
                seen.append(p.name)
    names = args.only or seen
    bodies = [load_body(args.root, n) for n in names]
    report = compare(bodies, args.reference)
    print(render(report), end="")
    if args.eyeaf_table:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from av_eyeaf_field import analyse as eyeaf
        print("\n0x413b (Movie Eye AF) field sweep:")
        print(f"  {'body':12s} {'handler':>10s} {'field':>7s} {'cache':>11s} {'wr':>4s} {'rd':>4s}")
        for body in bodies:
            if body.avcam is None:
                continue
            try:
                r = eyeaf(body.avcam, 0x413B)
            except ValueError as exc:
                print(f"  {body.name:12s} {exc}")
                continue
            if not r["present"]:
                print(f"  {body.name:12s} {'absent':>10s}")
                continue
            print(f"  {body.name:12s} {r['handler']:#10x} {r['field']:#7x} "
                  f"{r['cache']:#11x} {r['writes']:>4d} {r['reads']:>4d}")
    if args.json:
        args.json.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
        print(f"\nwrote {args.json}", file=sys.stderr)
    incomplete = [n for n, e in report["bodies"].items() if not e["complete"]]
    return 3 if incomplete else 0


if __name__ == "__main__":
    raise SystemExit(main())
