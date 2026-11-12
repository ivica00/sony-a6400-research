"""Audited runtime ARM instruction hook engine for the a6400 USB debugger (E0401).

This module is the offline (Unicorn-first) half of the Phase 2 runtime probe:

* `validate_instruction` rejects anything that is not safely relocatable: any
  instruction that reads or writes the program counter (PC-relative loads,
  adr/add rd,pc, branches, pop {pc}, ldrd with pc, svc/undef) is refused.
* `encode_branch` builds the 32-bit ARM B/BL used to divert the hooked address.
* `Trampoline` installs the generated stub, patches the target, fills every
  absolute literal slot, models `flush_icache_range`, and can restore the
  original bytes byte-for-byte.

Kernel text bounds come from verified physical evidence, never a guess:
`/proc/iomem` reports `Kernel text 0x00108000-0x0048d023`, and the kernel
mapping base is PAGE_OFFSET `0x60000000` (E0454), so the virtual text range is
`0x60108000-0x6048d023`. The stub itself must also lie inside that range.

Nothing here writes live kernel memory. The hardware install path is blocked
until the Phase 1 persistent-debugger hardware checks pass.
"""
from __future__ import annotations

import struct

from capstone import CS_ARCH_ARM, CS_MODE_ARM, Cs
from capstone.arm import ARM_OP_REG, ARM_REG_PC

from .arm_hook_stub import (RECORD_BYTES, RECORD_WORDS, STUB_SIZE, STUB_SYMBOLS,
                            STUB_TEXT)

PAGE_OFFSET = 0x60000000
KERNEL_TEXT_PHYSICAL = (0x00108000, 0x0048D023)
KERNEL_TEXT_VIRTUAL = (PAGE_OFFSET + KERNEL_TEXT_PHYSICAL[0],
                       PAGE_OFFSET + KERNEL_TEXT_PHYSICAL[1])
BRANCH_REACH = (1 << 23) - 1  # signed 24-bit word offset => ±32 MiB
A64H_MAGIC = 0x41363448
ARM_NOP = 0xE1A00000
BRANCH_MNEMONICS = {
    'b', 'bl', 'bx', 'blx', 'cbz', 'cbnz', 'tbb', 'tbh',
    'svc', 'smc', 'udf', 'undefined', 'hvc', 'bkpt',
}
RECORD_OFFSETS = {
    'magic': 0, 'sequence': 1, 'ticks': 2,
    'registers': 3,  # 16 words r0-r12, sp, lr, cpsr
    'deref_address': 19, 'deref_value': 20,
    'reserved': 21,
}
REGISTER_ORDER = [f'r{index}' for index in range(13)] + ['sp', 'lr', 'cpsr']


class HookError(RuntimeError):
    """The hook request is unsafe or the engine is in the wrong state."""


class InstructionRejected(HookError):
    def __init__(self, address, word, reason):
        super().__init__(f'instruction 0x{word:08x} at 0x{address:08x} rejected: {reason}')
        self.address = address
        self.word = word
        self.reason = reason


_DISASSEMBLER = Cs(CS_ARCH_ARM, CS_MODE_ARM)
_DISASSEMBLER.detail = True


def inside_kernel_text(address, size=4, bounds=KERNEL_TEXT_VIRTUAL):
    return bounds[0] <= address and address + size <= bounds[1]


def validate_instruction(word, address, bounds=KERNEL_TEXT_VIRTUAL):
    """Return decoded metadata or raise InstructionRejected; never guesses."""
    if address & 3:
        raise InstructionRejected(address, word, 'target is not 4-byte aligned')
    if not inside_kernel_text(address, 4, bounds):
        raise InstructionRejected(address, word, 'target outside verified kernel text bounds')
    instructions = list(_DISASSEMBLER.disasm(struct.pack('<I', word), address))
    if not instructions:
        raise InstructionRejected(address, word, 'not a decodable ARM instruction')
    instruction = instructions[0]
    if instruction.size != 4:
        raise InstructionRejected(address, word, 'not a 32-bit ARM instruction')
    if instruction.mnemonic in BRANCH_MNEMONICS:
        raise InstructionRejected(address, word, f'{instruction.mnemonic} is a control-flow instruction')
    for operand in instruction.operands:
        if operand.type == ARM_OP_REG and operand.reg == ARM_REG_PC:
            raise InstructionRejected(address, word, 'operand names PC (PC-relative)')
    try:
        reads, writes = instruction.regs_access()
    except Exception:
        raise InstructionRejected(address, word, 'register access cannot be proven')
    if ARM_REG_PC in writes:
        raise InstructionRejected(address, word, 'writes PC (not relocatable)')
    if ARM_REG_PC in reads:
        raise InstructionRejected(address, word, 'reads PC (PC-relative, not relocatable)')
    return {'address': address, 'word': word, 'mnemonic': instruction.mnemonic,
            'operands': instruction.op_str, 'size': instruction.size}


def encode_branch(source, target, link=False):
    """Encode ARM B/BL from source to target within the ±32 MiB branch range."""
    if source & 3 or target & 3:
        raise HookError('branch source and target must be 4-byte aligned')
    offset = target - (source + 8)
    if offset & 3:
        raise HookError('branch target is not word aligned')
    words = offset >> 2
    if not -(BRANCH_REACH + 1) <= words <= BRANCH_REACH:
        raise HookError(f'branch distance {offset} outside ARM ±32 MiB range')
    opcode = 0xEB000000 if link else 0xEA000000
    return opcode | (words & 0xFFFFFF)


def plan_slots(stub_base):
    """Absolute addresses of every stub literal slot, from generated symbols."""
    if stub_base & 3:
        raise HookError('stub base must be 4-byte aligned')
    return {name: stub_base + offset for name, offset in STUB_SYMBOLS.items()}


class Trampoline:
    """One installable hook over caller-supplied Unicorn-like memory access."""

    def __init__(self, memory, stub_base, bounds=KERNEL_TEXT_VIRTUAL, flush=None):
        self.memory = memory              # object with read(address,size)/write(address,data)
        self.stub_base = stub_base
        self.bounds = bounds
        self.flush = flush or (lambda start, end: None)
        self.flushes = []
        self.installed = None
        self.slots = plan_slots(stub_base)
        if not inside_kernel_text(stub_base, STUB_SIZE, bounds):
            raise HookError('stub is outside verified kernel text bounds')

    # -- memory helpers -------------------------------------------------
    def _read_word(self, address):
        return struct.unpack('<I', self.memory.read(address, 4))[0]

    def _write_word(self, address, word):
        self.memory.write(address, struct.pack('<I', word))

    def _flush(self, start, end):
        self.flushes.append((start, end))
        self.flush(start, end)

    def _write_stub_slots(self, target, ring):
        slot = self.slots
        self._write_word(slot['a6400_hook_ring_next_slot'], ring['next'])
        self._write_word(slot['a6400_hook_ring_base_slot'], ring['base'])
        self._write_word(slot['a6400_hook_ring_limit_slot'], ring['limit'])
        self._write_word(slot['a6400_hook_seq_slot'], ring['sequence'])
        self._write_word(slot['a6400_hook_ticks_slot'], ring['ticks'])
        self._write_word(slot['a6400_hook_config_slot'], ring.get('config', 0))
        self._write_word(slot['a6400_hook_magic_slot'], A64H_MAGIC)
        self._write_word(slot['a6400_hook_exec_slot'], slot['a6400_hook_saved_instruction'])
        self._write_word(slot['a6400_hook_target_next_slot'], target + 4)

    def install(self, target, ring):
        """Install the hook; returns a JSON-serialisable receipt."""
        if self.installed is not None:
            raise HookError('a hook is already installed')
        if not inside_kernel_text(target, 4, self.bounds):
            raise HookError('target outside verified kernel text bounds')
        original = self._read_word(target)
        decoded = validate_instruction(original, target, self.bounds)
        branch = encode_branch(target, self.slots['a6400_hook_stub'])
        self.memory.write(self.stub_base, STUB_TEXT)
        self._write_word(self.slots['a6400_hook_saved_instruction'], original)
        self._write_stub_slots(target, ring)
        self._flush(self.stub_base, self.stub_base + STUB_SIZE)
        self._write_word(target, branch)
        self._flush(target, target + 4)
        self.installed = {'target': target, 'original': original, 'branch': branch,
                          'decoded': decoded, 'ring': dict(ring)}
        return {'installed': True, 'target': hex(target), 'original_word': hex(original),
                'branch_word': hex(branch), 'stub': hex(self.stub_base),
                'stub_bytes': STUB_SIZE, 'mnemonic': decoded['mnemonic'],
                'flushes': [list(map(hex, pair)) for pair in self.flushes]}

    def clear(self):
        """Restore every patched instruction and flush; returns a receipt."""
        if self.installed is None:
            raise HookError('no hook is installed')
        target = self.installed['target']
        self._write_word(target, self.installed['original'])
        self._flush(target, target + 4)
        self._write_word(self.slots['a6400_hook_saved_instruction'], ARM_NOP)
        self._flush(self.slots['a6400_hook_saved_instruction'],
                    self.slots['a6400_hook_saved_instruction'] + 4)
        restored = self._read_word(target)
        receipt = {'cleared': True, 'target': hex(target),
                   'restored_word': hex(restored),
                   'byte_equal': restored == self.installed['original'],
                   'flushes': [list(map(hex, pair)) for pair in self.flushes]}
        self.installed = None
        self.flushes = []
        return receipt


def decode_record(raw, offset=0):
    """Decode one 96-byte ring record; fail closed on a short or foreign record."""
    if len(raw) - offset < RECORD_BYTES:
        raise HookError('ring record is truncated')
    words = struct.unpack_from('<%dI' % RECORD_WORDS, raw, offset)
    if words[0] != A64H_MAGIC:
        raise HookError(f'ring record magic mismatch: 0x{words[0]:08x}')
    return {
        'magic': words[0],
        'sequence': words[1],
        'ticks': words[2],
        'registers': dict(zip(REGISTER_ORDER, words[3:19])),
        'deref_address': words[19],
        'deref_value': words[20],
        'reserved': list(words[21:24]),
    }
