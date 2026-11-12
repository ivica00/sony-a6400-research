"""ARMv7 exclusive-instruction evidence and emulation checks (E0418)."""
import struct
import unittest

from unicorn import UC_ARCH_ARM, UC_MODE_ARM, Uc
from unicorn.arm_const import (UC_ARM_REG_CPSR, UC_ARM_REG_PC,
                               UC_ARM_REG_R2, UC_ARM_REG_R3,
                               UC_ARM_REG_R5, UC_ARM_REG_R7, UC_ARM_REG_R8)

from src.a6400.execution.arm_atags import build_atags
from src.a6400.execution.unicorn_machine import GIC_ICCICR, UnicornMachine


def tiny_kernel():
    image = bytearray(0x100)
    struct.pack_into('<2I', image, 0, 0xE321F0D3, 0xEAFFFFFE)  # msr; b .
    return bytes(image)


class UnicornExclusiveSupportTests(unittest.TestCase):
    """Unicorn 2.1.4 itself supports LDREX/STREX on mapped normal memory."""

    def test_ldrex_strex_word_succeeds_on_mapped_ram(self):
        uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        uc.mem_map(0, 0x4000, 7)
        uc.mem_write(0x2000, struct.pack('<I', 0x11223344))
        # mov r0,#0x2000; mov r1,#7; ldrex r2,[r0]; strex r3,r1,[r0]; b .
        words = [0xE3A00A02, 0xE3A01007, 0xE1902F9F, 0xE1803F91, 0xEAFFFFFE]
        uc.mem_write(0x1000, struct.pack('<5I', *words))
        uc.emu_start(0x1000, 0, count=10)
        self.assertEqual(uc.reg_read(UC_ARM_REG_R2), 0x11223344)
        self.assertEqual(uc.reg_read(UC_ARM_REG_R3), 0)  # STREX success
        self.assertEqual(struct.unpack('<I', uc.mem_read(0x2000, 4))[0], 7)


class ExclusiveEmulationTests(unittest.TestCase):
    def make_machine(self):
        return UnicornMachine(tiny_kernel(), b'\x00' * 64,
                              build_atags('console=ttyAM0', [(0, 0x40000000)]),
                              machine_id=0x0DA9, instruction_limit=100,
                              exclusive_patch=False)

    def put(self, machine, va, words):
        pa = va - machine.PAGE_OFFSET if va >= machine.PAGE_OFFSET else va
        machine.uc.mem_write(pa, struct.pack(f'<{len(words)}I', *words))

    def test_ldrex_strex_word_and_byte_and_halfword(self):
        machine = self.make_machine()
        data_va = 0x60200000
        data_pa = 0x00200000
        machine.uc.mem_write(data_pa, bytes([0x5A, 0xAA, 0xBB, 0xCC]))
        machine.uc.reg_write(UC_ARM_REG_R5, data_va)
        machine.uc.reg_write(UC_ARM_REG_R8, 0xAABBCC77)
        code_va = 0x60100000

        # word LDREX r2,[r5]; STREX r7,r8,[r5]
        self.put(machine, code_va, [0xE1952F9F, 0xE1857F98])
        self.assertTrue(machine._emulate_exclusive(code_va, 0x13))
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_R2), 0xCCBBAA5A)
        self.assertTrue(machine._emulate_exclusive(code_va + 4, 0x13))
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_R7), 0)
        self.assertEqual(bytes(machine.uc.mem_read(data_pa, 4)),
                         bytes([0x77, 0xCC, 0xBB, 0xAA]))

        # byte LDREXB r2,[r5]; STREXB r7,r8,[r5]
        self.put(machine, code_va + 8, [0xE1D52F9F, 0xE1C57F98])
        machine.uc.reg_write(UC_ARM_REG_R8, 0x99)
        self.assertTrue(machine._emulate_exclusive(code_va + 8, 0x13))
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_R2), 0x77)
        self.assertTrue(machine._emulate_exclusive(code_va + 12, 0x13))
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_R7), 0)
        self.assertEqual(machine.uc.mem_read(data_pa, 1)[0], 0x99)

        # halfword LDREXH r2,[r5]; STREXH r7,r8,[r5]
        self.put(machine, code_va + 16, [0xE1F52F9F, 0xE1E57F98])
        machine.uc.reg_write(UC_ARM_REG_R8, 0x1234)
        self.assertTrue(machine._emulate_exclusive(code_va + 16, 0x13))
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_R2) & 0xFFFF, 0xCC99)
        self.assertTrue(machine._emulate_exclusive(code_va + 20, 0x13))
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_R7), 0)
        self.assertEqual(struct.unpack('<H', machine.uc.mem_read(data_pa, 2))[0],
                         0x1234)

    def test_barriers_and_clrex_are_skipped(self):
        machine = self.make_machine()
        code_va = 0x60100000
        self.put(machine, code_va, [0xF57FF05F])  # dmb sy
        machine.uc.reg_write(UC_ARM_REG_PC, code_va)
        self.assertTrue(machine._emulate_exclusive(code_va, 0x13))
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_PC), code_va + 4)
        machine._exclusive_monitor = (0x200000, 1)
        self.put(machine, code_va + 4, [0xF57FF01F])  # clrex
        machine.uc.reg_write(UC_ARM_REG_PC, code_va + 4)
        self.assertTrue(machine._emulate_exclusive(code_va + 4, 0x13))
        self.assertIsNone(machine._exclusive_monitor)

    def test_irq_entry_clears_the_exclusive_monitor(self):
        machine = self.make_machine()
        machine._gic_regs[('cpu', GIC_ICCICR)] = 1
        machine._gic_regs[('dist', 0x000)] = 1
        machine.uc.reg_write(UC_ARM_REG_CPSR, 0x13)
        machine._exclusive_monitor = (0x200000, 1)
        machine._timer_irq_pending = 1
        self.assertTrue(machine._try_inject_irq())
        self.assertIsNone(machine._exclusive_monitor)


if __name__ == '__main__':
    unittest.main()
