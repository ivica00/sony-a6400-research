"""Contract tests for reading an ELF's symbol tables.

The point of this module is a name-to-address map obtained without disassembling anything: the
camera's libraries ship with their symbol tables intact, so function names are available before
a single instruction is decoded. Tests run without a camera or firmware; the real-library cases
are opt-in through ``A6400_UNPACKED_ROOT``.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "research"))

from elf_symbols import Symbol, functions, read_symbols  # noqa: E402


class ElfSymbolTests(unittest.TestCase):
    def test_rejects_a_file_that_is_not_an_elf(self) -> None:
        with self.assertRaises(ValueError):
            read_symbols(Path(__file__))

    def test_rejects_a_truncated_elf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "short.elf"
            path.write_bytes(b"\x7fELF\x01\x01\x01")
            with self.assertRaises(ValueError):
                read_symbols(path)

    def test_functions_keeps_only_code_symbols(self) -> None:
        symbols = [
            Symbol("a_func", 0x1000, 16, "T", "symtab"),
            Symbol("a_local", 0x1010, 8, "t", "symtab"),
            Symbol("a_data", 0x2000, 4, "D", "symtab"),
            Symbol("a_str", 0x3000, 8, "r", "symtab"),
        ]
        kept = functions(symbols)
        self.assertEqual([s.name for s in kept], ["a_func", "a_local"])

    def test_symbol_is_a_named_tuple_with_the_documented_fields(self) -> None:
        sym = Symbol("n", 1, 2, "T", "dynsym")
        self.assertEqual((sym.name, sym.address, sym.size, sym.type, sym.source),
                         ("n", 1, 2, "T", "dynsym"))


class RealLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        import os
        raw = os.environ.get("A6400_UNPACKED_ROOT")
        if not raw:
            self.skipTest("A6400_UNPACKED_ROOT not set; no unpacked body available")
        root = Path(raw)
        candidates = sorted(root.glob(
            "*/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libObj.so"))
        if not candidates:
            self.skipTest("no libObj.so under A6400_UNPACKED_ROOT")
        self.lib = candidates[0]

    def test_reads_a_real_shared_object(self) -> None:
        symbols = read_symbols(self.lib)
        funcs = functions(symbols)
        self.assertGreater(len(funcs), 3200, "the a6400 libObj.so has 3,297 code symbols")
        self.assertTrue(any(s.name.startswith("_ZN") for s in funcs),
                        "C++ mangled names must survive, or nothing downstream can be named")
        self.assertTrue(any(s.source == "dynsym" for s in funcs))

    def test_symbols_are_sorted_and_unique(self) -> None:
        symbols = read_symbols(self.lib)
        addresses = [s.address for s in symbols]
        self.assertEqual(addresses, sorted(addresses))
        keys = [(s.name, s.address) for s in symbols]
        self.assertEqual(len(keys), len(set(keys)), "duplicates must be removed")


if __name__ == "__main__":
    unittest.main()
