"""Image identity, bounded syscall copies, and runtime-unknown read guards."""
import hashlib
import unittest

import unicorn
from unicorn import arm_const as arm
from project_paths import PROJECT_ROOT
from src.a6400.execution.guest_uname import GuestUname, extract_kernel_uts, FIELDS
from src.a6400.execution.guest_memory import accessible, cstring_preview


def record():
    values = ('Linux', '(none)', '3.0.27-test', '#1 test build', 'arm', '(none)')
    return b''.join(value.encode().ljust(65, b'\0') for value in values)


class KernelUTSTests(unittest.TestCase):
    def setUp(self):
        self.path = PROJECT_ROOT / 'artifacts/tests/uts-kernel.bin'
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def extract(self, data):
        self.path.write_bytes(data)
        return extract_kernel_uts(self.path, hashlib.sha256(data).hexdigest())

    def test_unique_record_and_offset(self):
        banner = b'Linux version 3.0.27-test (builder) #1 test build\n\0'
        profile = self.extract(banner + record())
        self.assertEqual(profile['file_offset'], len(banner))
        self.assertEqual(profile['fields']['release'], '3.0.27-test')
        self.assertIn('machine', profile['runtime_unverified_fields'])

    def test_hash_change_rejected(self):
        self.path.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            extract_kernel_uts(self.path, '0' * 64)

    def test_ambiguous_record_rejected(self):
        with self.assertRaises(ValueError):
            self.extract(b'Linux version 3.0.27-test banner\0' + record() * 2)

    def test_mismatched_release_rejected(self):
        with self.assertRaises(ValueError):
            self.extract(b'Linux version 9.0 banner\0' + record())

    def test_truncated_record_rejected(self):
        with self.assertRaises(ValueError):
            self.extract(b'Linux version 3.0.27-test banner\0' + record()[:-1])


class UnameCopyTests(unittest.TestCase):
    def setUp(self):
        self.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.mu.mem_map(0x1000, 4096)
        self.mu.mem_map(0x3000, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
        self.stops = []
        self.profile = {'source_sha256': 'fixture', 'file_offset': 0,
                        'raw_hex': record().hex(), 'fields': dict(zip(FIELDS,
                        ('Linux', '(none)', '3.0.27-test', '#1 test build', 'arm', '(none)')))}

        def stop(details):
            self.stops.append(details)
            self.mu.emu_stop()
        self.uname = GuestUname(self.mu, self.profile, stop)

    def instruction(self, opcode, address):
        self.mu.mem_write(0x1000, opcode.to_bytes(4, 'little'))
        self.mu.ctl_remove_cache(0x1000, 0x1004)
        self.mu.reg_write(arm.UC_ARM_REG_R1, address)
        self.mu.emu_start(0x1000, 0x1004)

    def test_copy_exact_size(self):
        self.mu.mem_write(0x3000 + 390, b'K')
        event = self.uname.request(0x3000)
        self.assertEqual(event['returned'], 0)
        self.assertEqual(bytes(self.mu.mem_read(0x3000, 390)), record())
        self.assertEqual(bytes(self.mu.mem_read(0x3000 + 390, 1)), b'K')

    def test_unmapped_buffer_returns_efault(self):
        self.assertEqual(self.uname.request(0)['returned'], 0xfffffff2)
        self.assertEqual(self.uname.bytes, {})

    def test_protected_buffer_returns_efault_without_writing(self):
        self.mu.mem_protect(0x3000, 4096, unicorn.UC_PROT_READ)
        self.assertEqual(self.uname.request(0x3000)['returned'], 0xfffffff2)
        self.assertEqual(bytes(self.mu.mem_read(0x3000, 390)), bytes(390))

    def test_cross_page_copy_preflight_is_atomic(self):
        self.mu.mem_write(0x3f00, b'X' * 256)
        self.assertEqual(self.uname.request(0x3f00)['returned'], 0xfffffff2)
        self.assertEqual(bytes(self.mu.mem_read(0x3f00, 256)), b'X' * 256)

    def test_release_is_readable(self):
        self.uname.request(0x3000)
        self.instruction(0xe5d10000, 0x3000 + 130)  # ldrb r0,[r1]
        self.assertEqual(self.mu.reg_read(arm.UC_ARM_REG_R0), ord('3'))
        self.assertEqual(self.stops, [])
        self.assertEqual(self.uname.read_fields, {'release': 1})

    def test_runtime_machine_read_stops(self):
        self.uname.request(0x3000)
        self.instruction(0xe5d10000, 0x3000 + 260)
        self.assertEqual(self.stops[0]['fields'], ['machine'])

    def test_guest_overwrite_clears_only_changed_byte(self):
        self.uname.request(0x3000)
        self.mu.reg_write(arm.UC_ARM_REG_R0, ord('X'))
        self.instruction(0xe5c10000, 0x3000 + 260)  # strb r0,[r1]
        self.instruction(0xe5d10000, 0x3000 + 260)
        self.assertEqual(self.stops, [])
        self.instruction(0xe5d10000, 0x3000 + 261)
        self.assertEqual(self.stops[0]['fields'], ['machine'])

    def test_guest_memory_bounds_and_permissions(self):
        self.assertFalse(accessible(self.mu, 0xfffffff0, 390, unicorn.UC_PROT_WRITE))
        self.assertFalse(accessible(self.mu, 0x3ff0, 32, unicorn.UC_PROT_WRITE))
        self.assertTrue(accessible(self.mu, 0, 0, unicorn.UC_PROT_WRITE))

    def test_path_preview_is_bounded(self):
        self.mu.mem_write(0x3000, b'/etc/ld.so.preload\0')
        self.assertEqual(cstring_preview(self.mu, 0x3000)['value'], '/etc/ld.so.preload')
        self.assertEqual(cstring_preview(self.mu, 0)['status'], 'unreadable')
        self.assertEqual(cstring_preview(self.mu, 0x3000, limit=4)['status'], 'limit')


if __name__ == '__main__':
    unittest.main()
