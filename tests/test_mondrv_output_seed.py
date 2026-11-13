"""Unit tests for seed_mondrv_output (MonDrv::mp_output queue seed)."""
import struct
import unittest

import unicorn

from src.a6400.execution.interpreter_probe import drain_mondrv_output, seed_mondrv_output

PAGE = 0x52000000          # fake libMWF page
MP_OUTPUT = PAGE + 0xfe0   # stands in for base + mp_output
REGION = 0x53000000        # stands in for the allocator region


class MondrvOutputSeedTests(unittest.TestCase):
    def setUp(self):
        self.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_THUMB)
        self.mu.mem_map(PAGE, 0x1000, unicorn.UC_PROT_ALL)
        self.mu.mem_map(REGION, 0x8000, unicorn.UC_PROT_ALL)

    def test_seeds_empty_queue_and_pointer(self):
        self.assertTrue(seed_mondrv_output(self.mu, MP_OUTPUT, REGION))
        obj = struct.unpack('<IIII', bytes(self.mu.mem_read(REGION, 16)))
        self.assertEqual(obj, (REGION + 0x10, REGION + 0x14, REGION + 0x20, 0x7bf0))
        self.assertEqual(bytes(self.mu.mem_read(REGION + 0x10, 8)), bytes(8))
        self.assertEqual(struct.unpack('<I', bytes(self.mu.mem_read(MP_OUTPUT, 4)))[0], REGION)

    def test_no_write_when_pointer_already_set(self):
        self.mu.mem_write(MP_OUTPUT, struct.pack('<I', 0x12345678))
        self.mu.mem_write(REGION, b'\xaa' * 16)
        self.assertFalse(seed_mondrv_output(self.mu, MP_OUTPUT, REGION))
        self.assertEqual(struct.unpack('<I', bytes(self.mu.mem_read(MP_OUTPUT, 4)))[0], 0x12345678)
        self.assertEqual(bytes(self.mu.mem_read(REGION, 16)), b'\xaa' * 16)

    def test_drain_keeps_text_and_empties_queue(self):
        seed_mondrv_output(self.mu, MP_OUTPUT, REGION)
        self.mu.mem_write(REGION + 0x20 + 0x7bee, b'ab')
        self.mu.mem_write(REGION + 0x20, b'cd')
        self.mu.mem_write(REGION + 0x10, struct.pack('<II', 0x7bee, 2))  # wrapped
        entry = {}
        drain_mondrv_output(self.mu, REGION, entry)
        self.assertEqual(entry['text'], 'abcd')
        self.assertEqual(entry['drained'], 1)
        self.assertEqual(bytes(self.mu.mem_read(REGION + 0x10, 8)), bytes(8))
        drain_mondrv_output(self.mu, REGION, entry)  # already empty: no-op
        self.assertEqual(entry['drained'], 1)


if __name__ == '__main__':
    unittest.main()


class RearmAfterRestoreTests(unittest.TestCase):
    """rearm_checkpoint_hooks: re-find libc/libMWF from restored mmap records."""

    def _probe(self, queue_ptr, libc_sig=True):
        from types import SimpleNamespace
        from src.a6400.execution import interpreter_probe as ip
        probe = object.__new__(ip.InterpreterProbe)
        probe.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_THUMB)
        probe.mu.mem_map(PAGE, 0x1000, unicorn.UC_PROT_ALL)
        probe.mu.mem_map(REGION, ip.MONDRV_REGION_SIZE, unicorn.UC_PROT_ALL)
        probe.mu.mem_map(0x54000000, 0x60000, unicorn.UC_PROT_ALL)
        if libc_sig:
            probe.mu.mem_write(0x54000000 + 0x59bfc, bytes.fromhex('dff89424'))
        probe.mu.mem_write(MP_OUTPUT, struct.pack('<I', queue_ptr))
        probe.hook_mode, probe.report = 'fast', {}
        probe.filesystem = SimpleNamespace(cache={'/usr/lib/libMWF.so': b'elf'}, fds={})
        probe.mmap = SimpleNamespace(next_address=0x60000000, mappings=[
            {'address': PAGE, 'length': 0x1000, 'path': '/usr/lib/libMWF.so', 'offset': 0},
            {'address': 0x54000000, 'length': 0x60000, 'path': '/lib/libc-2.11.2.so', 'offset': 0},
            {'address': REGION, 'length': ip.MONDRV_REGION_SIZE, 'anonymous': True}])
        syms = {n: {'defined': True, 'value': v} for n, v in zip(ip.MONDRV_OUTPUT_SYMBOLS, (0xfe0, 0x100, 0x200))}
        self._orig = ip.inspect_elf_load_and_symbols
        ip.inspect_elf_load_and_symbols = lambda data, names: ([{'file_offset': 0, 'vaddr': 0}], syms) if data else (_ for _ in ()).throw(ValueError('empty'))
        self.addCleanup(setattr, ip, 'inspect_elf_load_and_symbols', self._orig)
        return probe

    def test_rearms_both_and_adopts_existing_queue(self):
        probe = self._probe(REGION)
        probe.rearm_checkpoint_hooks()
        self.assertEqual(probe.report['relocated_libc_it_repair']['base'], 0x54000000)
        entry = probe.report['mondrv_output_seed']
        self.assertTrue(entry['armed'])
        self.assertEqual(entry['queue'], REGION)
        self.assertEqual(entry['mp_output'], MP_OUTPUT)

    def test_fail_closed_without_elf_bytes_or_signature(self):
        probe = self._probe(0, libc_sig=False)
        probe.filesystem.cache.clear()
        probe.rearm_checkpoint_hooks()
        self.assertNotIn('relocated_libc_it_repair', probe.report)
        entry = probe.report['mondrv_output_seed']
        self.assertFalse(entry['armed'])
        self.assertIn('elf_unreadable', entry['reason'])
