"""GuardedGuestBytes range hooks: tracked bytes are still guarded; untracked accesses cost no callback."""
import unittest

import unicorn
from unicorn import arm_const as arm

from src.a6400.execution.guarded_bytes import GuardedGuestBytes

LDR_R1_R0 = bytes.fromhex('001090e5')  # ldr r1, [r0]
STR_R1_R0 = bytes.fromhex('001080e5')  # str r1, [r0]


class RangeHookTests(unittest.TestCase):
    def setUp(self):
        self.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.mu.mem_map(0x10000, 0x10000)
        self.stops = []
        self.guard = GuardedGuestBytes(self.mu, {'secret'}, self.stops.append, 'test')

    def run_insn(self, code, r0):
        self.mu.mem_write(0x10000, code)
        self.mu.reg_write(arm.UC_ARM_REG_R0, r0)
        self.mu.emu_start(0x10000, 0x10004)

    def test_tracked_read_stops_and_overlapping_read_from_below_is_seen(self):
        self.guard.track(0x18002, ['secret'])
        self.run_insn(LDR_R1_R0, 0x18000)  # 4-byte read starting below the tracked byte
        self.assertEqual(self.stops[0]['fields'], ['secret'])

    def test_untracked_access_is_not_reported_and_write_forgets(self):
        self.guard.track(0x18000, ['secret'])
        self.run_insn(LDR_R1_R0, 0x19000)
        self.assertEqual(self.stops, [])
        self.run_insn(STR_R1_R0, 0x18000)
        self.assertEqual(self.guard.bytes, {})
        self.run_insn(LDR_R1_R0, 0x18000)
        self.assertEqual(self.stops, [])

    def test_assigning_bytes_rearms_hooks(self):  # checkpoint restore path
        self.guard.bytes = {0x1a000: 'secret'}
        self.run_insn(LDR_R1_R0, 0x1a000)
        self.assertEqual(len(self.stops), 1)


if __name__ == '__main__':
    unittest.main()
