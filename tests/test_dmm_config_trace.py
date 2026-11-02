"""Constructed ARM execution checks; no proprietary inputs are required."""
import struct
import unittest
from unittest.mock import patch

import unicorn
from unicorn import arm_const as arm

from tools.research.dmm_config_trace import DmmConfigProbe, CODE, BSS, STACK, RETURN, CONFIG_BASE


class DmmProbeTests(unittest.TestCase):
    def setUp(self):
        self.probe = DmmConfigProbe.__new__(DmmConfigProbe)
        p = self.probe
        p.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        for address in (CODE, BSS, STACK + 0x2000, RETURN, CONFIG_BASE):
            p.mu.mem_map(address, 4096)
        p.config = b'abcd'
        p.imports, p.unresolved, p.config_reads = {}, [], []
        p.reader_entry = 0
        p.placements = {'.text': CODE}
        p.elf = type('FixtureElf', (), {'get_section': lambda self, n: type('Section', (), {'name': '.text'})()})()
        p.mu.hook_add(unicorn.UC_HOOK_CODE, p._code)
        p.mu.hook_add(unicorn.UC_HOOK_MEM_READ, p._read)
        p.mu.hook_add(unicorn.UC_HOOK_MEM_INVALID, p._invalid)

    def run_code(self, words, args=(), budget=100):
        self.probe.mu.mem_write(CODE, struct.pack('<' + 'I' * len(words), *words))
        self.probe.mu.ctl_remove_cache(CODE, CODE + 4096)
        with patch('tools.research.dmm_config_trace.symbol', return_value={'st_shndx': 1, 'st_value': 0}):
            return self.probe.call('fixture', args, budget)

    def test_original_arm_return_and_budget_are_distinct(self):
        result = self.run_code([0xe3a00007, 0xe12fff1e])  # mov r0,7; bx lr
        self.assertEqual((result['status'], result['return_value']), ('isolated_function_return', 7))
        result = self.run_code([0xeafffffe], budget=5)  # b .
        self.assertEqual(result['status'], 'instruction_budget_exhausted')
        self.assertEqual(result['instructions_executed'], 5)

    def test_unknown_ipc_is_observed_without_success_or_mutation(self):
        self.probe.imports[CODE] = 'osal_snd_sync_direct'
        request = bytes(range(32))
        self.probe.mu.mem_write(BSS + 64, request)
        result = self.run_code([0xebfffffe], (0x910042, BSS + 64, 32, 1))
        self.assertEqual(result['status'], 'unsupported_kernel_import')
        self.assertEqual(result['return_value'], 0x910042)
        self.assertEqual(result['boundary']['request_prefix_hex'], request.hex())
        self.assertEqual(bytes(self.probe.mu.mem_read(BSS + 64, 32)), request)

    def test_config_padding_is_not_supplied_input(self):
        result = self.run_code([0xe5900000, 0xe12fff1e], (CONFIG_BASE + 2,))  # ldr r0,[r0]
        self.assertEqual(result['status'], 'config_read_past_supplied_bytes')

    def test_unresolved_literal_stops_original_load(self):
        self.probe.unresolved = [(BSS + 64, BSS + 68, {'symbol': 'unknown_global'})]
        result = self.run_code([0xe5900000, 0xe12fff1e], (BSS + 64,))
        self.assertEqual(result['status'], 'unresolved_module_data')

    def test_fill_respects_permissions_and_preserves_surrounding_bytes(self):
        self.probe.imports[CODE] = 'memset'
        self.probe.mu.mem_write(BSS + 64, b'ABCDEFGH')
        result = self.run_code([0xebfffffe, 0xe51ff004, RETURN], (BSS + 66, 0x178, 3))
        self.assertEqual(result['status'], 'isolated_function_return')
        self.assertEqual(bytes(self.probe.mu.mem_read(BSS + 64, 8)), b'ABxxxFGH')
        self.probe.mu.mem_protect(BSS, 4096, unicorn.UC_PROT_READ)
        result = self.run_code([0xebfffffe], (BSS + 64, 0, 4))
        self.assertEqual(result['status'], 'unsupported_fill_range')
        self.assertEqual(bytes(self.probe.mu.mem_read(BSS + 64, 8)), b'ABxxxFGH')

    def test_division_by_zero_stops_without_result(self):
        self.probe.imports[CODE] = '__aeabi_uidiv'
        result = self.run_code([0xebfffffe], (123, 0))
        self.assertEqual(result['status'], 'division_by_zero_boundary')
        self.assertEqual(result['return_value'], 123)


if __name__ == '__main__':
    unittest.main()
