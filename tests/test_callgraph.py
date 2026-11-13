"""Contract tests for building a direct-call graph over a packaged library.

The camera's libraries are unstripped, so a direct call can be resolved to a name. That turns
`libObj.so` from 20 MB of bytes into a map of who calls what — the thing needed to follow a
capability instead of guessing at it.

Only direct calls are followed. An indirect call through a register is counted as unresolved
rather than invented: a guessed edge would make a path look traced when it is not.

Offline only.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "research"))

from callgraph import build_callgraph, callers_of, direct_calls  # noqa: E402


class DirectCallTests(unittest.TestCase):
    def test_a_real_thumb_blx_is_recorded_as_an_edge(self) -> None:
        # Bytes taken from the a6400 libupdatertalk.so: `blx #0x59c` at 0x5da. This is a real
        # ARM Thumb-2 BLX, including its H flag and word-aligned PC, rather than a guessed
        # encoding; an earlier attempt at a hand-built encoding tested nothing.
        data = bytes.fromhex("fff7e0ef")
        edges = direct_calls(data, 0x5da)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0], (0x5da, 0x59C))

    def test_a_non_branch_instruction_produces_no_edge(self) -> None:
        data = bytes.fromhex("00bf")         # nop
        self.assertEqual(direct_calls(data, 0x1000), [])


class GraphTests(unittest.TestCase):
    def test_callers_of_a_known_name_are_listed(self) -> None:
        graph = {"nodes": {"a": 0x1000, "b": 0x2000}, "edges": [("a", "b")], "unresolved": 0}
        self.assertEqual(callers_of(graph, "b"), ["a"])

    def test_callers_of_an_unvisited_name_is_empty(self) -> None:
        graph = {"nodes": {"a": 0x1000}, "edges": [], "unresolved": 0}
        self.assertEqual(callers_of(graph, "zzz"), [])

    def test_an_address_without_a_symbol_becomes_a_sub_name(self) -> None:
        # Exercises the naming rule without needing a real ELF: an unresolved callee address is
        # named "sub_XXXXXXXX" so paths stay printable.
        from callgraph import _name_for
        self.assertEqual(_name_for(0x1234, {}), "sub_00001234")
        self.assertEqual(_name_for(0x1234, {0x1234: "known"}), "known")


class RealLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        import os
        raw = os.environ.get("A6400_UNPACKED_ROOT")
        if not raw:
            self.skipTest("A6400_UNPACKED_ROOT not set; no unpacked body available")
        self.hits = sorted(Path(raw).glob(
            "*/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libObj.so"))
        if not self.hits:
            self.skipTest("no libObj.so under A6400_UNPACKED_ROOT")
        self.lib = self.hits[0]

    def test_graph_of_a_real_library_resolves_most_edges(self) -> None:
        graph = build_callgraph(self.lib)
        # libObj.so defines 1,852 code symbols inside .text; the other 1,444 of its 3,297
        # FUNC symbols are imports with address 0, which are reported separately.
        self.assertGreater(len(graph["nodes"]), 1800)
        self.assertGreater(len(graph["imports"]), 1000)
        self.assertGreater(len(graph["edges"]), 10000)
        # These libraries carry `.dynsym` only, so local functions are unnamed and most edges
        # land on `sub_XXXXXXXX`. That is a property of the shipped files, not a defect: what
        # matters is that the named subset exists and is usable.
        self.assertGreater(graph["named_edges"], 0,
                           "some edges must resolve to real symbol names")
        self.assertLess(graph["named_fraction"], 0.5,
                        "if this rises, the libraries were built with .symtab and the record's "
                        "statement about local symbols being unnamed needs revisiting")

    def test_callers_of_a_real_import_are_found_on_more_than_one_body(self) -> None:
        # Not every body's libObj.so calls osal_snd_msg directly (the a6100a does not), so this
        # checks across the available bodies instead of assuming the first one by name is
        # representative — the assumption that made an earlier version of this test fail.
        found = {}
        for lib in self.hits:
            graph = build_callgraph(lib)
            if callers_of(graph, "osal_snd_msg"):
                found[lib.parts[-9]] = len(callers_of(graph, "osal_snd_msg"))
        self.assertTrue(found, "no body's libObj.so calls osal_snd_msg, so the IPC work is moot")


if __name__ == "__main__":
    unittest.main()
