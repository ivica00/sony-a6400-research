"""Constructed ARM/Thumb fixtures validate bounded research execution outcomes."""
import unittest
from pathlib import Path

from test_interpreter_probe import make_elf
from project_paths import PROJECT_ROOT
from tools.research.boot_event_trace import run_window, RETURN


class BootWindowTests(unittest.TestCase):
    def run_code(self, code, terminals=None, budget=20):
        folder = PROJECT_ROOT / 'artifacts/tests/boot-window'
        folder.mkdir(parents=True, exist_ok=True)
        image = make_elf(folder / 'window.elf', code, dynamic=False)
        return run_window(image, 0x8101, (0x8100, 0x8100 + len(code)), lambda mu: None,
                          terminals or {}, budget)[0]

    def test_normal_return_requires_recorded_terminal(self):
        report = self.run_code(bytes.fromhex('07207047'), {RETURN: 'normal_return'})
        self.assertEqual(report['status'], 'normal_return')
        self.assertEqual(report['registers']['r0'], 7)
        self.assertEqual(len(report['trace']), 2)
        self.assertEqual(report['boundary_pc'], RETURN)

    def test_unexpected_branch_is_not_a_return(self):
        report = self.run_code(bytes.fromhex('7047'))
        self.assertEqual(report['status'], 'unexpected_control_flow')

    def test_budget_exhaustion_is_not_a_boundary(self):
        report = self.run_code(bytes.fromhex('fee7'), budget=7)
        self.assertEqual(report['status'], 'instruction_budget_exhausted')
        self.assertEqual(len(report['trace']), 7)

    def test_unmapped_read_is_a_fault(self):
        report = self.run_code(bytes.fromhex('00200068'))
        self.assertEqual(report['status'], 'execution_fault')
        self.assertIn('error', report)
