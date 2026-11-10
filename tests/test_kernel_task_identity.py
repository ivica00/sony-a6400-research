import pickle
import unittest

from unicorn import arm_const as arm

from src.a6400.execution.guest_gles import GlesBinding, GuestGles
from src.a6400.execution.guest_threads import GuestThreads, REGISTER_LIST, EXPECTED_PTHREAD_CLONE_FLAGS
from src.a6400.execution.kernel_task_identity import (KernelTaskIdentityTable,
                                                      UnsupportedKernelBinding)


class KernelTaskIdentityTableTests(unittest.TestCase):
    def test_register_materialises_guest_derived_records(self):
        table = KernelTaskIdentityTable(address_limit=0x5f000000)
        record = table.register(1011, 1000)
        self.assertEqual(record.pid, 1011)
        self.assertEqual(record.tgid, 1000)
        self.assertEqual(record.address_limit, 0x5f000000)
        self.assertEqual(table.observation_for(1011), record)
        self.assertIsNone(table.observation_for(1099))

    def test_table_binding_accepts_registered_caller(self):
        table = KernelTaskIdentityTable()
        table.register(1011, 1000)
        binding = GlesBinding(table=table)
        self.assertEqual(binding.address_limit, 0x5f000000)
        self.assertTrue(binding.validate_caller(1011, 1000))

    def test_table_binding_rejects_unobserved_caller(self):
        binding = GlesBinding(table=KernelTaskIdentityTable())
        with self.assertRaises(UnsupportedKernelBinding) as raised:
            binding.validate_caller(1011, 1000)
        self.assertEqual(raised.exception.details['reason'], 'kernel_task_record_not_observed')

    def test_table_binding_rejects_wrong_tgid_or_out_of_limit_range(self):
        table = KernelTaskIdentityTable()
        table.register(1011, 1000)
        binding = GlesBinding(table=table)
        with self.assertRaises(UnsupportedKernelBinding) as raised:
            binding.validate_caller(1011, 999)
        self.assertIn('tgid_mismatch', str(raised.exception.details))
        with self.assertRaises(UnsupportedKernelBinding) as raised:
            binding.validate_caller(1011, 1000, [(0x5f000000, 0x1000)])
        self.assertIn('user_range_outside_task_limit', str(raised.exception.details))

    def test_guest_gles_open_uses_table_record_for_the_actual_caller(self):
        table = KernelTaskIdentityTable()
        table.register(1003, 1000)
        table.register(1011, 1000)
        gles = GuestGles(GlesBinding(table=table))
        owner = gles.open(2, 1011, 1000)
        self.assertEqual(owner['caller_pid'], 1011)
        with self.assertRaises(UnsupportedKernelBinding):
            gles.open(2, 1099, 1000)

    def test_clone_event_registers_child_tid(self):
        table = KernelTaskIdentityTable()
        threads = GuestThreads()
        threads.on_clone = table.register
        registers = {register: 0 for register in REGISTER_LIST}
        registers[arm.UC_ARM_REG_CPSR] = 0x10
        threads.handle_clone(EXPECTED_PTHREAD_CLONE_FLAGS, 0x70000000, 0, 0x71000000, 0,
                             lambda address, size: b'\x00' * size,
                             lambda address, data: None,
                             syscall_registers=registers)
        child_tid = 1001
        self.assertIsNotNone(table.observation_for(child_tid))
        self.assertEqual(table.observation_for(child_tid).pid, child_tid)

    def test_table_and_binding_pickle_roundtrip(self):
        table = KernelTaskIdentityTable()
        table.register(1011, 1000)
        binding = GlesBinding(table=table)
        restored = pickle.loads(pickle.dumps((table, binding)))
        self.assertIsNotNone(restored[0].observation_for(1011))
        self.assertTrue(restored[1].validate_caller(1011, 1000))


if __name__ == '__main__':
    unittest.main()
