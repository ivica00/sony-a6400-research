"""Observe original timer register writes, stopping before unknown runtime state."""
import json
import struct

import unicorn
from unicorn import arm_const as arm

from project_paths import PROJECT_ROOT
from tools.research.dmm_timer_setup import descriptors, execute_setup, TABLE
from tools.research.dmm_runtime_trace import KERNEL, KERNEL_BASE
from tools.research.mount_evidence import checked_input
from tools.research.boot_mount_trace import parse_init_mounts, INIT_BIN

ENTRY, BOUNDARY = 0x60124cec, 0x60124d4c


def observe_programming(raw, pointers):
    if len(pointers) != 4 or len(set(pointers)) != 4 or any(p & 3 or p <= 0 for p in pointers):
        raise ValueError('Expected four distinct aligned timer pointers')
    if (not KERNEL_BASE <= ENTRY < BOUNDARY <= KERNEL_BASE + len(raw)
            or TABLE + 64 > KERNEL_BASE + len(raw)):
        raise ValueError('Programming window escapes kernel input')
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
    mu.mem_map(KERNEL_BASE, (len(raw) + 4095) & ~4095, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    mu.mem_write(KERNEL_BASE, raw)
    # Explicit composed state from the original pointer-store slices.
    for cpu, pointer in enumerate(pointers):
        mu.mem_write(TABLE + cpu * 20, struct.pack('<I', pointer))
    for page in sorted({p & ~4095 for p in pointers}):
        mu.mem_map(page, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
    stack = 0x08000000
    mu.mem_map(stack, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
    mu.reg_write(arm.UC_ARM_REG_CPSR, 0x13)  # Constructed supervisor mode for CPSID.
    mu.reg_write(arm.UC_ARM_REG_SP, stack + 4096)
    result = {'status': 'running', 'trace': [], 'register_writes': [], 'hardware_reads_supplied': 0,
              'selected_pointers': pointers}

    def stop(reason, **details):
        result.update(status=reason, boundary={'pc': mu.reg_read(arm.UC_ARM_REG_PC), **details})
        mu.emu_stop()

    def code(uc, address, size, _):
        if address == BOUNDARY:
            stop('post_programming_runtime_boundary')
        elif not ENTRY <= address < BOUNDARY:
            stop('unsupported_control_flow', target=address)
        else:
            result['trace'].append({'pc': address, 'bytes': bytes(uc.mem_read(address, size)).hex()})

    def read(uc, access, address, size, value, _):
        if stack <= address and address + size <= stack + 4096:
            return
        if address == 0x60124d74 and size == 4:
            return
        if size == 4 and address in {TABLE + cpu * 20 for cpu in range(4)}:
            return
        stop('unsupplied_data_read', address=address, size=size)

    def write(uc, access, address, size, value, _):
        if stack <= address and address + size <= stack + 4096:
            return
        for cpu, pointer in enumerate(pointers):
            if size == 4 and address in (pointer, pointer + 4):
                result['register_writes'].append({'cpu': cpu, 'address': address,
                    'offset': address - pointer, 'value': value, 'pc': mu.reg_read(arm.UC_ARM_REG_PC)})
                return
        stop('unsupported_data_write', address=address, size=size)

    def invalid(uc, access, address, size, value, _):
        stop('memory_boundary', address=address, size=size, access=access)
        return False

    mu.hook_add(unicorn.UC_HOOK_CODE, code)
    mu.hook_add(unicorn.UC_HOOK_MEM_READ, read)
    mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, write)
    mu.hook_add(unicorn.UC_HOOK_MEM_INVALID, invalid)
    try:
        mu.emu_start(ENTRY, 0, count=200, timeout=1000000)
    except unicorn.UcError as error:
        if result['status'] == 'running':
            result.update(status='execution_fault', error=str(error))
    if result['status'] == 'running':
        result['status'] = 'timeout' if mu.query(unicorn.UC_QUERY_TIMEOUT) else 'instruction_limit'
    return result


def main():
    inputs = json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text(encoding='utf-8'))['inputs']
    hashes = {row['path']: row['sha256'] for row in inputs}
    raw = checked_input(PROJECT_ROOT, KERNEL, hashes[KERNEL])
    init = INIT_BIN.relative_to(PROJECT_ROOT).as_posix()
    checked_input(PROJECT_ROOT, init, hashes[init])
    description = descriptors(raw)
    setup = [execute_setup(raw, description['device'], cpu) for cpu in range(4)]
    if any(s['status'] != 'runtime_pointer_store_completed' or len(s['writes']) != 1 for s in setup):
        raise ValueError('Original pointer-store slices did not complete')
    pointers = [s['writes'][0]['value'] for s in setup]
    report = {'inputs': {KERNEL: hashes[KERNEL], init: hashes[init]},
              'programming': observe_programming(raw, pointers),
              'setting_mount': [m for m in parse_init_mounts()[0] if m['target'] == '/setting'],
              'setting_partition_images': [r for r in inputs if r['path'].endswith('/dev/nflasha2')],
              'limitations': ['Composed original slices with selected static descriptors and supervisor stack.',
                  'Register stores are observed bus requests; their device effects and clock progression are not modeled.',
                  'Unknown MMIO reads remain guarded even when their host storage has been mapped.',
                  'No full boot, callbacks, interrupts, elapsed-time policy or timer response is supplied.']}
    output = PROJECT_ROOT / 'artifacts/execution/dmm-timer-program.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output)
    print(report['programming']['status'], len(report['programming']['register_writes']), 'register stores')
    print('setting mount:', report['setting_mount'])


if __name__ == '__main__':
    main()
