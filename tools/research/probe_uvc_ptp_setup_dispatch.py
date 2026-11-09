"""Original g_setup and class/interface dispatch with explicit driver doubles."""
import argparse, hashlib, json, struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
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
    gc, gadget, request, node, driver, callback, done = [0x100000 + i * 0x1000 for i in range(7)]
    state, checks = {}, []

    def put(a, v):
        c.mem_write(a, struct.pack('<I', v & 0xffffffff))

    def hook(cpu, a, size, unused):
        if a == done:
            state['returned'] = True
            cpu.emu_stop()
            return
        if a == 0x6029b1a0:
            assert cpu.reg_read(UC_ARM_REG_R0) == gadget + 0x30
            result = gc
        elif a == 0x602bd450:
            result = 0  # Explicit GCW state fixture, avoids alternate descriptor lookup.
        elif a == callback:
            assert cpu.reg_read(UC_ARM_REG_R0) == driver
            assert cpu.reg_read(UC_ARM_REG_R1) == request
            assert cpu.reg_read(UC_ARM_REG_R2) == gadget
            state['events'].append('driver-setup-double')
            result = state['callback_result']
        elif a == 0x602b8f70:
            assert cpu.reg_read(UC_ARM_REG_R0) == gc
            state['events'].append('clear-halt-double')
            result = 0
        elif 0x602b8328 <= a < 0x602b8364 or 0x602b94a4 <= a < 0x602ba450:
            return
        else:
            raise RuntimeError(f'Unexpected execution {a:08x}')
        cpu.reg_write(UC_ARM_REG_R0, result & 0xffffffff)
        cpu.reg_write(UC_ARM_REG_PC, cpu.reg_read(UC_ARM_REG_LR))

    c.hook_add(UC_HOOK_CODE, hook)
    cases = [('inactive', 0, 2, 1, 0, 0, []),
             ('accepted', 4, 2, 1, 0, 0, ['driver-setup-double', 'clear-halt-double']),
             ('callback-one', 4, 2, 1, 1, -22, ['driver-setup-double']),
             ('callback-error', 4, 2, 1, -95, -22, ['driver-setup-double']),
             ('other-interface', 4, 2, 9, 0, -22, []),
             ('other-config', 4, 3, 1, 0, -22, [])]
    for name, flags, config, interface, response, expected, events in cases:
        c.mem_write(gc, bytes(0x7000))
        put(gc + 4, gadget)
        put(gc + 0x68, flags)
        c.mem_write(gc + 0x74, bytes([2]))
        put(gc + 0x78, node + 4)
        put(node, driver)
        put(node + 4, gc + 0x78)
        c.mem_write(driver + 4, bytes([config, interface]))
        put(driver + 0x2c, callback)
        c.mem_write(request, bytes([0x21, 1, 0, 0, 1, 0, 0, 0]))
        state.clear()
        state.update(callback_result=response, events=[], returned=False)
        c.reg_write(UC_ARM_REG_R0, gadget)
        c.reg_write(UC_ARM_REG_R1, request)
        c.reg_write(UC_ARM_REG_SP, 0x20f000)
        c.reg_write(UC_ARM_REG_LR, done)
        c.emu_start(0x602b8328, 0xffffffff, count=1000)
        assert state['returned'] and c.reg_read(UC_ARM_REG_R0) == expected & 0xffffffff, name
        assert state['events'] == events, (name, state)
        checks.append(dict(name=name, result=expected, events=list(events)))
    out.mkdir(parents=True, exist_ok=True)
    (out / 'manifest.json').write_text(json.dumps(dict(
        status='offline_original_setup_dispatch_passed', kernel_sha256=KERNEL_SHA, checks=checks,
        limitations=['Driver/list/request and GCW state are explicit fixtures.',
                     'Driver setup, clear-halt and device-data lookup are service doubles.',
                     'No real driver callback, EP0 queue/completion, IRQ or DMA drain executed.']), indent=2) + '\n')
    print(f'{len(checks)} original setup dispatch cases passed')


if __name__ == '__main__':
    main()
