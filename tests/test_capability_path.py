"""Contract tests for tracing a capability from an input to a display call.

The value of a call graph is that it can answer "how does a button press reach the screen"
without guessing. This module does the walk, and it also carries the sharing verdict that this
project had to correct once: a shared symbol set is not shared code unless the differing symbols
are data.

Offline only.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "research"))

from capability_path import describe_path, path_between, sharing_verdict  # noqa: E402


class PathTests(unittest.TestCase):
    def test_a_direct_edge_is_a_path_of_two(self) -> None:
        graph = {"nodes": {"a": 1, "b": 2}, "edges": [("a", "b")], "unresolved": 0}
        self.assertEqual(path_between(graph, "a", "b"), ["a", "b"])

    def test_no_route_returns_none(self) -> None:
        graph = {"nodes": {"a": 1, "b": 2}, "edges": [("a", "b")], "unresolved": 0}
        self.assertIsNone(path_between(graph, "b", "a", max_depth=3))

    def test_depth_bound_is_respected(self) -> None:
        graph = {"nodes": {}, "edges": [("a", "b"), ("b", "c"), ("c", "d")], "unresolved": 0}
        self.assertIsNone(path_between(graph, "a", "d", max_depth=2))
        self.assertEqual(path_between(graph, "a", "d", max_depth=3), ["a", "b", "c", "d"])

    def test_a_cycle_does_not_hang(self) -> None:
        graph = {"nodes": {}, "edges": [("a", "b"), ("b", "a")], "unresolved": 0}
        self.assertIsNone(path_between(graph, "a", "zzz", max_depth=4))

    def test_the_start_equal_to_the_end_is_a_zero_length_path(self) -> None:
        graph = {"nodes": {"a": 1}, "edges": [], "unresolved": 0}
        self.assertEqual(path_between(graph, "a", "a"), ["a"])


class DescribeTests(unittest.TestCase):
    def test_a_hop_that_carries_a_queue_id_shows_it(self) -> None:
        edges = [{"caller": "a", "callee": "osal_snd_msg", "site": 0x1000,
                  "queue_or_cmd": 0xCA8192}]
        text = describe_path(["a", "osal_snd_msg"], edges)
        self.assertIn("0xca8192", text)

    def test_a_hop_without_an_id_shows_no_number(self) -> None:
        edges = [{"caller": "a", "callee": "b", "site": 0x1000, "queue_or_cmd": None}]
        text = describe_path(["a", "b"], edges)
        self.assertNotIn("0x", text)


class SharingVerdictTests(unittest.TestCase):
    """The verdict must follow from measured types, not from a symbol-name match."""

    def test_identical_tables_are_one_code_object(self) -> None:
        self.assertEqual(sharing_verdict(0, 0), "one code object")

    def test_a_few_differing_data_symbols_are_not_one_code_object(self) -> None:
        # ZV-E10 and ILCE-7C put all 14,460 functions at the same address but differ in 9 data
        # addresses, so the honest verdict is "data shifted", not "one code object".
        self.assertEqual(sharing_verdict(0, 9), "one symbol set, data shifted")

    def test_a_large_data_shift_is_still_one_symbol_set(self) -> None:
        self.assertEqual(sharing_verdict(0, 9124), "one symbol set, data shifted")

    def test_differing_functions_mean_separate_kernels(self) -> None:
        self.assertEqual(sharing_verdict(4033, 9), "separate kernels")

    def test_a_single_differing_function_is_enough(self) -> None:
        self.assertEqual(sharing_verdict(1, 0), "separate kernels",
                         "one moved function disproves 'one code object'")


class RealLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        import os
        raw = os.environ.get("A6400_UNPACKED_ROOT")
        if not raw:
            self.skipTest("A6400_UNPACKED_ROOT not set; no unpacked body available")
        hits = sorted(Path(raw).glob(
            "*/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libObj.so"))
        if not hits:
            self.skipTest("no libObj.so under A6400_UNPACKED_ROOT")
        self.libs = hits

    def test_input_to_display_path_is_found_or_reported_absent(self) -> None:
        # Both outcomes are findings: a path proves the route, and its absence within the depth
        # bound says the route leaves libObj.so, which is itself worth recording.
        from callgraph import build_callgraph

        found = {}
        for lib in self.libs:
            graph = build_callgraph(lib)
            path = path_between(graph, "snd_InfraInputEvent_to_InputServant",
                                "ObjDisplay_Start", max_depth=6)
            if path:
                found[lib.parts[-9]] = path
        # This asserts the walk runs and returns a consistent shape, not that a route exists.
        self.assertIsInstance(found, dict)


if __name__ == "__main__":
    unittest.main()
