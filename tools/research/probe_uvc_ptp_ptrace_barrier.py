"""Execute original ptrace_check_attach; scheduler/lock services are doubles."""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT, KERNEL, KERNEL_SHA


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    out = parser.parse_args().output_dir.resolve()
    if not out.is_relative_to(ROOT / 'artifacts'):
        parser.error('Output must be under artifacts')
    raw = KERNEL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == KERNEL_SHA
    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    base = 0x60108000
    cpu.mem_map(base, (len(raw) + 4095) & ~4095)
    cpu.mem_write(base, raw)
    cpu.mem_map(0x100000, 0x10000)
    cpu.mem_map(0x200000, 0x10000)
    task, tracer, signal, stack, done = 0x100000, 0x101000, 0x102000, 0x20f000, 0x103000
    events = []
    state = {}
    services = {0x6012c0ac, 0x6012bee0, 0x603c6a10, 0x603c69d4,
                0x603c68f4, 0x603c691c}

    def put(address, value):
        cpu.mem_write(address, struct.pack('<I', value))

    def hook(c, address, size, unused):
        if state.get('dispatch') and address == 0x6013edac:
            state['ignore'] = c.reg_read(UC_ARM_REG_R1)
            assert c.reg_read(UC_ARM_REG_R0) == task
            c.emu_stop()
            return
        if state.get('dispatch') and 0x6013f654 <= address <= 0x6013f664:
            return
        if address == done:
            c.emu_stop()
            return
        if address in services:
            events.append(hex(address))
        elif address == 0x6012d3f8:
            assert c.reg_read(UC_ARM_REG_R0) == task
            assert c.reg_read(UC_ARM_REG_R1) == 8
            events.append('wait_task_inactive-double')
            c.reg_write(UC_ARM_REG_R0, state['inactive'])
        elif address == 0x60133e5c:
            events.append('warning-double')
        elif 0x6013edac <= address < 0x6013eec8:
            return
        else:
            raise RuntimeError(f'Unexpected execution {address:08x}')
        c.reg_write(UC_ARM_REG_PC, c.reg_read(UC_ARM_REG_LR))

    cpu.hook_add(UC_HOOK_CODE, hook)
    checks = []
    cases = [
        ('not-traced', 0, tracer, 8, 0, 1, -3, False),
        ('wrong-tracer', 1, tracer + 4, 8, 0, 1, -3, False),
        ('running-target', 1, tracer, 0, 0, 1, -3, False),
        ('stopped-inactive', 1, tracer, 8, 0, 1, 0, True),
        ('stopped-still-running', 1, tracer, 8, 0, 0, -3, True),
        ('ignore-stop-bypasses-inactive', 1, tracer, 0, 1, 0, 0, False),
    ]
    for name, traced, parent, status, ignore, inactive, expected, waits in cases:
        cpu.mem_write(task, bytes(0x3000))
        put(task, status)
        put(task + 0x14, traced)
        put(task + 0x110, parent)
        put(task + 0x220, signal)
        put((stack & ~0x1fff) + 0xc, tracer)
        state['inactive'] = inactive
        events.clear()
        cpu.reg_write(UC_ARM_REG_R0, task)
        cpu.reg_write(UC_ARM_REG_R1, ignore)
        cpu.reg_write(UC_ARM_REG_SP, stack)
        cpu.reg_write(UC_ARM_REG_LR, done)
        cpu.emu_start(0x6013edac, 0xffffffff, count=1000)
        actual = cpu.reg_read(UC_ARM_REG_R0)
        assert actual == expected & 0xffffffff, (name, actual)
        assert ('wait_task_inactive-double' in events) == waits, name
        checks.append(dict(name=name, result=expected, events=list(events)))
    # Execute the original sys_ptrace request-to-ignore_state expression itself.
    # Stop before check_attach: task lookup/refcount and arch_ptrace are not run.
    state['dispatch'] = True
    for request, expected in [(12, 0), (8, 1), (17, 0)]:
        cpu.reg_write(UC_ARM_REG_R4, task)
        cpu.reg_write(UC_ARM_REG_R5, request)
        cpu.reg_write(UC_ARM_REG_SP, stack)
        cpu.emu_start(0x6013f654, 0xffffffff, count=10)
        assert state['ignore'] == expected
        checks.append(dict(name=f'original-sys-ptrace-request-{request}', ignore_state=expected))
    out.mkdir(parents=True, exist_ok=True)
    manifest = dict(status='offline_original_ptrace_checks_passed', kernel_sha256=KERNEL_SHA,
                    entry='0x6013edac', checks=checks,
                    limitations=['Explicit task/current fixtures; no live task lookup or attestation.',
                                 'Locks, preemption, warnings and wait_task_inactive are service doubles.',
                                 'No syscall completion, VFS publication, IRQ or DMA drain proof.'])
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'{len(checks)} original ptrace checks passed; hardware barrier NOT proven')


if __name__ == '__main__':
    main()
