import struct
import unittest

from src.a6400.execution.kernel_task_identity import KernelTaskObservation, UnsupportedKernelBinding


class KernelTaskIdentityTests(unittest.TestCase):
    def observation(self, backlink=0x2000):
        header = struct.pack('<6I', 0, 1, 0x5f000000, 0x8000, 0, 0)
        task = bytearray(0x10c)
        struct.pack_into('<I', task, 8, backlink)
        struct.pack_into('<2I', task, 0x104, 97, 97)
        return KernelTaskObservation.read(lambda address, size: header if address == 0x2000 else task, 0x2000)

    def test_original_layout_requires_reciprocal_task_pointer(self):
        self.assertEqual(self.observation().pid, 97)
        with self.assertRaises(UnsupportedKernelBinding):
            self.observation(backlink=0x4000)

    def test_identity_and_address_space_mismatch_are_independent(self):
        failures = self.observation().mismatches(guest_pid=1003, guest_tgid=1000,
                                                user_ranges=[(0x7fe00000, 0x100000)])
        self.assertEqual([f['reason'] for f in failures],
                         ['pid_mismatch', 'tgid_mismatch', 'user_range_outside_task_limit'])

    def test_matching_identity_does_not_allow_overflow_or_kernel_limit(self):
        task = self.observation()
        self.assertIs(task.require_caller(guest_pid=97, guest_tgid=97,
                                         user_ranges=[(0x1000, 4096)]), task)
        with self.assertRaises(UnsupportedKernelBinding):
            task.require_caller(guest_pid=97, guest_tgid=97, user_ranges=[(0xfffffff0, 32)])
        kernel = KernelTaskObservation(0x2000, 0x8000, 97, 97, 0, 0)
        self.assertTrue(kernel.mismatches(guest_pid=97, guest_tgid=97))

    def test_unaligned_or_short_header_is_refused(self):
        for address in (0x2004, 0x2000):
            with self.assertRaises(UnsupportedKernelBinding):
                KernelTaskObservation.read(lambda *_: b'', address)
