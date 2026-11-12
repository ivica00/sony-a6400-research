"""Timer/GIC IRQ model checks for the CXD90045 Unicorn machine (E0417)."""
import struct
import unittest

from src.a6400.execution.arm_atags import build_atags
from src.a6400.execution.unicorn_machine import (
    GIC_CPU,
    GIC_DIST,
    GIC_ICCICR,
    TIMER_BASE,
    TIMER_TICKS_PER_JIFFY,
    UnicornMachine,
)

MACHINE_ID = 0x0DA9
STORAGE = 0x00100000


def gic_program():
    """Reads GIC IAR, GICD_TYPER and the free-running timer counter into RAM."""
    image = bytearray(0x100)
    words = [
        0xE321F0D3,  # 0x00 msr cpsr_c,#0xd3 (kernel head word)
        0xE59F0054,  # 0x04 ldr r0,[pc,#0x54] -> 0x60 GICC
        0xE3A01001,  # 0x08 mov r1,#1
        0xE5801000,  # 0x0c str r1,[r0]          ICCICR = 1
        0xE59F004C,  # 0x10 ldr r0,[pc,#0x4c] -> 0x64 GICD
        0xE5801000,  # 0x14 str r1,[r0]          GICD_CTLR = 1
        0xE59F0048,  # 0x18 ldr r0,[pc,#0x48] -> 0x68 GICC
        0xE590200C,  # 0x1c ldr r2,[r0,#0x0c]    IAR read
        0xE59F3044,  # 0x20 ldr r3,[pc,#0x44] -> 0x6c STORAGE
        0xE5832000,  # 0x24 str r2,[r3]
        0xE59F0040,  # 0x28 ldr r0,[pc,#0x40] -> 0x70 GICD
        0xE5902004,  # 0x2c ldr r2,[r0,#4]       GICD_TYPER read
        0xE59F303C,  # 0x30 ldr r3,[pc,#0x3c] -> 0x74 STORAGE+4
        0xE5832000,  # 0x34 str r2,[r3]
        0xE59F0038,  # 0x38 ldr r0,[pc,#0x38] -> 0x78 TIMER_BASE
        0xE590210C,  # 0x3c ldr r2,[r0,#0x10c]  counter read
        0xE59F3034,  # 0x40 ldr r3,[pc,#0x34] -> 0x7c STORAGE+8
        0xE5832000,  # 0x44 str r2,[r3]
        0xEAFFFFFE,  # 0x48 b .
    ]
    for index, word in enumerate(words):
        struct.pack_into('<I', image, index * 4, word)
    struct.pack_into('<8I', image, 0x60, GIC_CPU, GIC_DIST, GIC_CPU, STORAGE,
                     GIC_DIST, STORAGE + 4, TIMER_BASE, STORAGE + 8)
    return bytes(image)


class TimerGicModelTests(unittest.TestCase):
    def make_machine(self, program=None, **kwargs):
        options = dict(machine_id=MACHINE_ID, instruction_limit=40000,
                       sample_interval=1000, timer_irq_model=True,
                       timer_ticks_per_instruction=1,
                       timer_ticks_per_jiffy=1000)
        options.update(kwargs)
        return UnicornMachine(program or gic_program(), b'\x00' * 64,
                              build_atags('console=ttyAM0', [(0, 0x40000000)]),
                              **options)

    def test_gic_reads_are_served_by_the_model(self):
        machine = self.make_machine()
        report = machine.run()
        iar = struct.unpack('<I', machine.uc.mem_read(STORAGE, 4))[0]
        typer = struct.unpack('<I', machine.uc.mem_read(STORAGE + 4, 4))[0]
        counter = struct.unpack('<I', machine.uc.mem_read(STORAGE + 8, 4))[0]
        self.assertEqual(iar, 1023)  # spurious: no pending interrupt yet
        self.assertEqual(typer, 0x1F)  # 1024 interrupt lines reported
        self.assertEqual(counter, 0)  # first slice has not advanced time yet
        self.assertEqual(report['timer_model']['gic_iar_reads'], 1)

    def test_timer_counter_advances_with_executed_instructions(self):
        machine = self.make_machine(instruction_limit=30000, sample_interval=5000)
        report = machine.run()
        self.assertGreaterEqual(report['timer_model']['timer_counter'], 30000)
        self.assertGreater(report['timer_model']['timer_counter_reads'], 0)

    def test_advance_timer_marks_one_pending_jiffy(self):
        machine = self.make_machine()
        machine.timer_ticks_per_jiffy = 100
        machine.timer_irq_start_instructions = 0
        machine._timer_counter = 0
        machine._next_jiffy_tick = 100
        machine._advance_timer(100)
        self.assertEqual(machine._timer_irq_pending, 1)
        self.assertEqual(machine._next_jiffy_tick, 200)
        machine._advance_timer(100)
        self.assertEqual(machine._timer_irq_pending, 1)  # not queued twice
        self.assertEqual(machine._next_jiffy_tick, 300)

    def test_irq_injection_enters_arm_irq_vector_with_banked_state(self):
        from unicorn.arm_const import (UC_ARM_REG_CPSR, UC_ARM_REG_LR,
                                       UC_ARM_REG_PC, UC_ARM_REG_SPSR)
        machine = self.make_machine()
        machine._gic_regs[('cpu', GIC_ICCICR)] = 1
        machine._gic_regs[('dist', 0x000)] = 1
        machine.uc.reg_write(UC_ARM_REG_CPSR, 0x13)
        machine.uc.reg_write(UC_ARM_REG_PC, 0x60123456)
        machine._timer_irq_pending = 1
        self.assertTrue(machine._try_inject_irq())
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_CPSR) & 0x1F, 0x12)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_SPSR), 0x13)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_LR), 0x6012345A)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_PC), 0xFFFF0018)
        self.assertEqual(machine._timer_irq_pending, 0)

    def test_irq_is_not_injected_when_masked_or_gic_disabled(self):
        from unicorn.arm_const import UC_ARM_REG_CPSR
        machine = self.make_machine()
        machine._gic_regs[('cpu', GIC_ICCICR)] = 1
        machine._gic_regs[('dist', 0x000)] = 1
        machine._timer_irq_pending = 1
        machine.uc.reg_write(UC_ARM_REG_CPSR, 0x93)  # IRQ masked
        self.assertFalse(machine._try_inject_irq())
        machine.uc.reg_write(UC_ARM_REG_CPSR, 0x13)
        machine._gic_regs[('cpu', GIC_ICCICR)] = 0
        self.assertFalse(machine._try_inject_irq())


if __name__ == '__main__':
    unittest.main()
