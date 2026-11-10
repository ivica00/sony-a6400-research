"""Resolve and execute the original clear-configuration final gadget call.

The original unconfigure body calls gadget ops+0x18 with argument 1, not
pullup(0). This probe pins the vtable entries from dwc3_gadget_ops and runs
the original dwc3_gadget_ioctl for the relevant codes.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC

from tools.research.build_uvc_ptp_descriptor_candidate import ROOT, KERNEL, KERNEL_SHA

OPS = 0x603dfbf0
PULLUP = 0x602b1d3c
IOCTL = 0x602afcd8
DONE = 0x200000


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    out = parser.parse_args().output_dir.resolve()
    if not out.is_relative_to(ROOT / 'artifacts'):
        parser.error('Output must be under artifacts')
    out.mkdir(parents=True, exist_ok=False)
    raw = KERNEL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == KERNEL_SHA
    names = {s['address']: s['name'] for s in
             json.loads((ROOT / 'artifacts/analysis/uvc-portability-final-e0135/a6400-kallsyms-checked.json').read_text())['symbols']}
    offset = OPS - 0x60108000
    table = {i: struct.unpack_from('<I', raw, offset + 4 * i)[0] for i in range(10)}
    checks = []

    def check(name, value):
        if not value:
            raise AssertionError(name)
        checks.append(name)

    check('ops14-is-dwc3_gadget_pullup', table[5] == PULLUP and names.get(PULLUP) == 'dwc3_gadget_pullup')
    check('ops18-is-dwc3_gadget_ioctl', table[6] == IOCTL and names.get(IOCTL) == 'dwc3_gadget_ioctl')
    check('ops20-is-dwc3_gadget_start', names.get(table[8]) == 'dwc3_gadget_start')
    check('ops24-is-dwc3_gadget_stop', names.get(table[9]) == 'dwc3_gadget_stop')

    results = []
    for code, param, expected in [(1, 0, 0), (2, 0, 0), (3, 0, 0),
                                  (0, 0, -0x203), (4, 6, -0x203)]:
        cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        cpu.mem_map(0x60108000, (len(raw) + 4095) & ~4095)
        cpu.mem_write(0x60108000, raw)
        cpu.mem_map(0x200000, 0x10000)
        returned = []

        def hook(machine, address, size, unused):
            if address == DONE:
                returned.append(machine.reg_read(UC_ARM_REG_R0))
                machine.emu_stop()
            elif address < 0x602afcd8 or address >= 0x602afd5c:
                raise RuntimeError(f'Unexpected execution {address:08x}')

        cpu.hook_add(UC_HOOK_CODE, hook)
        cpu.reg_write(UC_ARM_REG_R0, 0x400000)
        cpu.reg_write(UC_ARM_REG_R1, code)
        cpu.reg_write(UC_ARM_REG_R2, param)
        cpu.reg_write(UC_ARM_REG_SP, 0x20f000)
        cpu.reg_write(UC_ARM_REG_LR, DONE)
        cpu.emu_start(IOCTL, 0xffffffff, count=200)
        check(f'ioctl-code{code}-param{param}-return', returned == [expected & 0xffffffff])
        results.append({'code': code, 'param': param, 'return': returned[0] if returned else None})

    report = {
        'status': 'offline_unconfigure_ioctl_resolved',
        'kernel_sha256': KERNEL_SHA,
        'ops_table': {str(i): hex(v) for i, v in table.items()},
        'ops_table_names': {str(i): names.get(v) for i, v in table.items()},
        'checks': checks,
        'cases': results,
        'finding': 'The original unconfigure calls dwc3_gadget_ioctl(gadget,1,0), which returns 0 without touching the UDC; it does not call pullup(0).',
        'limitations': [
            'Executes the original ioctl body with explicit stack/gadget fixtures; no hardware access.',
            'Proves control flow/return, not the real gadget teardown or the module pullup busy wait.',
        ],
    }
    (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f"{len(checks)} checks, {len(results)} ioctl cases passed; ops+0x18={names.get(table[6])}")
    print(report['finding'])


if __name__ == '__main__':
    main()
