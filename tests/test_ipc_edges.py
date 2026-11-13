"""Contract tests for enumerating IPC edges and the queue id each one carries.

The camera's application layer talks over OSAL messages: a send names a queue id, and that id is
what links a button event to the code that handles it. This module turns "somewhere in 20 MB it
calls osal_snd_msg" into a table of call sites and the constant each one passes.

The hard part is not finding the call; it is deciding what argument it carries. A register set
from another register or from memory has no constant value, and the tool says so rather than
inventing one.

Offline only.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "research"))

from ipc_edges import constant_arguments, edges_to_tsv, ipc_edges  # noqa: E402


class ConstantArgumentTests(unittest.TestCase):
    def test_returns_none_when_the_register_is_never_set(self) -> None:
        data = bytes.fromhex("00bf00bf00bf00bf")     # four nops
        self.assertIsNone(constant_arguments(data, 0x1000, 0x1004, 0))

    def test_finds_an_immediate_moved_into_the_register_before_the_site(self) -> None:
        # movs r0,#0x2a at 0x1000 (0x202a), then the call site at 0x1004
        data = bytes.fromhex("2a20") + bytes.fromhex("00bf00bf")
        self.assertEqual(constant_arguments(data, 0x1000, 0x1004, 0), 0x2A)

    def test_a_register_copied_from_another_register_has_no_constant(self) -> None:
        # mov r0,r1 (0x4608) then a call site: the value is not knowable statically
        data = bytes.fromhex("0846") + bytes.fromhex("00bf00bf")
        self.assertIsNone(constant_arguments(data, 0x1000, 0x1004, 0))


class TsvTests(unittest.TestCase):
    def test_tsv_has_the_documented_header(self) -> None:
        text = edges_to_tsv([{"caller": "a", "callee": "osal_snd_msg",
                              "site": 0x1000, "queue_or_cmd": 0xCA8192}])
        self.assertTrue(text.startswith("caller\tcallee\tsite\tqueue_or_cmd\n"))

    def test_an_unknown_queue_is_written_as_empty_not_zero(self) -> None:
        text = edges_to_tsv([{"caller": "a", "callee": "osal_snd_msg",
                              "site": 0x1000, "queue_or_cmd": None}])
        fields = text.splitlines()[1].split("\t")
        self.assertEqual(fields[3], "", "an unknown id must not become 0x0, which is a real id")

    def test_queue_ids_are_written_hexadecimal(self) -> None:
        text = edges_to_tsv([{"caller": "a", "callee": "osal_snd_msg",
                              "site": 0x1000, "queue_or_cmd": 0xCA8192}])
        self.assertIn("0xca8192", text)


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

    def test_edges_of_a_real_library_include_send_sites(self) -> None:
        # Not every body's libObj.so calls osal_snd_msg or ioctl directly — the a6100a build
        # reaches them through wrappers — so this checks across the available bodies rather than
        # assuming the first by name is representative.
        found = {}
        for lib in self.hits:
            edges = ipc_edges(lib)
            if edges:
                found[lib.parts[-9]] = sorted({e["callee"] for e in edges})
        self.assertTrue(found, "no body's libObj.so contains a direct IPC call site")

    def test_an_edge_that_carries_a_constant_is_reported_as_a_number(self) -> None:
        with_constant = []
        for lib in self.hits:
            for edge in ipc_edges(lib):
                if edge["queue_or_cmd"] is not None:
                    with_constant.append(edge)
        self.assertTrue(with_constant,
                        "at least some call sites must pass a constant queue id")


if __name__ == "__main__":
    unittest.main()
