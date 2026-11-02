"""Constructed ARM routines check the isolated research window's stop semantics."""
import struct
import unittest

from unicorn import arm_const as arm
from tools.research.liro_startup_trace import BASE, run_slice


class LiroWindowTests(unittest.TestCase):
    def test_external_call_is_stopped_before_execution(self):
        code = struct.pack('<2I', 0xe3a01001, 0xebfffffe)
        report, mu = run_slice(code, 0, [(0, 4)], {4: 'external_call_boundary'}, {})
        self.assertEqual(report['status'], 'external_call_boundary')
        self.assertEqual(len(report['trace']), 1)
        self.assertEqual(mu.reg_read(arm.UC_ARM_REG_R1), 1)
        self.assertEqual(report['kernel_responses_supplied'], 0)

    def test_unexpected_branch_is_not_a_completed_window(self):
        code = struct.pack('<3I', 0xe12fff1e, 0xe1a00000, 0xe1a00000)
        report, _ = run_slice(code, 0, [(0, 4)], {}, {arm.UC_ARM_REG_LR: BASE + 8})
        self.assertEqual(report['status'], 'unexpected_control_flow')
        self.assertEqual(report['boundary_offset'], 8)

    def test_budget_exhaustion_is_not_a_completed_window(self):
        report, _ = run_slice(struct.pack('<I', 0xeafffffe), 0, [(0, 4)], {}, {}, budget=7)
        self.assertEqual(report['status'], 'instruction_budget_exhausted')
        self.assertEqual(len(report['trace']), 7)

    def test_code_mapping_is_not_writable(self):
        code = struct.pack('<I', 0xe5801000)
        report, mu = run_slice(code, 0, [(0, 4)], {}, {arm.UC_ARM_REG_R0: BASE, arm.UC_ARM_REG_R1: 0})
        self.assertEqual(report['status'], 'execution_fault')
        self.assertEqual(bytes(mu.mem_read(BASE, 4)), code)
