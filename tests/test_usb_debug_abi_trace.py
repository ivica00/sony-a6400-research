import hashlib
import struct
import tempfile
import unittest
from pathlib import Path

from tools.research.usb_debug_abi_trace import trace

ROOT = Path(__file__).resolve().parents[1]


class UsbDebugAbiInputTests(unittest.TestCase):
    def setUp(self):
        fixtures = ROOT / "artifacts" / "tests"
        fixtures.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="usb-debug-abi-", dir=fixtures)
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "input.so"

    def test_changed_source_is_rejected_before_parsing(self):
        self.path.write_bytes(b"changed input")
        expected = hashlib.sha256(b"preserved input").hexdigest()
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            trace(self.path, expected_sha256=expected)

    def elf_header(self, machine):
        identification = b"\x7fELF\x01\x01\x01" + bytes(9)
        return struct.pack("<16sHHIIIIIHHHHHH", identification, 3, machine, 1,
                           0, 0, 0, 0, 52, 32, 0, 40, 0, 0)

    def test_other_cpu_library_is_not_executed_as_arm(self):
        self.path.write_bytes(self.elf_header(3))
        with self.assertRaisesRegex(ValueError, "ARM shared library"):
            trace(self.path)

    def test_arm_library_without_symbols_is_rejected(self):
        self.path.write_bytes(self.elf_header(40))
        with self.assertRaisesRegex(ValueError, "Missing dynamic symbol table"):
            trace(self.path)
