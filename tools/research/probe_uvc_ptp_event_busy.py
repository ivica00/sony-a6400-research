"""Original DWC event worker busy-bit lifetime; explicit event/MMIO fixtures."""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import *
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT, KERNEL, KERNEL_SHA


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', type=Path, required=True)
    out = p.parse_args().output_dir.resolve()
    if not out.is_relative_to(ROOT / 'artifacts'):
        p.error('Output must be under artifacts')
    raw = KERNEL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == KERNEL_SHA
    c = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    c.mem_map(0x60108000, (len(raw) + 4095) & ~4095)
    c.mem_write(0x60108000, raw)
    c.mem_map(0x100000, 0x20000)
    c.mem_map(0x200000, 0x10000)
    dwc, table, event, ring, mmio, ep, driver, callback, done = [0x100000 + i * 0x1000 for i in range(9)]
    trace, checks = [], []
    state = {}

    def put(a, v):
        c.mem_write(a, struct.pack('<I', v & 0xffffffff))

    def word(a):
        return struct.unpack('<I', c.mem_read(a, 4))[0]

    services = {0x6012c0ac: 'migrate-disable', 0x6012bee0: 'migrate-enable',
                0x603c68f4: 'lock', 0x603c691c: 'unlock'}

    def hook(cpu, a, size, unused):
        if a == done:
            state['returned'] = True
            cpu.emu_stop()
            return
        if a in services:
            trace.append(services[a])
            cpu.reg_write(UC_ARM_REG_PC, cpu.reg_read(UC_ARM_REG_LR))
        elif a == callback:
            assert trace[-2:] == ['unlock', 'migrate-enable']
            assert cpu.reg_read(UC_ARM_REG_R0) == dwc + 0x150
            assert cpu.reg_read(UC_ARM_REG_R1) == ring
            trace.append('setup-callback-double')
            cpu.reg_write(UC_ARM_REG_R0, (-95) & 0xffffffff)
            cpu.reg_write(UC_ARM_REG_PC, cpu.reg_read(UC_ARM_REG_LR))
        elif not (0x602b1378 <= a < 0x602b18f8 or 0x602b28e4 <= a < 0x602b2934):
            raise RuntimeError(f'Unexpected execution {a:08x}')

    def write(cpu, access, a, size, value, unused):
        if a == event + 0x10:
            trace.append(['busy-write', value])
        if a == mmio + 0x30c:
            trace.append(['event-ack-write', value])

    c.hook_add(UC_HOOK_CODE, hook)
    c.hook_add(UC_HOOK_MEM_WRITE, write)
    for count in (0, 4, 8):
        c.mem_write(dwc, bytes(0x9000))
        put(dwc + 0xcc, table)
        put(table, event)
        put(event, ring)
        put(event + 0x10, 0xa0)
        put(dwc + 0x2b4, mmio)
        put(dwc + 0x2c8, 1)
        put(dwc + 0xd0, ep)
        # Two endpoint-zero events with a disabled endpoint: no callback double.
        put(mmio + 0x30c, count)
        put(0x604c92d0 + 0x1c, 0)  # Explicit optional MMIO barrier-hook fixture.
        trace.clear()
        state.clear()
        c.reg_write(UC_ARM_REG_R0, 0)
        c.reg_write(UC_ARM_REG_R1, dwc)
        c.reg_write(UC_ARM_REG_SP, 0x20f000)
        c.reg_write(UC_ARM_REG_LR, done)
        c.emu_start(0x602b1378, 0xffffffff, count=2000)
        assert state['returned']
        writes = [e for e in trace if isinstance(e, list)]
        expected = [] if not count else [['busy-write', 0xa1]] + [['event-ack-write', 4]] * (count // 4) + [['busy-write', 0xa0]]
        assert writes == expected, trace
        assert word(event + 8) == count and word(event + 0x10) == 0xa0
        assert word(event + 0xc) == 0
        checks.append(dict(name=f'original-event-worker-{count}-bytes', trace=list(trace)))
    put(dwc + 0x2b0, driver)
    put(driver + 0x10, callback)
    trace.clear()
    state.clear()
    c.reg_write(UC_ARM_REG_R0, dwc)
    c.reg_write(UC_ARM_REG_R1, ring)
    c.reg_write(UC_ARM_REG_SP, 0x20f000)
    c.reg_write(UC_ARM_REG_LR, done)
    c.emu_start(0x602b28e4, 0xffffffff, count=100)
    assert state['returned'] and c.reg_read(UC_ARM_REG_R0) == (-95) & 0xffffffff
    assert trace == ['unlock', 'migrate-enable', 'setup-callback-double', 'migrate-disable', 'lock']
    checks.append(dict(name='original-setup-delegate-lock-order', trace=list(trace)))
    out.mkdir(parents=True, exist_ok=True)
    (out / 'manifest.json').write_text(json.dumps(dict(
        status='offline_original_event_busy_checks_passed', kernel_sha256=KERNEL_SHA,
        checks=checks, limitations=['Event buffers, MMIO and disabled endpoint are explicit fixtures.',
                                   'Locks, migration and delegated setup callback are doubles.',
                                   'Worker and setup-delegate probes are separate, not an end-to-end EP0 path.',
                                   'No physical IRQ/DMA drain or callback completion proof.']), indent=2) + '\n')
    print(f'{len(checks)} original event/dispatch cases passed')


if __name__ == '__main__':
    main()
