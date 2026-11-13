import struct
import unittest
from unicorn.arm_const import (UC_ARM_REG_CPSR, UC_ARM_REG_LR, UC_ARM_REG_PC,
                              UC_ARM_REG_R4, UC_ARM_REG_SP)

from src.a6400.execution.machine_contract import build_atags
from src.a6400.execution.unicorn_machine import UnicornMachine
from tests.emulator.test_data_abort import tiny_kernel


def make_machine(**kwargs):
    machine = UnicornMachine(tiny_kernel(), b'\x00' * 64,
                             build_atags('console=ttyAM0', [(0, 0x40000000)]),
                             machine_id=0x0DA9, instruction_limit=100,
                             exclusive_patch=False, virtual_tlb_enabled=True,
                             **kwargs)
    return machine


class VirtualTlbTest(unittest.TestCase):
    def test_virtual_tlb_is_enabled(self):
        machine = make_machine()
        self.assertTrue(machine.virtual_tlb, machine.virtual_tlb_error)

    def test_pre_mmu_identity(self):
        machine = make_machine()
        machine._mmu_enabled = False
        self.assertEqual(machine._translate_virtual(0x00108A4C), 0x00108A4C)

    def test_kernel_lowmem_linear(self):
        machine = make_machine()
        machine._mmu_enabled = True
        self.assertEqual(machine._translate_virtual(0x60108A4C), 0x00108A4C)

    def test_high_vectors_identity(self):
        machine = make_machine()
        machine._mmu_enabled = True
        self.assertEqual(machine._translate_virtual(0xFFFF0018), 0xFFFF0018)

    def test_user_va_page_table_walk(self):
        machine = make_machine()
        machine._mmu_enabled = True
        ttbr0 = 0x10800000
        l2page = 0x10901000
        machine.uc.mem_write(ttbr0 + 0x040 * 4, struct.pack('<I', l2page | 1))
        machine.uc.mem_write(l2page + 0x31 * 4,
                             struct.pack('<I', 0x00431000 | 0x7F))
        machine._cached_ttbr0 = ttbr0
        self.assertEqual(machine._translate_virtual(0x04031000), 0x00431000)

    def test_user_va_unmapped_returns_none(self):
        machine = make_machine()
        machine._mmu_enabled = True
        machine._cached_ttbr0 = 0x10800000  # empty L1 -> no entry
        self.assertIsNone(machine._translate_virtual(0x04031000))

    def test_user_va_without_ttbr0_returns_none(self):
        machine = make_machine()
        machine._mmu_enabled = True
        machine._cached_ttbr0 = None
        self.assertIsNone(machine._translate_virtual(0x04031000))


    def test_ttbr1_section_translation(self):
        machine = make_machine()
        machine._mmu_enabled = True
        base = 0x10800000
        machine._cached_ttbr1 = base
        vaddr = 0xDF700000
        idx = (vaddr >> 20) & 0xFFF
        machine.uc.mem_write(base + idx * 4, struct.pack('<I', 0x00100000 | 2))
        self.assertEqual(machine._translate_virtual(vaddr), 0x00100000)

    def test_ttbr1_l2_small_page_translation(self):
        machine = make_machine()
        machine._mmu_enabled = True
        base = 0x10800000
        l2page = 0x10900000
        machine._cached_ttbr1 = base
        vaddr = 0xDF7FE123
        idx = (vaddr >> 20) & 0xFFF
        machine.uc.mem_write(base + idx * 4, struct.pack('<I', l2page | 1))
        l2idx = (vaddr >> 12) & 0xFF
        machine.uc.mem_write(l2page + l2idx * 4,
                             struct.pack('<I', 0x00401000 | 2))
        self.assertEqual(machine._translate_virtual(vaddr), 0x00401123)

    def test_ttbr1_unmapped_vmalloc_returns_none(self):
        machine = make_machine()
        machine._mmu_enabled = True
        machine._cached_ttbr1 = 0x10800000
        self.assertIsNone(machine._translate_virtual(0xDF7FE000))

    def test_mmio_window_identity(self):
        machine = make_machine()
        machine._mmu_enabled = True
        self.assertEqual(machine._translate_virtual(0xF2000000), 0xF2000000)


    def test_deferred_virtual_tlb_waits_for_userspace(self):
        machine = make_machine(virtual_tlb_on_userspace=True)
        self.assertFalse(machine.virtual_tlb)
        machine._install_virtual_tlb()
        self.assertTrue(machine.virtual_tlb)

    def test_deferred_flag_reported(self):
        machine = make_machine(virtual_tlb_on_userspace=True)
        machine._install_virtual_tlb()
        self.assertTrue(machine.virtual_tlb_on_userspace)
        self.assertTrue(machine._translate_virtual(0x60100000) is not None)


    def test_resolve_user_pgd_handles_empty_chain(self):
        machine = make_machine()
        machine.uc.reg_write(__import__('unicorn').arm_const.UC_ARM_REG_SP, 0)
        self.assertIsNone(machine._resolve_user_pgd())

    def test_refresh_user_ttbr0_keeps_kernel_pgd_without_fallback(self):
        machine = make_machine()
        machine._cached_ttbr0 = 0x00104000
        machine._refresh_user_ttbr0()
        # tiny machine TTBR0 reads 0 and no current->mm fallback exists
        self.assertEqual(machine._cached_ttbr0, 0)


    def test_switch_mm_hook_uses_verified_image_address(self):
        machine = make_machine()
        machine._install_switch_mm_hook()
        self.assertTrue(machine.switch_mm_hooked)
        self.assertEqual(machine.switch_mm_address, 0x6011A26C)


    def test_ttbr0_opcode_scanner(self):
        import struct
        code = struct.pack('<2I', 0xEE023F10, 0xEAFFFFFE)
        sites = UnicornMachine.scan_ttbr0_write_sites(code, 0x60100000)
        self.assertEqual(sites, [(0x60100000, 3)])

    def test_ttbr0_opcode_scanner_ignores_other_mcr(self):
        import struct
        code = struct.pack('<2I', 0xEE010F10, 0xEE021F30)
        self.assertEqual(UnicornMachine.scan_ttbr0_write_sites(code, 0), [])


    def test_ttbr0_scanner_finds_thumb2_encoding(self):
        import struct
        code = struct.pack('<2H', 0xEE02, 0x3F10)
        sites = UnicornMachine.scan_ttbr0_write_sites(code, 0x60100000)
        self.assertEqual(sites, [(0x60100000, 3)])

    def test_ttbr0_scanner_thumb2_ignores_other_second_halfword(self):
        import struct
        code = struct.pack('<2H', 0xEE02, 0x1F30)
        self.assertEqual(UnicornMachine.scan_ttbr0_write_sites(code, 0), [])


    def test_activation_pgd_default_and_read32_phys(self):
        machine = make_machine()
        self.assertIsNone(machine._activation_pgd)
        # tiny machine: PA 0 is mapped and zero-filled
        self.assertEqual(machine._read32_phys(0), 0)


    def test_pt_regs_base_finder_accepts_user_frame(self):
        import struct
        machine = make_machine()
        ti = 0x0100E000
        base = ti + 0x1FB0
        # pc slot (+0x3C) = user address, cpsr slot (+0x40) = USR mode
        machine.uc.mem_write(base + 0x3C, struct.pack('<I', 0x0402E790))
        machine.uc.mem_write(base + 0x40, struct.pack('<I', 0x00000070))
        self.assertEqual(machine._find_pt_regs_base(ti + 0x1FB0), base)

    def test_pt_regs_base_finder_rejects_zero_pc(self):
        import struct
        machine = make_machine()
        ti = 0x0100E000
        base = ti + 0x1FB0
        machine.uc.mem_write(base + 0x3C, struct.pack('<I', 0))
        machine.uc.mem_write(base + 0x40, struct.pack('<I', 0x00000070))
        self.assertIsNone(machine._find_pt_regs_base(ti + 0x1FB0))


    def test_thumb_pc_keeps_thumb_bit_for_even_target(self):
        self.assertEqual(UnicornMachine.thumb_pc(0x0402E790, 0x70), 0x0402E791)

    def test_thumb_pc_clears_lsb_in_arm_mode(self):
        self.assertEqual(UnicornMachine.thumb_pc(0x0402E791, 0x10), 0x0402E790)


    def test_pending_user_return_defaults_and_restore_counter(self):
        machine = make_machine()
        self.assertIsNone(machine.pending_user_spsr)
        self.assertIsNone(machine.pending_user_lr)
        self.assertEqual(machine.user_restores, 0)
        # thumb_pc is used by the restore for the final PC
        self.assertEqual(machine.thumb_pc(0x0402E790, 0x30), 0x0402E791)


    def test_set_pc_and_cpsr_thumb_lsb(self):
        machine = make_machine()
        machine._set_pc_and_cpsr(0x0402E790, 0x00000030)
        self.assertTrue(machine.uc.reg_read(UC_ARM_REG_CPSR) & 0x20)
        # Unicorn keeps PC even in the register while T is carried in CPSR
        self.assertIn(machine.uc.reg_read(UC_ARM_REG_PC), (0x0402E790, 0x0402E791))

    def test_thumb_ldr_w_and_mov_executes_under_odd_begin(self):
        machine = make_machine()
        # ldr.w sl,[pc,#0x68] ; ldr.w r4,[pc,#0x68] ; mov r0,sp (Thumb-2)
        code = bytes.fromhex('dff868a0dff868406846')
        machine.uc.mem_write(0x0402E790, code)
        machine.uc.reg_write(UC_ARM_REG_CPSR, 0x00000030)
        machine.uc.reg_write(UC_ARM_REG_PC, 0x0402E791)
        machine.uc.emu_start(0x0402E791, 0, count=3)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_PC), 0x0402E79A)


    def test_pending_user_resume_defaults_to_none(self):
        machine = make_machine()
        self.assertIsNone(machine._pending_user_resume)
        # the run loop resumes at the odd LSB produced by thumb_pc
        self.assertEqual(machine.thumb_pc(0x0402E790, 0x30), 0x0402E791)


    def test_tb_remove_cache_api_available(self):
        machine = make_machine()
        # E0467: eviction API used when a cached ARM TB must be dropped
        self.assertTrue(hasattr(machine.uc, 'ctl_remove_cache'))
        machine.uc.ctl_remove_cache(0x0402E000, 0x0402F000)


    def test_thumb_prologue_interpreter_ldr_mov_bl(self):
        machine = make_machine()
        base = 0x0402E790
        code = bytes.fromhex('dff868a0dff86840684603f085f9')
        machine._read_user_bytes = lambda va, size: code[va - base:va - base + size]
        machine._read_user32 = lambda va: {
            0x0402E7FC: 0x11111111,
            0x0402E800: 0x22222222,
        }.get(va)
        res = machine._emulate_thumb_prologue(0x0402E791, 0x30)
        self.assertIsNotNone(res)
        pc, cpsr, trace = res
        self.assertEqual(pc, 0x0403_1AA8)
        self.assertEqual(cpsr, 0x30)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_LR), 0x0402E79F)
        self.assertEqual([t[0] for t in trace], ['ldr', 'ldr', 'mov', 'bl'])


    def test_general_stepper_push(self):
        machine = make_machine()
        mem = {}
        code = bytes.fromhex('2de9f04f')  # push.w {r4-r11,lr}
        machine._read_user_bytes = lambda va, size: code[va - 0x1000:va - 0x1000 + size]
        machine._read_user32 = lambda va: mem.get(va)
        machine._write_user32 = lambda va, val: mem.__setitem__(va, val & 0xFFFFFFFF) or True
        machine.uc.reg_write(UC_ARM_REG_SP, 0x2000)
        machine.uc.reg_write(UC_ARM_REG_R4, 0xAA)
        machine.uc.reg_write(UC_ARM_REG_LR, 0xBB)
        res = machine._step_user_thumb_insns(0x1000, 0x30, max_steps=1)
        self.assertIsNotNone(res)
        pc, cpsr, trace = res
        self.assertEqual([t[0] for t in trace], ['push'])
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_SP), 0x2000 - 9 * 4)
        self.assertIn(0xAA, mem.values())

    def test_general_stepper_ldr_mov_bl(self):
        machine = make_machine()
        base = 0x0402E790
        code = bytes.fromhex('dff868a0dff86840684603f085f9')
        machine._read_user_bytes = lambda va, size: code[va - base:va - base + size]
        machine._read_user32 = lambda va: {
            0x0402E7FC: 0x11111111,
            0x0402E800: 0x22222222,
        }.get(va)
        res = machine._step_user_thumb_insns(0x0402E791, 0x30, max_steps=4)
        self.assertIsNotNone(res)
        pc, cpsr, trace = res
        self.assertEqual(pc, 0x04031AA8)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_LR), 0x0402E79F)
        self.assertEqual([t[0] for t in trace], ['ldr', 'ldr', 'mov', 'bl'])


    def test_general_stepper_callee_block(self):
        machine = make_machine()
        base = 0x04031AA8
        # push.w {r4-r11,lr} ; sub.w sp,sp,#0x1f4 ; ldr.w r3,[pc,#0x7c]
        code = bytes.fromhex('2de9f04fadf51f7ddff87c34')
        machine._read_user_bytes = lambda va, size: code[va - base:va - base + size]
        machine._read_user32 = lambda va: 0x12345678
        machine._write_user32 = lambda va, val: True
        machine.uc.reg_write(UC_ARM_REG_SP, 0x8000)
        res = machine._step_user_thumb_insns(0x04031AA8, 0x30, max_steps=3)
        self.assertIsNotNone(res)
        pc, cpsr, trace = res
        self.assertEqual([t[0] for t in trace], ['push', 'alu', 'ldr'])
        self.assertEqual(pc, 0x04031AB4)


    def test_should_recover_insn_invalid_ignores_cpsr_mode(self):
        machine = make_machine()

        class _Resident:
            def __call__(self, pc):
                return True
        machine._user_pa = _Resident()
        # userspace VA, INSN message -> recover regardless of the reported CPSR
        self.assertTrue(machine._should_recover_insn_invalid(
            0x04031AAC, 'Invalid instruction (UC_ERR_INSN_INVALID)'))
        # kernel VA / other message -> no recovery
        self.assertFalse(machine._should_recover_insn_invalid(
            0x6010DF64, 'Invalid instruction (UC_ERR_INSN_INVALID)'))
        self.assertFalse(machine._should_recover_insn_invalid(
            0x04031AAC, 'Unhandled CPU exception (UC_ERR_EXCEPTION)'))


    def test_stepper_keeps_partial_progress_on_unmapped_literal(self):
        machine = make_machine()
        base = 0x04031AAC
        # sub.w sp,sp,#0x27c ; ldr.w r3,[pc,#0x47c] (literal page not resident)
        code = bytes.fromhex('adf51f7ddff87c34')
        machine._read_user_bytes = lambda va, size: code[va - base:va - base + size]
        machine._read_user32 = lambda va: None
        machine._write_user32 = lambda va, val: True
        res = machine._step_user_thumb_insns(0x04031AAC, 0x30, max_steps=2)
        self.assertIsNotNone(res)
        pc, cpsr, trace = res
        self.assertEqual([t[0] for t in trace], ['alu'])
        self.assertEqual(pc, 0x04031AB0)


if __name__ == '__main__':
    unittest.main()
