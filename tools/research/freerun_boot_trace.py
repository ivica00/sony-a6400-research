"""Original freerun setup: unknown-state guard and explicitly labeled controls."""
import json
import struct

import unicorn
from unicorn import arm_const as arm

from project_paths import PROJECT_ROOT
from tools.research.dmm_runtime_trace import KERNEL, KERNEL_BASE
from tools.research.mount_evidence import checked_input

ENTRY, LIMIT, REGISTER = 0x6011fdec, 0x6011fe1c, 0xf2403100
RETURN = 0x09000000


def execute(raw, control=None):
    if not KERNEL_BASE <= ENTRY < LIMIT + 8 <= KERNEL_BASE + len(raw):
        raise ValueError('Freerun window escapes preserved kernel')
    if control is not None and not 0 <= control <= 0xffffffff:
        raise ValueError('Control must be an explicit ARM32 value')
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
    mu.mem_map(KERNEL_BASE, (len(raw) + 4095) & ~4095, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    mu.mem_write(KERNEL_BASE, raw)
    mu.mem_map(REGISTER & ~4095, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
    mu.mem_map(RETURN, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    if control is not None:
        mu.mem_write(REGISTER, struct.pack('<I', control))
    mu.reg_write(arm.UC_ARM_REG_CPSR, 0x10)
    mu.reg_write(arm.UC_ARM_REG_LR, RETURN)
    report = {'status': 'running', 'selected_control': control, 'writes': [], 'trace': [],
              'counter_values_supplied': 0}

    def stop(reason, **details):
        report.update(status=reason, boundary={'pc': mu.reg_read(arm.UC_ARM_REG_PC), **details})
        mu.emu_stop()

    def code(uc, address, size, _):
        if address == RETURN:
            stop('isolated_function_return')
        elif not ENTRY <= address < LIMIT:
            stop('unsupported_control_flow', target=address)
        else:
            report['trace'].append({'pc': address, 'bytes': bytes(uc.mem_read(address, size)).hex()})

    def read(uc, access, address, size, value, _):
        if address in (LIMIT, LIMIT + 4) and size == 4:
            return
        if address == REGISTER and size == 4 and control is not None:
            return
        stop('unsupplied_runtime_read', address=address, size=size)

    def write(uc, access, address, size, value, _):
        if size == 4 and address in (REGISTER, REGISTER + 4):
            report['writes'].append({'pc': mu.reg_read(arm.UC_ARM_REG_PC), 'address': address, 'value': value})
        else:
            stop('unsupported_write', address=address, size=size)

    def invalid(uc, access, address, size, value, _):
        stop('memory_boundary', address=address, size=size, access=access)
        return False

    mu.hook_add(unicorn.UC_HOOK_CODE, code)
    mu.hook_add(unicorn.UC_HOOK_MEM_READ, read)
    mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, write)
    mu.hook_add(unicorn.UC_HOOK_MEM_INVALID, invalid)
    try:
        mu.emu_start(ENTRY, 0, count=100, timeout=1000000)
    except unicorn.UcError as error:
        if report['status'] == 'running':
            report.update(status='execution_fault', error=str(error))
    if report['status'] == 'running':
        report['status'] = 'timeout' if mu.query(unicorn.UC_QUERY_TIMEOUT) else 'instruction_limit'
    return report


def main():
    rows = json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text(encoding='utf-8'))['inputs']
    digest = next(row['sha256'] for row in rows if row['path'] == KERNEL)
    raw = checked_input(PROJECT_ROOT, KERNEL, digest)
    report = {'input': {'path': KERNEL, 'sha256': digest},
              'window_address': ENTRY, 'window_bytes': raw[ENTRY - KERNEL_BASE:LIMIT + 8 - KERNEL_BASE].hex(),
              'unknown_state': execute(raw), 'explicit_controls': [execute(raw, value) for value in (0, 0x1031)],
              'limitations': ['Literal/reference-derived routine identity; not a recovered kernel function symbol.',
                  'Constructed initial control values demonstrate branches, not reset state or an actual boot.',
                  'Register effects, elapsed time, clock frequency and counter values remain unmodeled.',
                  'No actual firmware service reply, main-process advancement or camera operation.']}
    output = PROJECT_ROOT / 'artifacts/execution/freerun-boot-trace.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output)
    print('unknown:', report['unknown_state']['status'], report['unknown_state'].get('boundary'))
    for control in report['explicit_controls']:
        print(hex(control['selected_control']), control['status'], control['writes'])


if __name__ == '__main__':
    main()
