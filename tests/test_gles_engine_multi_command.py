"""GuestGles engine model: every new GPES submission completes, once."""
import struct
import unittest

from src.a6400.execution.guest_gles import GuestGles, GlesBinding
from src.a6400.execution.kernel_task_identity import KernelTaskObservation

BAR = 0x10000


class EngineMultiCommandTests(unittest.TestCase):
    def setUp(self):
        header = struct.pack('<6I', 0, 1, 0x5f000000, 0x8000, 0, 0)
        task = bytearray(0x10c)
        struct.pack_into('<I', task, 8, 0x2000)
        struct.pack_into('<2I', task, 0x104, 1003, 1000)
        obs = KernelTaskObservation.read(lambda a, s: header if a == 0x2000 else task, 0x2000)
        self.gles = GuestGles(GlesBinding(obs))
        self.gles.engine_model = True
        self.gles.bar_virtual = BAR
        self.gles.bar_length = 0x4000
        self.mem = {}

    def rd(self, address, size):
        return self.mem.get(address, b'\x00' * size)[:size]

    def wr(self, address, data):
        self.mem[address] = bytes(data)

    def poll(self):
        return self.gles._poll_engine_command(self.rd, self.wr)

    def submit_header(self):
        self.mem[BAR + 0xE8] = b'\x01\x00\x05\x00'

    def test_two_header_submissions_both_complete(self):
        for n in (1, 2):
            self.submit_header()
            self.assertEqual(self.poll(), 0x40000000)
            self.assertEqual(self.gles.engine_completions, n)
            self.assertEqual(self.gles.dev_a8, 0x45000000)
            self.gles.dev_a8 = 0  # guest ack
            self.assertIsNone(self.poll())  # header consumed, no re-fire
        self.assertTrue(self.gles.engine_command_seen)

    def test_stale_descriptor_does_not_refire(self):
        self.mem[BAR + 0xF4] = b'\x21\x00\x00\x00'
        self.mem[BAR + 0x16C] = b'\x00\x10\x00\x00'
        self.assertEqual(self.poll(), 0x40000000)
        for _ in range(3):
            self.assertIsNone(self.poll())
        self.assertEqual(self.gles.engine_completions, 1)
        self.mem[BAR + 0x16C] = b'\x00\x20\x00\x00'  # new completion word
        self.assertEqual(self.poll(), 0x40000000)
        self.assertEqual(self.gles.engine_completions, 2)

    def test_engine_state_counter_resets_per_submission(self):
        self.gles.engine_state_events = 16
        self.submit_header()
        self.poll()
        self.assertEqual(self.gles.engine_state_events, 0)
        self.gles.engine_state_events = 16
        self.gles.complete_engine_command('test')
        self.assertEqual(self.gles.engine_state_events, 0)

    def test_bar_write_completion_not_double_counted(self):
        self.assertIsNotNone(self.gles.complete_engine_command('bar-write'))
        self.assertIsNone(self.gles.complete_engine_command('bar-write'))  # 0x170 after 0x16C
        self.submit_header()
        self.poll()  # same submission seen by the poll: consumed, not recounted
        self.assertEqual(self.gles.engine_completions, 1)
        self.submit_header()  # genuinely new submission
        self.poll()
        self.assertEqual(self.gles.engine_completions, 2)
        self.assertIsNotNone(self.gles.complete_engine_command('bar-write'))
        self.assertEqual(self.gles.engine_completions, 3)

    def test_old_checkpoint_loads(self):
        state = dict(self.gles.__dict__)
        state.pop('engine_last_key', None)
        state.pop('engine_bar_completed', None)
        fresh = GuestGles.__new__(GuestGles)
        fresh.__setstate__(state)
        self.assertIsNone(fresh.engine_last_key)
        self.assertFalse(fresh.engine_bar_completed)


if __name__ == '__main__':
    unittest.main()
