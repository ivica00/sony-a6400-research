"""ARMv7 data-abort delivery and futex __ex_table checks (E0419)."""
import struct
import unittest
from pathlib import Path

from unicorn.arm_const import (UC_ARM_REG_CPSR, UC_ARM_REG_LR,
                               UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
                               UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R12,
                               UC_ARM_REG_SP, UC_ARM_REG_SPSR)

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
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_R3), 0x800005)

    def test_demand_page_helper_whitelist(self):
        machine = self.make_machine(symbols={'__clear_user_std': 0x6025DB00,
                                             'kmalloc': 0x60100000})
        self.assertTrue(machine._in_demand_page_helper(0x6025DB1C))
        self.assertFalse(machine._in_demand_page_helper(0x60100010))

    def test_prefetch_abort_ifar_ifsr_and_vector(self):
        machine = self.make_machine()
        pc, cpsr = 0x00123456, 0x00000070  # user mode + Thumb
        self.assertTrue(machine._deliver_prefetch_abort(pc, cpsr, 0x0402E790))
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_CPSR) & 0x1F, 0x17)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_SPSR), cpsr)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_LR), pc + 4)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_PC), 0xFFFF000C)
        # IFAR (c6,c0,2) and IFSR (c5,c0,1) read-back.
        helper_pa = 0x02003000
        machine.uc.mem_write(helper_pa, struct.pack('<3I', 0xEE162F50,
                                                    0xEE153F30, 0xEAFFFFFE))
        machine.uc.emu_start(helper_pa, 0, count=2)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_R2), 0x0402E790)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_R3), 0x5)
        self.assertEqual(machine.prefetch_aborts_delivered, 1)
        self.assertTrue(machine.prefetch_abort_trace[0]['user'])

    def test_user_prefetch_enters_pabt_usr_with_isolated_abt_frame(self):
        machine = self.make_machine(symbols={'__pabt_usr': 0x6010DE20})
        machine.mode_sp['svc'] = 0x7DC0FFB0
        machine.uc.reg_write(UC_ARM_REG_SP, 0x7DC0F000)  # user SP
        machine.uc.reg_write(UC_ARM_REG_R0, 0x1234)
        pc = 0x0402E790
        self.assertTrue(machine._deliver_prefetch_abort(pc, 0x00000070, pc))
        # Handler entered in SVC mode on the kernel SVC stack, not on SP_abt.
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_PC), 0x6010DE20)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_CPSR) & 0x1F, 0x13)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_SP), 0x7DC0FFB0)
        scratch_va = machine.VECTOR_SCRATCH_PA + machine.PAGE_OFFSET
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_R0), scratch_va)
        frame = struct.unpack('<3I', machine.uc.mem_read(machine.VECTOR_SCRATCH_PA, 12))
        self.assertEqual(frame, (0x1234, pc, 0x00000070))
        self.assertEqual(machine.user_sp, 0x7DC0F000)
        self.assertTrue(machine._restore_user_sp)

    def test_banked_usr_store_uses_saved_user_registers(self):
        machine = self.make_machine(symbols={'__pabt_usr': 0x6010DE20})
        machine.mode_sp['usr'] = 0x0E864F10
        machine.mode_lr['usr'] = 0x04001234
        sp = 0x0DC0FF20
        machine.uc.reg_write(UC_ARM_REG_SP, sp)
        machine.uc.reg_write(UC_ARM_REG_R0, sp + 0x3C)  # handler's add r0, sp, #0x3c
        pc = 0x6010DE3C                                 # __pabt_usr+0x1c (stmdb ^)
        machine._emulate_banked_store(pc)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_PC), pc + 4)
        frame = struct.unpack('<2I', machine.uc.mem_read(sp + 0x34, 8))
        self.assertEqual(frame, (0x0E864F10, 0x04001234))

    def test_flush_tlb_is_safe(self):
        machine = self.make_machine()
        machine._flush_tlb()  # must not raise even if the API is unavailable

    def test_unicorn_models_banked_sp(self):
        from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM
        cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        cpu.mem_map(0, 0x1000)
        cpu.reg_write(UC_ARM_REG_CPSR, 0xD3)
        cpu.reg_write(UC_ARM_REG_SP, 0x1111)
        cpu.reg_write(UC_ARM_REG_CPSR, 0x10)          # USR bank
        self.assertEqual(cpu.reg_read(UC_ARM_REG_SP), 0)
        cpu.reg_write(UC_ARM_REG_SP, 0x2222)
        cpu.reg_write(UC_ARM_REG_CPSR, 0xD3)
        self.assertEqual(cpu.reg_read(UC_ARM_REG_SP), 0x1111)
        cpu.reg_write(UC_ARM_REG_CPSR, 0x10)
        self.assertEqual(cpu.reg_read(UC_ARM_REG_SP), 0x2222)

    def test_banked_restore_reads_user_bank_from_frame(self):
        machine = self.make_machine()
        sp = 0x0DC10000
        machine.uc.reg_write(UC_ARM_REG_SP, sp)
        words = [0x1000 + i for i in range(13)] + [0x0E864F10, 0x04001234]
        machine.uc.mem_write(sp - 60, struct.pack('<15I', *words))
        pc = 0x6010DF58
        machine._emulate_banked_restore(pc)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_R0), 0x1000)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_R12), 0x100C)
        self.assertEqual(machine.mode_sp['usr'], 0x0E864F10)
        self.assertEqual(machine.mode_lr['usr'], 0x04001234)
        self.assertEqual(machine.user_sp, 0x0E864F10)
        self.assertTrue(machine._restore_user_sp)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_PC), pc + 4)
        self.assertEqual(machine.banked_restore_hits, 1)

    def test_prefetch_delivery_saves_ifar_for_mrc_hooks(self):
        machine = self.make_machine(symbols={'__pabt_usr': 0x6010DE20})
        machine.mode_sp['svc'] = 0x0DC0FFB0
        pc = 0x0402E790
        self.assertTrue(machine._deliver_prefetch_abort(pc, 0x00000070, pc))
        self.assertEqual(machine.last_ifar, pc)
        self.assertEqual(machine.last_ifsr, 5)
        self.assertEqual(machine.prefetch_aborts_delivered, 1)

    def test_data_delivery_saves_dfar_for_mrc_hooks(self):
        machine = self.make_machine()
        self.assertTrue(machine._deliver_data_abort(0x60123456, 0x00000013,
                                                    0x00048AC6, write=True))
        self.assertEqual(machine.last_dfar, 0x00048AC6)
        self.assertEqual(machine.last_dfsr & 0xFFF, 0x805)

    def test_user_copy_helpers_are_demand_page_whitelisted(self):
        machine = self.make_machine(symbols={
            'strncpy_from_user': 0x60A00000, 'copy_to_user': 0x60B00000,
            'kmalloc': 0x60C00000})
        self.assertTrue(machine._in_demand_page_helper(0x60A00010))
        self.assertTrue(machine._in_demand_page_helper(0x60B00020))
        self.assertFalse(machine._in_demand_page_helper(0x60C00030))

    def test_svc_data_abort_counts_delivery(self):
        machine = self.make_machine(symbols={'__dabt_svc': 0x6010D980})
        machine.uc.reg_write(UC_ARM_REG_SP, 0x0DC10000)
        self.assertTrue(machine._deliver_data_abort(0x60123456, 0x13,
                                                    0x04031AF0, write=False))
        self.assertEqual(machine.data_aborts_delivered, 1)
        self.assertTrue(machine.data_abort_trace[-1].get('svc'))

    def test_swi_dispatch_enters_vector_swi(self):
        machine = self.make_machine()
        machine.uc.reg_write(UC_ARM_REG_CPSR, 0x50)
        machine.uc.reg_write(UC_ARM_REG_PC, 0x04031AF0)
        machine._on_interrupt(machine.uc, 2)
        self.assertEqual(machine.svc_hits, 1)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_PC), 0xFFFF0008)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_CPSR) & 0x1F, 0x13)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_SPSR), 0x50)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_LR), 0x04031AF4)

    def test_svc_data_abort_enters_dabt_svc_with_scratch_frame(self):
        machine = self.make_machine(symbols={'__dabt_svc': 0x6010D980})
        sp = 0x0DC10000
        machine.uc.reg_write(UC_ARM_REG_SP, sp)
        machine.uc.reg_write(UC_ARM_REG_R0, 0x12345678)
        pc = 0x60123456
        self.assertTrue(machine._deliver_data_abort(pc, 0x00000013,
                                                    0x04031AF0, write=False))
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_PC), 0x6010D980)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_SP), sp)
        scratch = machine.VECTOR_SCRATCH_PA + 0x10
        values = struct.unpack('<3I', machine.uc.mem_read(scratch, 12))
        self.assertEqual(values, (0x12345678, pc, 0x13))
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_R0),
                         scratch + machine.PAGE_OFFSET)

    def test_svc_prefetch_abort_enters_pabt_svc_with_scratch_frame(self):
        machine = self.make_machine(symbols={'__pabt_svc': 0x6010DBA0})
        sp = 0x0DC10000
        machine.uc.reg_write(UC_ARM_REG_SP, sp)
        machine.uc.reg_write(UC_ARM_REG_R0, 0x0BADF00D)
        pc = 0x04031AF0
        self.assertTrue(machine._deliver_prefetch_abort(pc, 0x00000013, pc))
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_PC), 0x6010DBA0)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_SP), sp)
        scratch = machine.VECTOR_SCRATCH_PA + 0x10
        values = struct.unpack('<3I', machine.uc.mem_read(scratch, 12))
        self.assertEqual(values, (0x0BADF00D, pc, 0x13))
        self.assertEqual(machine.prefetch_aborts_delivered, 1)

    def test_swi_lr_uses_thumb_state(self):
        machine = self.make_machine()
        machine.uc.reg_write(UC_ARM_REG_CPSR, 0x70)  # request Thumb + USR
        machine.uc.reg_write(UC_ARM_REG_PC, 0x04031AF0)
        thumb = bool(machine.uc.reg_read(UC_ARM_REG_CPSR) & 0x20)
        machine._on_interrupt(machine.uc, 2)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_LR),
                         0x04031AF0 + (2 if thumb else 4))
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_CPSR) & 0x1F, 0x13)

    def test_intr_aborts_are_redispatched(self):
        machine = self.make_machine()
        calls = []
        machine._deliver_prefetch_abort = lambda pc, cpsr, addr: calls.append(
            ('pabt', pc, cpsr, addr)) or True
        machine._deliver_data_abort = lambda pc, cpsr, addr, write=False: calls.append(
            ('dabt', pc, cpsr, addr, write)) or True
        machine.uc.reg_write(UC_ARM_REG_PC, 0x04031AF0)
        machine.uc.reg_write(UC_ARM_REG_CPSR, 0x50)
        machine._on_interrupt(machine.uc, 3)
        machine.last_dfar = 0x04031000
        machine._on_interrupt(machine.uc, 4)
        self.assertEqual(calls[0][0], 'pabt')
        self.assertEqual(calls[0][1], 0x04031AF0)
        self.assertEqual(calls[1][0], 'dabt')
        self.assertEqual(calls[1][3], 0x04031000)

    def test_unmapped_read_hook_captures_address_and_type(self):
        machine = self.make_machine()
        self.assertFalse(machine._on_unmapped_read(
            machine.uc, 16, 0x04031AF4, 4, 0))
        self.assertEqual(machine._last_unmapped, 0x04031AF4)
        self.assertFalse(machine._last_unmapped_write)

    def test_unmapped_write_hook_captures_address_and_type(self):
        machine = self.make_machine()
        self.assertFalse(machine._on_unmapped_write(
            machine.uc, 17, 0x04048AC6, 4, 0))
        self.assertEqual(machine._last_unmapped, 0x04048AC6)
        self.assertTrue(machine._last_unmapped_write)

    def test_repeated_fault_circuit_breaker(self):
        machine = self.make_machine()
        key = (0x04031AF0, 0x04031AF0, 0x10)
        for _ in range(7):
            self.assertFalse(machine._note_fault(*key))
        self.assertTrue(machine._note_fault(*key))
        self.assertEqual(machine._fault_guard_count, 8)
        # a different fault resets the counter
        self.assertFalse(machine._note_fault(0x0402E790, 0x0402E790, 0x10))
        self.assertEqual(machine._fault_guard_count, 1)

    def test_prefetch_delivery_marks_fault_page_dirty(self):
        machine = self.make_machine(symbols={'__pabt_usr': 0x6010DE20})
        machine.mode_sp['svc'] = 0x0DC0FFB0
        self.assertTrue(machine._deliver_prefetch_abort(0x0402F666, 0x70, 0x0402F666))
        self.assertTrue(machine._pte_dirty)
        self.assertEqual(machine._last_fault_page, 0x0402F000)

    def test_flush_cputlb_helper_runs(self):
        machine = self.make_machine()
        before = machine.cputlb_flushes
        machine._flush_cputlb()
        self.assertEqual(machine.cputlb_flushes, before + 1)

    def test_decode_fault_address_thumb_load(self):
        machine = self.make_machine()
        pa = 0x00431AF0
        machine.uc.mem_write(pa, struct.pack('<H', 0x580B))  # ldr r3,[r1,r0]
        machine.uc.reg_write(UC_ARM_REG_CPSR, 0x40 | 0x10 | 0x20)  # Thumb+USR
        machine.uc.reg_write(UC_ARM_REG_R1, 0x0402E000)
        machine.uc.reg_write(UC_ARM_REG_R0, 0x1FF48)
        self.assertEqual(machine._decode_fault_address(pa, pa),
                         (0x0404DF48, False))

    def test_decode_fault_address_thumb_store(self):
        machine = self.make_machine()
        pa = 0x00432000
        machine.uc.mem_write(pa, struct.pack('<H', 0x604B))  # str r3,[r1,#4]
        machine.uc.reg_write(UC_ARM_REG_CPSR, 0x40 | 0x10 | 0x20)
        machine.uc.reg_write(UC_ARM_REG_R1, 0x0402E000)
        self.assertEqual(machine._decode_fault_address(pa, pa),
                         (0x0402E004, True))

    def test_guard_is_keyed_on_decoded_va(self):
        machine = self.make_machine()
        pc = 0x04031AF0
        for _ in range(7):
            self.assertFalse(machine._note_fault(pc, 0x0404DF48, 0x10))
        # a different decoded VA must not inherit the counter
        self.assertFalse(machine._note_fault(pc, 0x0404E85C, 0x10))
        self.assertEqual(machine._fault_guard_count, 1)
        self.assertTrue(machine._note_fault(pc, 0x0404DF48, 0x10) is False)

    def test_kernel_phys_translation(self):
        machine = self.make_machine()
        base = machine.PAGE_OFFSET
        self.assertEqual(machine._kernel_phys(base + 0x1000), 0x1000)
        self.assertEqual(machine._kernel_phys(base + 0x1DC0E000), 0x1DC0E000)
        self.assertEqual(machine._kernel_phys(0x04031000), 0x04031000)

    def test_tlb_flush_is_counted(self):
        machine = self.make_machine()
        before = machine._tlb_flushes
        machine._flush_tlb()
        self.assertGreaterEqual(machine._tlb_flushes, before)

    def test_do_page_fault_frame_capture(self):
        machine = self.make_machine()
        addr = 0x0DC20000
        machine.uc.reg_write(UC_ARM_REG_R0, 0x04031AF0)
        machine.uc.reg_write(UC_ARM_REG_R1, 0x805)
        machine.uc.reg_write(UC_ARM_REG_R2, addr)
        machine.uc.reg_write(UC_ARM_REG_SP, 0x0DC10000)
        words = [0x11110000 + i for i in range(18)]
        machine.uc.mem_write(addr, struct.pack('<18I', *words))
        machine._capture_fault_frame(0x60116D94)
        frame = machine.do_page_fault_frames[-1]
        self.assertEqual(frame['r0'], '0x04031af0')
        self.assertEqual(frame['r1'], '0x00000805')
        self.assertEqual(frame['r2'], '0x0dc20000')
        self.assertEqual(frame['sp'], '0x0dc10000')
        self.assertEqual(frame['pt_regs'][0], '0x11110000')
        self.assertEqual(frame['pt_regs'][17], '0x11110011')

    def test_on_interrupt_ignores_unknown_exceptions(self):
        machine = self.make_machine()
        machine.uc.reg_write(UC_ARM_REG_PC, 0x12345678)
        before_pc = machine.uc.reg_read(UC_ARM_REG_PC)
        machine._on_interrupt(machine.uc, 5)
        self.assertEqual(machine.svc_hits, 0)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_PC), before_pc)

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
