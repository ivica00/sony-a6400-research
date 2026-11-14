import gc
import struct
import unittest
from unicorn.arm_const import (UC_ARM_REG_CPSR, UC_ARM_REG_LR, UC_ARM_REG_PC,
                              UC_ARM_REG_R0, UC_ARM_REG_R4, UC_ARM_REG_R8,
                              UC_ARM_REG_SPSR,
                              UC_ARM_REG_SP)

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
    def tearDown(self):
        gc.collect()

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


    def test_take_user_frame_consumes_generation_once(self):
        machine = make_machine()
        machine.pt_frame_last = {
            'gen': 7, 'words': [0] * 18, 'sp': 0x5E864F10,
            'lr': 0x0402E790, 'pc': 0x0402E790, 'cpsr': 0x30}
        first = machine._take_user_frame()
        self.assertIsNotNone(first)
        self.assertEqual(first['gen'], 7)
        self.assertEqual(machine.pt_frame_consumed, 7)
        # a second hit without a new frame must not replay it
        self.assertIsNone(machine._take_user_frame())
        machine.pt_frame_last = dict(machine.pt_frame_last, gen=8)
        third = machine._take_user_frame()
        self.assertEqual(third['gen'], 8)
        self.assertEqual(machine.pt_frame_consumed, 8)


    def test_stepper_mov_high_register_r8(self):
        machine = make_machine()
        base = 0x04031A00
        # mov r8, r0 (Thumb 16-bit high-register MOV, 0x4680 -> bytes 80 46)
        code = bytes.fromhex('8046')
        machine._read_user_bytes = lambda va, size: code[va - base:va - base + size]
        machine.uc.reg_write(UC_ARM_REG_R0, 0x5E864F10)
        res = machine._step_user_thumb_insns(0x04031A00, 0x30, max_steps=1)
        self.assertIsNotNone(res)
        self.assertEqual(res[0], 0x04031A02)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_R8), 0x5E864F10)

    def test_user_frame_keeps_r8_slot_for_restore(self):
        machine = make_machine()
        words = [0] * 18
        words[8] = 0x5E864F10   # pt_regs + 0x20 == r8
        words[0x34 // 4] = 0x5E864F10
        words[0x3C // 4] = 0x0402E790
        words[0x40 // 4] = 0x30
        machine.pt_frame_last = {'gen': 1, 'words': words,
                                 'sp': words[13], 'lr': 0,
                                 'pc': words[15], 'cpsr': words[16]}
        frame = machine._take_user_frame()
        self.assertIsNotNone(frame)
        self.assertEqual(frame['words'][8], 0x5E864F10)
        self.assertEqual(frame['words'][0x20 // 4], 0x5E864F10)
        self.assertEqual(frame['words'][0x34 // 4], 0x5E864F10)


    def test_recovery_syncs_user_bank_from_frame(self):
        machine = make_machine()
        words = [0] * 18
        words[0] = 0x5E864F10
        words[8] = 0x5E864F10
        words[0x34 // 4] = 0x5E864F10
        words[0x3C // 4] = 0x04031AA8
        words[0x40 // 4] = 0x30
        machine.pt_frame_last = {'gen': 5, 'words': words, 'sp': 0x5E864F10,
                                 'lr': 0, 'pc': 0x04031AA8, 'cpsr': 0x30}
        machine.uc.reg_write(UC_ARM_REG_CPSR, 0x13 | 0xC0)
        machine.uc.reg_write(UC_ARM_REG_SP, 0x60472990)  # kernel stack
        synced = machine._sync_user_bank_for_recovery(0x04031AAC, 0x30)
        self.assertTrue(synced)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_SP), 0x5E864EEC)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_R0), 0x5E864F10)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_R8), 0x5E864F10)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_CPSR) & 0x1F, 0x10)


    def test_svc_return_address_uses_true_instruction(self):
        machine = make_machine()
        # SVC at 0x1000 (Thumb 0xDF00); Unicorn reports PC after it (0x1002)
        machine.uc.mem_write(0x1000, b'\x00\xdf')
        self.assertEqual(machine._svc_return_address(0x1002, True), 0x1002)
        self.assertEqual(machine._svc_return_address(0x1000, True), 0x1002)
        # ARM SVC (0xEF000000) at 0x2000, reported after it (0x2004)
        machine.uc.mem_write(0x2000, b'\x00\x00\x00\xef')
        self.assertEqual(machine._svc_return_address(0x2004, False), 0x2004)


    def test_swi_captures_user_bank_before_switch(self):
        machine = make_machine()
        machine._symbol_address = lambda name: 0x6010DFA0
        machine.uc.mem_write(0x1000, b'\x00\xdf')
        machine.uc.reg_write(UC_ARM_REG_CPSR, 0x30)   # USR + Thumb
        machine.uc.reg_write(UC_ARM_REG_SP, 0x5E864F10)
        machine.uc.reg_write(UC_ARM_REG_LR, 0x0403E98D)
        machine.uc.mem_write(0x1000, b'\x00\xdf')
        machine.uc.reg_write(UC_ARM_REG_PC, 0x1001)  # odd PC keeps Thumb
        machine._on_interrupt(machine.uc, 2)
        self.assertEqual(machine.svc_hits, 1)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_SPSR), 0x30)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_CPSR) & 0x1F, 0x13)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_PC), 0x6010DFA0)
        self.assertEqual(machine._pending_swi_usr_sp, 0x5E864F10)
        self.assertEqual(machine._pending_swi_usr_lr, 0x0403E98D)

    def test_vector_stmdb_is_single_shot_into_ptregs(self):
        machine = make_machine()
        machine._pending_swi_usr_sp = 0x5E864C04
        machine._pending_swi_usr_lr = 0x0403E98D
        machine.uc.reg_write(UC_ARM_REG_CPSR, 0x93)
        machine.uc.reg_write(UC_ARM_REG_R8, 0x6000303C)
        self.assertTrue(machine._emulate_vector_stmdb(machine.uc))
        self.assertFalse(machine._emulate_vector_stmdb(machine.uc))
        sp_word = int.from_bytes(bytes(machine.uc.mem_read(0x3034, 4)), 'little')
        lr_word = int.from_bytes(bytes(machine.uc.mem_read(0x3038, 4)), 'little')
        self.assertEqual(sp_word, 0x5E864C04)
        self.assertEqual(lr_word, 0x0403E98D)


    def test_fast_syscall_return_enforces_usr_thumb_odd_pc(self):
        machine = make_machine()
        words = [0] * 20
        words[0] = 0x00055000          # r0 = new brk value
        words[13] = 0x5E864C04         # SP_usr
        words[14] = 0x0403E98D         # LR_usr
        words[15] = 0x0403EB16         # ARM_pc (even, Thumb code)
        words[16] = 0x600000F0         # ARM_cpsr USR|Thumb
        machine._fast_frame = {'words': words[:17], 'sp': 0x5E864C04,
                               'lr': 0x0403E98D, 'pc': 0x0403EB16,
                               'cpsr': 0x600000F0}
        machine.uc.reg_write(UC_ARM_REG_CPSR, 0x93)
        machine.uc.reg_write(UC_ARM_REG_LR, 0x0403EB16)
        self.assertTrue(machine._restore_fast_syscall_user_return(machine.uc))
        cpsr = machine.uc.reg_read(UC_ARM_REG_CPSR)
        self.assertEqual(cpsr & 0x1F, 0x10)     # USR
        self.assertTrue(cpsr & 0x20)            # Thumb
        # Unicorn stores the architectural (even) PC; CPSR.T carries Thumb.
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_PC) & ~1, 0x0403EB16)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_SP), 0x5E864C04)
        self.assertEqual(machine.uc.reg_read(UC_ARM_REG_R0), 0x00055000)

    def test_decode_fault_address_thumb2_pc_relative_ldr(self):
        machine = make_machine()
        # 0x0402F666: dff8ec4b = ldr.w r4, [pc, #0xbec] -> ((0x0402F666 + 4) & ~3) + 0xbec = 0x04030254
        pa = 0x0042F666
        machine.uc.mem_write(pa, bytes.fromhex('dff8ec4b'))
        machine._set_pc_and_cpsr(0x0402F666, 0x600000F0)
        decoded = machine._decode_fault_address(0x0402F666, pa)
        self.assertEqual(decoded, (0x04030254, False))

    def test_capture_fast_syscall_frame_preserves_live_r0(self):
        machine = make_machine()
        sp = 0x60003000
        # At 0x6010DEC0 (ret_fast_syscall), pt_regs starts at sp + 8, where ARM_r0 is 0,
        # while the live syscall return value (0x00055000) is in R0.
        pt_words = [0] * 18
        pt_words[13] = 0x5E864C04
        pt_words[14] = 0x0403E98D
        pt_words[15] = 0x0403EB16
        pt_words[16] = 0x600000F0
        import struct
        machine.uc.mem_write(0x3008, struct.pack('<18I', *pt_words))
        machine.uc.reg_write(UC_ARM_REG_CPSR, 0x93)
        machine.uc.reg_write(UC_ARM_REG_SP, sp)
        machine.uc.reg_write(UC_ARM_REG_R0, 0x00055000)
        machine._capture_fast_syscall_frame(machine.uc)
        self.assertIsNotNone(machine._fast_frame)
        self.assertEqual(machine._fast_frame['words'][0], 0x00055000)

    def test_on_tlb_fill_respects_armv7_ap2_and_xn(self):
        import struct
        from types import SimpleNamespace

        machine = make_machine(virtual_tlb_on_userspace=True)
        machine._mmu_enabled = True
        machine._cached_ttbr0 = 0x10000
        # L1 entry at 0x10000 + (0x041F1000 >> 20)*4 -> L2 table at 0x20000 (type=1)
        l1_idx = (0x041F1000 >> 20) & 0xFFF
        machine.uc.mem_write(0x10000 + l1_idx * 4, struct.pack('<I', 0x20001))

        cases = [
            # empty_zero_page: AP[2]=1, AP[1:0]=3, XN=1 -> READ only (1)
            (0xBF7FEE7F, 0xBF7FE000, 1),
            # RWX: AP[2]=0, AP[1:0]=3, XN=0 -> ALL (7)
            (0x0042F03E, 0x0042F000, 7),
            # RX: AP[2]=1, AP[1:0]=3, XN=0 -> READ|EXEC (5)
            (0x0042F23E, 0x0042F000, 5),
            # RW NX: AP[2]=0, AP[1:0]=3, XN=1 -> READ|WRITE (3)
            (0x0042F03F, 0x0042F000, 3),
        ]
        l2_idx = (0x041F1000 >> 12) & 0xFF
        for l2_val, expected_pa, expected_perms in cases:
            machine.uc.mem_write(0x20000 + l2_idx * 4, struct.pack('<I', l2_val))
            entry = SimpleNamespace(paddr=0, perms=0)
            ok = machine._on_tlb_fill(machine.uc, 0x041F1000, 16, entry)
            self.assertTrue(ok)
            self.assertEqual(entry.paddr, expected_pa)
            self.assertEqual(entry.perms, expected_perms)


if __name__ == '__main__':
    unittest.main()
