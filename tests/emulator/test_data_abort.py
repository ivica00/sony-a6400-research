"""ARMv7 data-abort delivery and futex __ex_table checks (E0419)."""
import struct
import unittest
from pathlib import Path

from unicorn.arm_const import (UC_ARM_REG_CPSR, UC_ARM_REG_LR,
                               UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
                               UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SPSR)

from src.a6400.execution.arm_atags import build_atags
from src.a6400.execution.unicorn_machine import UnicornMachine

ROOT = Path(__file__).resolve().parents[2]
KERNEL = ROOT / 'artifacts/analysis/e0416-qemu-bringup/nflasha1-vmlinux-decompressed.bin'


def tiny_kernel():
    image = bytearray(0x100)
    struct.pack_into('<2I', image, 0, 0xE321F0D3, 0xEAFFFFFE)  # msr; b .
    return bytes(image)


class DataAbortDeliveryTests(unittest.TestCase):
    def make_machine(self, **kwargs):
        machine = UnicornMachine(tiny_kernel(), b'\x00' * 64,
                                 build_atags('console=ttyAM0', [(0, 0x40000000)]),
                                 machine_id=0x0DA9, instruction_limit=100,
                                 exclusive_patch=False, **kwargs)
        machine.PAGE_OFFSET = 0  # synthetic MMU-off machine: helper at PA
        return machine

    def test_cp15_dfar_dfsr_write_and_read_back(self):
        machine = self.make_machine()
        self.assertTrue(machine._set_cp15_fault(0x00123458, 0x800005))
        # Execute mrc p15,0,r2,c6,c0,0 / mrc p15,0,r3,c5,c0,0 and read the values.
        helper_pa = 0x02002000
        helper_va = helper_pa + machine.PAGE_OFFSET
        machine.uc.mem_write(helper_pa, struct.pack('<3I', 0xEE162F10,
                                                    0xEE153F10, 0xEAFFFFFE))
        machine.uc.emu_start(helper_pa, 0, count=2)  # no MMU in this test machine
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_R2), 0x00123458)

    def test_abort_delivery_sets_armv7_abort_state(self):
        machine = self.make_machine()
        pc, cpsr = 0x60123456, 0x13
        self.assertTrue(machine._deliver_data_abort(pc, cpsr, 0, write=False))
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_CPSR) & 0x1F, 0x17)
        self.assertTrue(machine.uc.reg_read(UC_ARM_REG_CPSR) & 0x80)  # I masked
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_SPSR), 0x13)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_LR), pc + 8)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_PC), 0xFFFF0010)
        self.assertEqual(machine.data_aborts_delivered, 1)
        self.assertEqual(machine.data_abort_trace[0]['address'], '0x00000000')

    def test_write_fault_sets_wnr_and_double_fault_guard(self):
        machine = self.make_machine()
        self.assertTrue(machine._deliver_data_abort(0x60100000, 0x13, 0, True))
        self.assertEqual(machine.data_abort_trace[0]['fsr'], '0x00000805')
        # A repeatedly faulting PC is bounded instead of looping forever.
        for _ in range(12):
            machine._deliver_data_abort(0x60100000, 0x13, 0, True)
        self.assertFalse(machine._deliver_data_abort(0x60100000, 0x13, 0, True))

    def test_delivery_can_be_disabled(self):
        machine = self.make_machine(data_abort_delivery=False)
        self.assertFalse(machine._deliver_data_abort(0x60100000, 0x13, 0, False))
        self.assertEqual(machine.data_aborts_delivered, 0)


@unittest.skipUnless(KERNEL.is_file(), 'E0416 decompressed updater kernel not present')
class FutexExceptionTableTests(unittest.TestCase):
    def test_ex_table_entry_for_futex_cmpxchg_ldrex(self):
        image = KERNEL.read_bytes()
        base = 0x60108000
        fault_pc = 0x6015BDCC  # ldrex r2,[r5] in cmpxchg_futex_value_locked+0x50
        pattern = struct.pack('<I', fault_pc)
        start = 0
        entries = []
        while True:
            index = image.find(pattern, start)
            if index < 0:
                break
            fixup = struct.unpack_from('<I', image, index + 4)[0]
            if 0x60108000 <= fixup < 0x60500000:
                entries.append((base + index, fault_pc, fixup))
            start = index + 1
        self.assertEqual(len(entries), 1)
        entry_offset, insn, fixup = entries[0]
        self.assertEqual(insn, fault_pc)
        self.assertEqual(fixup, 0x60364BD4)  # mov r7,r3; b 0x6015bde4 (-EFAULT path)
        self.assertEqual(entry_offset, 0x60454438)


class ExceptionTableFixupTests(unittest.TestCase):
    def test_fixup_jump_for_faulting_pc(self):
        machine = UnicornMachine(tiny_kernel(), b'\x00' * 64,
                                 build_atags('console=ttyAM0', [(0, 0x40000000)]),
                                 machine_id=0x0DA9, instruction_limit=100,
                                 exclusive_patch=False, data_abort_delivery=False)
        machine.PAGE_OFFSET = 0
        machine.ex_table = {0x6015BDCC: 0x60364BD4}
        machine.uc.reg_write(UC_ARM_REG_PC, 0x6015BDCC)
        fixup = machine._try_ex_table_fixup(0x6015BDCC)
        self.assertEqual(fixup, 0x60364BD4)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_PC), 0x60364BD4)
        self.assertEqual(machine.ex_table_fixups, 1)
        self.assertIsNone(machine._try_ex_table_fixup(0x60100000))

    @unittest.skipUnless(KERNEL.is_file(), 'E0416 decompressed updater kernel not present')
    def test_real_kernel_ex_table_contains_futex_ldrex(self):
        machine = UnicornMachine(KERNEL.read_bytes(), b'\x00' * 64,
                                 build_atags('console=ttyAM0', [(0, 0x40000000)]),
                                 machine_id=0x0DA9, instruction_limit=1,
                                 exclusive_patch=False, data_abort_delivery=False)
        self.assertGreater(machine.ex_table_entries, 1000)
        self.assertEqual(machine.ex_table.get(0x6015BDCC), 0x60364BD4)


if __name__ == '__main__':
    unittest.main()
