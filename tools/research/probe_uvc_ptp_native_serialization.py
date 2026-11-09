"""Execute original Sony ioctl/atomic bodies up to destructive boundaries.

All object state is explicit fixture data. No camera access, hardware calls,
successful mode switch or observed physical race is claimed.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT, KERNEL, KERNEL_SHA


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if not out.is_relative_to(ROOT / 'artifacts'):
        parser.error('Output must be under artifacts')
    raw = KERNEL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == KERNEL_SHA
    base = 0x60108000
    gc, gadget, ops, old_root = 0x200000, 0x201000, 0x202000, 0x203000
    pullup, done = 0x300000, 0x300004
    checks, traces = [], []

    def machine(flags):
        cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        cpu.mem_map(base, (len(raw) + 4095) & ~4095)
        cpu.mem_write(base, raw)
        cpu.mem_map(0x6051b000, 4096)
        cpu.mem_map(0x200000, 0x10000)
        cpu.mem_map(0x300000, 4096)
        cpu.mem_map(0x400000, 0x10000)
        def put(a, n): cpu.mem_write(a, struct.pack('<I', n))
        put(0x6051b17c, gc)
        put(gc, gadget); put(gadget + 0x10, ops); put(ops + 0x14, pullup)
        put(gc + 0x68, flags); put(gc + 0x6c, old_root)
        events = []
        def hook(c, address, size, _):
            if address in (pullup, 0x602bc550):
                events.append(dict(boundary=hex(address), flags=word(c, gc + 0x68),
                                   root=hex(word(c, gc + 0x6c))))
                c.emu_stop()
            elif address == 0x602b5ff0:
                # Explicit speed service double. No controller code executes.
                events.append(dict(service='speed-double'))
                c.reg_write(UC_ARM_REG_R0, 3)
                c.reg_write(UC_ARM_REG_PC, c.reg_read(UC_ARM_REG_LR))
            elif address == done:
                c.emu_stop()
            elif not any(a <= address < b for a, b in (
                (0x602b8844, 0x602b8ab0), (0x60259588, 0x60259618))):
                raise RuntimeError(f'Unexpected execution {address:08x}')
        def write_guard(c, access, address, size, value, _):
            if not any(a <= address and address + size <= b for a,b in (
                (gc, gc + 0x100), (0x400000, 0x410000))):
                raise RuntimeError(f'Unexpected write {address:08x}')
        cpu.hook_add(UC_HOOK_CODE, hook)
        cpu.hook_add(UC_HOOK_MEM_WRITE, write_guard)
        return cpu, events

    def word(c, address): return struct.unpack('<I', c.mem_read(address, 4))[0]
    def invoke(c, command, stack=0x40f000):
        c.reg_write(UC_ARM_REG_R0, 0)
        c.reg_write(UC_ARM_REG_R1, command)
        c.reg_write(UC_ARM_REG_R2, 0x204000)
        c.reg_write(UC_ARM_REG_SP, stack)
        c.reg_write(UC_ARM_REG_LR, done)
        c.emu_start(0x602b8844, 0xffffffff, count=10000)
        return c.reg_read(UC_ARM_REG_PC)
    def check(name, passed):
        if not passed: raise AssertionError(name)
        checks.append(name)

    # Native literal is read rather than guessing ioctl command encoding.
    commit = struct.unpack_from('<I', raw, 0x602b8ab0 - base)[0]
    check('commit-command', commit == 0x400ce203)
    cpu, events = machine(4)
    check('active-commit-returns', invoke(cpu, commit) == done)
    check('active-commit-busy', cpu.reg_read(UC_ARM_REG_R0) == 0xfffffff0)
    check('busy-preserves-active-bit', word(cpu, gc + 0x68) == 4)
    check('busy-no-destructive-boundary', not events)
    cpu, events = machine(8)
    check('commit-with-other-flags-reaches-save', invoke(cpu, commit) == 0x602bc550)
    check('commit-preserves-other-flags', word(cpu, gc + 0x68) == 12)
    cpu, events = machine(12)
    check('disconnect-with-other-flags-reaches-pullup', invoke(cpu, 0xe204) == pullup)
    check('disconnect-preserves-other-flags', word(cpu, gc + 0x68) == 8)
    cpu, events = machine(0)
    check('inactive-disconnect-returns', invoke(cpu, 0xe204) == done)
    check('inactive-disconnect-noop', not events and word(cpu, gc + 0x6c) == old_root)
    cpu, events = machine(4)
    check('disconnect-stops-before-pullup', invoke(cpu, 0xe204) == pullup)
    check('disconnect-clears-active-before-pullup', word(cpu, gc + 0x68) == 0)
    check('disconnect-old-root-still-owned', word(cpu, gc + 0x6c) == old_root)
    # Explicit interleaving fixture: first call remains paused before pullup;
    # another stack invokes original commit. This proves a missing exclusion
    # in this entry path, not that real scheduling permits this interleaving.
    check('interleaved-commit-reaches-save', invoke(cpu, commit, 0x40d000) == 0x602bc550)
    check('interleaved-commit-reactivates-bit', word(cpu, gc + 0x68) == 4)
    check('interleaved-save-sees-old-root', word(cpu, gc + 0x6c) == old_root)
    traces.extend(events)
    report = dict(status='original_native_boundary_checks_passed', count=len(checks),
        checks=checks, traces=traces, kernel_sha256=KERNEL_SHA, camera_access=False,
        executed_original_ranges=['602b8844..602b8aac', '60259588..60259614'],
        conclusion='Native active flag is not transaction-wide mutual exclusion.',
        limitations=['GC/gadget/ops/root and two stacks are explicit fixtures.',
            'Speed service is an explicit double; pullup/save are stop boundaries.',
            'External callers may serialize ioctl calls; this probe does not establish their scheduling.',
            'No native locking solution, physical race, module deployment or sensor frames proven.'])
    out.mkdir(parents=True, exist_ok=True)
    (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
