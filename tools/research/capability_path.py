#!/usr/bin/env python3
"""Follow one capability through the call graph, and judge whether two binaries share code.

Two jobs, both needed to answer "how does a button press reach the screen".

**Path.** A breadth-first walk over direct-call edges, bounded in depth so a 20 MB library cannot
hang the caller. The bound is part of the answer: "no path within six hops" is a finding, not a
failure, because it locates the route's exit from the library.

**Verdict.** Whether two kernels are one code object. This project published a wrong version of
that verdict once, by comparing symbol *names* instead of symbol *types*: the a6100A, a7 III and
a7R IVA share 24,351 names while 4,033 of their 4,042 differing addresses are functions, so they
are three separate kernels. The rule here is mechanical: any differing function symbol disproves
"one code object".

Offline only.
"""
from __future__ import annotations

import argparse
import sys
from collections import deque
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))


def path_between(graph: dict[str, Any], start: str, end: str,
                 max_depth: int = 6) -> list[str] | None:
    """Shortest direct-call path from ``start`` to ``end``, or ``None`` within the bound."""
    if start == end:
        return [start]
    adjacency: dict[str, list[str]] = {}
    for caller, callee in graph["edges"]:
        adjacency.setdefault(caller, []).append(callee)

    queue: deque[tuple[str, list[str]]] = deque([(start, [start])])
    seen = {start}
    while queue:
        node, route = queue.popleft()
        if len(route) - 1 >= max_depth:
            continue
        for neighbour in adjacency.get(node, ()):
            if neighbour in seen:
                continue
            extended = route + [neighbour]
            if neighbour == end:
                return extended
            seen.add(neighbour)
            queue.append((neighbour, extended))
    return None


def describe_path(path: list[str], edges: list[dict[str, Any]]) -> str:
    """One line per hop, with the queue id when that hop carries a constant one."""
    by_pair: dict[tuple[str, str], int | None] = {}
    for edge in edges:
        by_pair.setdefault((edge["caller"], edge["callee"]), edge["queue_or_cmd"])

    lines: list[str] = []
    for index, (caller, callee) in enumerate(zip(path, path[1:]), start=1):
        value = by_pair.get((caller, callee))
        suffix = f"  (queue 0x{value:x})" if value is not None else ""
        lines.append(f"{index}. {caller} -> {callee}{suffix}")
    return "\n".join(lines)


def sharing_verdict(code_differing: int, data_differing: int) -> str:
    """How two binaries relate, from the counts of differing symbols by kind.

    ``code_differing`` is the number of function symbols whose addresses differ, and
    ``data_differing`` the same for data symbols. A single differing function is enough to say
    the code is not identical: that is the correction this project had to make.
    """
    if code_differing > 0:
        return "separate kernels"
    if data_differing > 0:
        return "one symbol set, data shifted"
    return "one code object"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--image", type=Path, help="ELF to build the graph from")
    parser.add_argument("--start", default="snd_InfraInputEvent_to_InputServant")
    parser.add_argument("--end", default="ObjDisplay_Start")
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("A", "B"),
                        help="verdict for two kernel symbol dumps (JSON produced by "
                             "tools/research/decode_kernel_kallsyms.py)")
    args = parser.parse_args(argv)

    if args.compare:
        import json

        def counts(path: Path) -> tuple[int, int, int, int]:
            data = json.loads(Path(path).read_text())
            table = data["symbols"]
            names = {(s["name"], s["address"], s.get("type", "?")) for s in table}
            return len(names), 0, 0, 0

        left = json.loads(args.compare[0].read_text())["symbols"]
        right = json.loads(args.compare[1].read_text())["symbols"]
        left_map = {s["name"]: (s["address"], s.get("type", "?")) for s in left}
        right_map = {s["name"]: (s["address"], s.get("type", "?")) for s in right}
        shared = set(left_map) & set(right_map)
        code_differing = sum(
            1 for name in shared
            if left_map[name][0] != right_map[name][0] and left_map[name][1] in ("T", "t"))
        data_differing = sum(
            1 for name in shared
            if left_map[name][0] != right_map[name][0] and left_map[name][1] not in ("T", "t"))
        print(f"shared names: {len(shared)}  code differing: {code_differing}  "
              f"data differing: {data_differing}")
        print(f"verdict: {sharing_verdict(code_differing, data_differing)}")
        return 0

    if args.image is None:
        parser.error("--image is required unless --compare is used")

    from callgraph import build_callgraph
    from ipc_edges import ipc_edges

    graph = build_callgraph(args.image)
    path = path_between(graph, args.start, args.end, args.max_depth)
    if path is None:
        print(f"no direct-call path from {args.start} to {args.end} "
              f"within {args.max_depth} hops", file=sys.stderr)
        return 2
    print(describe_path(path, ipc_edges(args.image)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
