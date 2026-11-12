import struct
import unittest

from src.a6400.debug import arm_hook
from src.a6400.debug.arm_hook_stub import (RECORD_BYTES, RECORD_WORDS, STUB_SIZE,
                                           STUB_SYMBOLS, STUB_TEXT)


class BranchEncodingTests(unittest.TestCase):
    def test_forward_branch_encodes_and_round_trips(self):
        source, target = 0x60120000, 0x60400000
        word = arm_hook.encode_branch(source, target)
        self.assertEqual(word & 0xFF000000, 0xEA000000)
        offset = (word & 0xFFFFFF) << 2
        self.assertEqual(source + 8 + offset, target)

    def test_backward_and_link_branches(self):
        word = arm_hook.encode_branch(0x60120000, 0x60110000, link=True)
        self.assertEqual(word & 0xFF000000, 0xEB000000)
        delta = word & 0xFFFFFF
        if delta & 0x800000:
            delta -= 0x1000000
        self.assertEqual(0x60120000 + 8 + (delta << 2), 0x60110000)

    def test_misaligned_and_out_of_range_are_rejected(self):
        with self.assertRaises(arm_hook.HookError):
            arm_hook.encode_branch(0x60120002, 0x60400000)
        with self.assertRaises(arm_hook.HookError):
            arm_hook.encode_branch(0x60120000, 0x62200000)

    def test_signed_negative_offset_is_encoded_as_twos_complement(self):
        word = arm_hook.encode_branch(0x60120000, 0x6011FFF0)
        self.assertEqual(word & 0xFFFFFF, 0xFFFFFA)


class InstructionValidationTests(unittest.TestCase):
    def test_plain_data_processing_and_memory_instructions_are_accepted(self):
        accepted = [
            (0xE2800001, 'add r0, r0, #1'),
            (0xE1A01000, 'mov r1, r0'),
            (0xE5901000, 'ldr r1, [r0]'),
            (0xE5801000, 'str r1, [r0]'),
            (0xE1A00000, 'nop'),
            (0xE92D4000, 'push {lr}'),
        ]
        for word, description in accepted:
            decoded = arm_hook.validate_instruction(word, 0x60120000)
            self.assertEqual(decoded['word'], word, description)

    def test_pc_relative_and_control_flow_instructions_are_rejected(self):
        rejected = [
            (0xE59F0004, 'ldr r0, [pc, #4]'),
            (0xE28F0004, 'add r0, pc, #4'),
            (0xEA000000, 'b'),
            (0xEB000000, 'bl'),
            (0xE12FFF1E, 'bx lr'),
            (0xE12FFF10, 'bx r0'),
            (0xE8BD8000, 'pop {pc}'),
            (0xE1A0F000, 'mov pc, r0'),
            (0xEF000000, 'svc'),
        ]
        for word, description in rejected:
            with self.assertRaises(arm_hook.InstructionRejected, msg=description):
                arm_hook.validate_instruction(word, 0x60120000)

    def test_targets_outside_verified_kernel_text_are_rejected(self):
        for address in (0x60100000, 0x60107FFC, 0x6048D024, 0x61000000):
            with self.assertRaises(arm_hook.InstructionRejected):
                arm_hook.validate_instruction(0xE1A00000, address)
        self.assertTrue(arm_hook.inside_kernel_text(0x60120000))

    def test_generated_stub_slots_are_inside_the_stub(self):
        self.assertEqual(STUB_SYMBOLS['a6400_hook_stub'], 0)
        self.assertLessEqual(len(STUB_TEXT), STUB_SIZE)
        for name, offset in STUB_SYMBOLS.items():
            self.assertGreaterEqual(offset, 0, name)
            self.assertLessEqual(offset + 4, STUB_SIZE, name)


class UcMemory:
    def __init__(self, uc):
        self.uc = uc

    def read(self, address, size):
        return bytes(self.uc.mem_read(address, size))

    def write(self, address, data):
        self.uc.mem_write(address, bytes(data))


class TrampolineUnicornTests(unittest.TestCase):
    """Runs the assembled ARM stub in Unicorn: the mandatory pre-hardware proof."""

    CODE_BASE = 0x60000000
    CODE_SIZE = 0x00800000
    STUB_BASE = 0x60400000
    TARGET = 0x60120000
    RAM_BASE = 0x70000000
    RAM_SIZE = 0x00400000
    CALLER = 0x60080000
    SENTINEL = 0x60080010
    STACK = 0x70080000
    RING = 0x70100000
    RING_LIMIT = RING + 4096
    SEQ = 0x70100800
    TICKS = 0x70100804
    CONFIG = 0x70100808          # three words: enabled, register index, byte offset
    NEXT_WORD = 0x70100820
    BASE_WORD = 0x70100824
    LIMIT_WORD = 0x70100828
    DEREF = 0x70200000
    DEREF_VALUE = 0xDEADBEEF

    def setUp(self):
        import unicorn
        from unicorn import arm_const
        self.unicorn = unicorn
        self.arm = arm_const
        self.uc = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.uc.mem_map(self.CODE_BASE, self.CODE_SIZE)
        self.uc.mem_map(self.RAM_BASE, self.RAM_SIZE)
        self.memory = UcMemory(self.uc)
        self.uc.reg_write(arm_const.UC_ARM_REG_SP, self.STACK)
        self._write_caller()
        self._write_target()
        self.uc.mem_write(self.DEREF, struct.pack('<I', self.DEREF_VALUE))
        self._write_word(self.NEXT_WORD, self.RING)
        self._write_word(self.BASE_WORD, self.RING)
        self._write_word(self.LIMIT_WORD, self.RING_LIMIT)
        self._write_word(self.SEQ, 0xFFFFFFF0)
        self._write_word(self.TICKS, 0x00001234)
        self._write_word(self.CONFIG, 1)
        self._write_word(self.CONFIG + 4, 2)   # r2
        self._write_word(self.CONFIG + 8, 0)   # offset
        self.ring = {'next': self.NEXT_WORD, 'base': self.BASE_WORD,
                     'limit': self.LIMIT_WORD, 'sequence': self.SEQ,
                     'ticks': self.TICKS, 'config': self.CONFIG}

    # -- helpers ------------------------------------------------------
    def _write_word(self, address, word):
        self.uc.mem_write(address, struct.pack('<I', word))

    def _read_word(self, address):
        return struct.unpack('<I', self.uc.mem_read(address, 4))[0]

    def _write_target(self):
        words = [0xE2800001,  # add r0, r0, #1
                 0xE1A01000,  # mov r1, r0
                 0xE0802001,  # add r2, r0, r1
                 0xE12FFF1E]  # bx lr
        self.uc.mem_write(self.TARGET, b''.join(struct.pack('<I', w) for w in words))

    def _write_caller(self):
        caller = [
            0xE3A00041,                                  # mov r0, #0x41
            0xE3A01000,                                  # mov r1, #0
            0xE59F2010,                                  # ldr r2, [pc, #0x10]
            arm_hook.encode_branch(self.CALLER + 0x0C, self.TARGET, link=True),
            0xEAFFFFFE,                                  # b .
            0xE1A00000, 0xE1A00000, 0xE1A00000,          # padding
            self.DEREF,
        ]
        self.uc.mem_write(self.CALLER, b''.join(struct.pack('<I', w) for w in caller))

    def _execute(self):
        self.uc.reg_write(self.arm.UC_ARM_REG_SP, self.STACK)
        self.uc.reg_write(self.arm.UC_ARM_REG_LR, 0)
        stop = []
        handle = self.uc.hook_add(self.unicorn.UC_HOOK_CODE,
                                  lambda uc, address, size, _: (uc.emu_stop(), stop.append(address))
                                  if address == self.SENTINEL else None,
                                  begin=self.SENTINEL, end=self.SENTINEL)
        try:
            self.uc.emu_start(self.CALLER, 0, count=10000)
        finally:
            self.uc.hook_del(handle)
        self.assertTrue(stop, 'caller never reached the return sentinel')
        return self.uc.reg_read(self.arm.UC_ARM_REG_R0), \
            self.uc.reg_read(self.arm.UC_ARM_REG_R1), \
            self.uc.reg_read(self.arm.UC_ARM_REG_R2)

    def _trampoline(self):
        return arm_hook.Trampoline(self.memory, self.STUB_BASE)

    # -- tests --------------------------------------------------------
    def test_install_capture_saved_instruction_and_clean_return(self):
        original = self._read_word(self.TARGET)
        engine = self._trampoline()
        receipt = engine.install(self.TARGET, self.ring)
        self.assertTrue(receipt['installed'])
        self.assertEqual(self._read_word(self.TARGET) & 0xFF000000, 0xEA000000)
        r0, r1, r2 = self._execute()
        self.assertEqual((r0, r1, r2), (0x42, 0x42, 0x84))
        self.assertEqual(self._read_word(self.NEXT_WORD), self.RING + RECORD_BYTES)
        record = arm_hook.decode_record(self.memory.read(self.RING, RECORD_BYTES))
        self.assertEqual(record['sequence'], 0xFFFFFFF0)
        self.assertEqual(record['ticks'], 0x00001234)
        registers = record['registers']
        self.assertEqual(registers['r0'], 0x41)          # captured before the saved instruction
        self.assertEqual(registers['r1'], 0)
        self.assertEqual(registers['r2'], self.DEREF)
        self.assertEqual(registers['lr'], self.SENTINEL)
        self.assertEqual(registers['sp'], self.STACK)
        self.assertEqual(record['deref_address'], self.DEREF)
        self.assertEqual(record['deref_value'], self.DEREF_VALUE)
        self.assertEqual(record['reserved'], [0, 0, 0])
        self.assertEqual(engine.installed['original'], original)

    def test_saved_instruction_really_executes(self):
        # If the saved add were skipped, r0 would stay 0x41 and r1/r2 would be 0x41/0x82.
        self._trampoline().install(self.TARGET, self.ring)
        self.assertEqual(self._execute(), (0x42, 0x42, 0x84))

    def test_rollback_is_byte_for_byte_and_flushes_both_regions(self):
        original = self._read_word(self.TARGET)
        engine = self._trampoline()
        engine.install(self.TARGET, self.ring)
        receipt = engine.clear()
        self.assertTrue(receipt['byte_equal'])
        self.assertEqual(self._read_word(self.TARGET), original)
        self.assertEqual(self._read_word(0x60400000 + STUB_SYMBOLS['a6400_hook_saved_instruction']),
                         arm_hook.ARM_NOP)
        install_flushes = [tuple(pair) for pair in receipt['flushes']]
        self.assertIn((hex(self.TARGET), hex(self.TARGET + 4)), install_flushes)
        # A second execution without a hook still behaves exactly like the original function.
        self.assertEqual(self._execute(), (0x42, 0x42, 0x84))
        self.assertEqual(self._read_word(self.TARGET), original)

    def test_cycle_counter_wraps_through_the_limited_ring(self):
        engine = self._trampoline()
        near_end = self.RING + 4096 - RECORD_BYTES
        self._write_word(self.NEXT_WORD, near_end)
        engine.install(self.TARGET, self.ring)
        self._execute()
        self.assertEqual(self._read_word(self.NEXT_WORD), self.RING)
        record = arm_hook.decode_record(self.memory.read(near_end, RECORD_BYTES))
        self.assertEqual(record['sequence'], 0xFFFFFFF0)

    def test_pc_relative_target_is_refused_without_patching(self):
        word = 0xE59F0004  # ldr r0, [pc, #4]
        self._write_word(self.TARGET, word)
        engine = self._trampoline()
        with self.assertRaises(arm_hook.InstructionRejected):
            engine.install(self.TARGET, self.ring)
        self.assertEqual(self._read_word(self.TARGET), word)
        self.assertIsNone(engine.installed)

    def test_double_install_and_double_clear_are_refused(self):
        engine = self._trampoline()
        engine.install(self.TARGET, self.ring)
        with self.assertRaises(arm_hook.HookError):
            engine.install(self.TARGET, self.ring)
        engine.clear()
        with self.assertRaises(arm_hook.HookError):
            engine.clear()

    def test_stub_base_outside_kernel_text_is_refused(self):
        with self.assertRaises(arm_hook.HookError):
            arm_hook.Trampoline(self.memory, 0x61000000)


if __name__ == '__main__':
    unittest.main()
