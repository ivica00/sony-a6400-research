"""Negative capability checks and real ARM stop-reason checks; no camera needed."""
import contextlib
import io
import struct
import json
import unittest
from unittest.mock import patch
from pathlib import Path

from legacy.cxd90045_hle_emulator import CXD90045_HLE_Emulator, RAM_BASE, MMIO_BASE
from legacy.execution_audit import UnsupportedBehavior
from project_paths import PROJECT_ROOT


class ExecutionAuditTests(unittest.TestCase):
    def setUp(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.emu = CXD90045_HLE_Emulator(mode='strict')

    def code(self, words):
        self.emu.mu.mem_write(RAM_BASE, b''.join(struct.pack('<I', w) for w in words))
        self.emu.mu.ctl_remove_cache(RAM_BASE, RAM_BASE + 4096)

    def test_missing_symbol_rejected(self):
        with self.assertRaises(UnsupportedBehavior):
            self.emu.register_default_stub('missing_test_symbol')
        self.assertNotIn('missing_test_symbol', self.emu.symbols)

    def test_unsupported_relocation_rejected(self):
        class UnknownRelocations:
            name = '.rela.dyn'
            def iter_relocations(self):
                return iter([{'r_info_type': 999, 'r_offset': 0}])
        class FixtureELF:
            def iter_sections(self):
                return iter([UnknownRelocations()])
        with patch('elftools.elf.relocation.RelocationSection', UnknownRelocations):
            with self.assertRaises(UnsupportedBehavior):
                self.emu.apply_relocations(FixtureELF(), RAM_BASE, None)
        self.assertEqual(self.emu.audit_events[-1]['kind'], 'unsupported_relocation')

    def test_mocks_and_host_ui_rejected(self):
        for operation in (self.emu.setup_sony_subsystems, self.emu.render_active_screen,
                          self.emu.render_menu_framebuffer):
            with self.assertRaises(UnsupportedBehavior):
                operation()

    def test_mmio_rejected_in_executing_code(self):
        self.code([0xe5900000, 0xe12fff1e])  # ldr r0,[r0]; bx lr
        with self.assertRaises(UnsupportedBehavior):
            self.emu.call_function(RAM_BASE, MMIO_BASE)
        self.assertEqual(self.emu.last_execution['status'], 'unsupported')

    def test_unmapped_access_rejected(self):
        self.code([0xe5900000, 0xe12fff1e])
        with self.assertRaises(UnsupportedBehavior):
            self.emu.call_function(RAM_BASE, 0x80000000)
        with self.assertRaises(Exception):
            self.emu.mu.mem_read(0x80000000, 4)

    def test_hle_service_rejected(self):
        with self.assertRaises(UnsupportedBehavior):
            self.emu.call_function(self.emu.stub_by_name['ioctl'])

    def test_return_is_success(self):
        self.code([0xe3a0002a, 0xe12fff1e])  # mov r0,#42; bx lr
        self.assertEqual(self.emu.call_function(RAM_BASE), 42)
        self.assertEqual(self.emu.last_execution['status'], 'returned')

    def test_budget_is_not_success(self):
        self.code([0xeafffffe])  # b .
        self.assertIsNone(self.emu.call_function(RAM_BASE, instruction_budget=20))
        self.assertEqual(self.emu.last_execution['status'], 'instruction_budget_exhausted')

    def test_timeout_is_not_success(self):
        self.code([0xeafffffe])
        self.assertIsNone(self.emu.call_function(RAM_BASE, timeout_us=1000,
                                               instruction_budget=1000000000))
        self.assertEqual(self.emu.last_execution['status'], 'timeout')

    def test_fault_is_not_success(self):
        self.code([0xe7f000f0])  # undefined instruction
        self.assertIsNone(self.emu.call_function(RAM_BASE))
        self.assertEqual(self.emu.last_execution['status'], 'fault')

    def test_research_menu_and_report(self):
        self.emu.mode = 'research'
        self.assertEqual(self.emu.render_menu_framebuffer().size, (960, 540))
        temporary_root = PROJECT_ROOT / 'artifacts' / 'tests'
        temporary_root.mkdir(parents=True, exist_ok=True)
        target = temporary_root / 'research-report.json'
        self.emu.write_execution_report(target)
        report = json.loads(target.read_text(encoding='utf-8'))
        self.assertFalse(report['firmware_fidelity_validated'])
        self.assertEqual(report['events'][0]['kind'], 'host_rendering')


if __name__ == '__main__':
    unittest.main()
