"""Original DWC pullup control flow, with explicit hardware/scheduler doubles."""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
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
    c.mem_map(0x100000, 0x10000)
    c.mem_map(0x200000, 0x10000)
    dwc, link, busy, ep0, ep1, done = 0x100000, 0x101000, 0x102000, 0x103000, 0x104000, 0x105000
    events, state, checks = [], {}, []
    services = {0x6012c0ac: 'migrate-disable', 0x6012bee0: 'migrate-enable',
                0x603c68f4: 'lock', 0x603c691c: 'unlock',
                0x603c4e68: 'reschedule', 0x602b04f4: 'stop-transfers',
                0x602b1a3c: 'disable-endpoint', 0x602af150: 'disconnect-notify',
                0x602aeffc: 'run-stop'}

    def put(a, v):
        c.mem_write(a, struct.pack('<I', v & 0xffffffff))

    def hook(cpu, a, size, unused):
        if a == done:
            state['returned'] = True
            cpu.emu_stop()
            return
        name = services.get(a)
        if name:
            r0, r1 = cpu.reg_read(UC_ARM_REG_R0), cpu.reg_read(UC_ARM_REG_R1)
            events.append([name, r0, r1])
            if name in ('lock', 'unlock'):
                assert r0 == dwc + 0x70
            if name == 'reschedule':
                state['yields'] += 1
                if state['clear_after'] == state['yields']:
                    put(busy + 0x10, 0)
                if state['yields'] == 20:
                    state['bounded_observation_stop'] = True
                    cpu.emu_stop()
                    return
            if name in ('stop-transfers', 'disconnect-notify', 'run-stop'):
                assert r0 == dwc
            if name == 'disable-endpoint':
                assert r0 in (ep0, ep1)
            if name == 'run-stop':
                assert r1 == state['enable']
                cpu.reg_write(UC_ARM_REG_R0, state['run_result'] & 0xffffffff)
            cpu.reg_write(UC_ARM_REG_PC, cpu.reg_read(UC_ARM_REG_LR))
        elif not 0x602b1d3c <= a < 0x602b1df8:
            raise RuntimeError(f'Unexpected execution {a:08x}')

    c.hook_add(UC_HOOK_CODE, hook)
    cases = [('idle-disable', 0, 0, 0, 0), ('connected-disable', 0, 1, 0, 0),
             ('busy-clears', 0, 1, 3, 0), ('busy-persists', 0, 1, -1, 0),
             ('run-stop-failure', 0, 1, 0, -110), ('enable', 1, 1, -1, 0)]
    for name, enable, old, clear_after, result in cases:
        c.mem_write(dwc, bytes(0x5000))
        put(dwc + 0xcc, link)
        put(link, busy)
        put(dwc + 0xd0, ep0)
        put(dwc + 0xd4, ep1)
        put(dwc + 0x170, old)
        put(busy + 0x10, int(clear_after != 0))
        state.clear()
        state.update(enable=enable, clear_after=clear_after, run_result=result, yields=0, returned=False)
        events.clear()
        c.reg_write(UC_ARM_REG_R0, dwc + 0x150)
        c.reg_write(UC_ARM_REG_R1, enable)
        c.reg_write(UC_ARM_REG_SP, 0x20f000)
        c.reg_write(UC_ARM_REG_LR, done)
        c.emu_start(0x602b1d3c, 0xffffffff, count=10000)
        names = [e[0] for e in events]
        if name == 'busy-persists':
            assert not state['returned'] and state['bounded_observation_stop']
            assert 'stop-transfers' not in names and 'run-stop' not in names
        else:
            assert state['returned'] and c.reg_read(UC_ARM_REG_R0) == result & 0xffffffff
            teardown = [e[0] for e in events if e[0] in ('stop-transfers', 'disable-endpoint', 'disconnect-notify', 'run-stop')]
            expected = ['run-stop'] if enable else ['stop-transfers', 'disable-endpoint', 'disable-endpoint'] + (['disconnect-notify'] if old else []) + ['run-stop']
            assert teardown == expected, (name, teardown)
            assert state['yields'] == (3 if name == 'busy-clears' else 0)
        if not enable:
            assert struct.unpack('<I', c.mem_read(dwc + 0x170, 4))[0] == 0
        checks.append(dict(name=name, state=dict(state), events=list(events)))
    out.mkdir(parents=True, exist_ok=True)
    (out / 'manifest.json').write_text(json.dumps(dict(
        status='offline_original_pullup_control_flow_passed', kernel_sha256=KERNEL_SHA,
        checks=checks, limitations=['Hardware, callbacks, locks and scheduler are service doubles.',
                                   'Persistent busy observation is stopped by the harness, not a native timeout.',
                                   'No live EP0/IRQ/DMA drain or safe publication proof.']), indent=2) + '\n')
    print(f'{len(checks)} original pullup cases passed; hardware drain NOT proven')


if __name__ == '__main__':
    main()
