"""Observe original DMM prerequisites without supplying timer/log runtime state."""
import json
import struct

import capstone
import unicorn
from unicorn import arm_const as arm

from project_paths import PROJECT_ROOT
from tools.research.mount_evidence import checked_input
from tools.research.storage_trace import inspect_module
from tools.research.entropy_trace import KERNEL, KERNEL_BASE
from tools.research.boot_mount_trace import parse_init_mounts, INIT_BIN

LOG_MODULE = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/osal_ulogio.ko'
TIMER_NAME = b'hwtimer_read_clock_cpu\0'


def export_address(raw, name):
    """Require a unique name and an aligned value/name kernel export pair."""
    offsets = []
    start = 0
    while (offset := raw.find(name, start)) >= 0:
        if offset == 0 or raw[offset - 1] == 0:
            offsets.append(offset)
        start = offset + 1
    if len(offsets) != 1:
        raise ValueError('Kernel export name is missing or ambiguous')
    offset = offsets[0]
    pointer = struct.pack('<I', KERNEL_BASE + offset)
    candidates = []
    for index in range(4, len(raw) - 3, 4):
        if raw[index:index + 4] == pointer:
            address = struct.unpack_from('<I', raw, index - 4)[0]
            if KERNEL_BASE <= address < KERNEL_BASE + len(raw) and address % 4 == 0:
                candidates.append({'address': address, 'pair_file_offset': index - 4,
                                   'name_file_offset': offset})
    if len(candidates) != 1:
        raise ValueError('Kernel export pair is missing or ambiguous')
    return candidates[0]


def timer_window(raw, entry, cpu=0, selected_pointer=None):
    """Execute only the observed 56-byte function; unknown data reads stop.

    The sole allowed image data read is its own final literal word. Other
    image bytes are not assumed initialized runtime state just because they
    happen to be present (often zero) in the preserved kernel container.
    """
    if not 0 <= entry - KERNEL_BASE <= len(raw) - 60:
        raise ValueError('Timer window escapes supplied image')
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
    mu.mem_map(KERNEL_BASE, (len(raw) + 4095) & ~4095, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    mu.mem_write(KERNEL_BASE, raw)
    slot = 0x604be020 + cpu * 20
    if selected_pointer is not None:
        if cpu not in range(4) or not 0 <= slot - KERNEL_BASE <= len(raw) - 4:
            raise ValueError('Selected timer slot escapes supplied image')
        mu.mem_write(slot, struct.pack('<I', selected_pointer))
    stack, returned = 0x08000000, 0x09000000
    mu.mem_map(stack, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
    mu.mem_map(returned, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    mu.reg_write(arm.UC_ARM_REG_CPSR, 0x10)
    mu.reg_write(arm.UC_ARM_REG_R0, cpu)
    mu.reg_write(arm.UC_ARM_REG_SP, stack + 4096)
    mu.reg_write(arm.UC_ARM_REG_LR, returned)
    result = {'status': 'running', 'cpu': cpu, 'trace': [], 'responses_supplied': 0}
    if selected_pointer is not None:
        result['selected_pointer_control'] = {'slot': slot, 'value': selected_pointer,
            'scope': 'Explicit composed slice state, not an initialized kernel or observed camera state'}

    def stop(reason, **details):
        result.update(status=reason, boundary={'pc': mu.reg_read(arm.UC_ARM_REG_PC), **details})
        mu.emu_stop()

    def code(uc, address, size, _):
        if address == returned:
            stop('isolated_function_return')
        elif not entry <= address < entry + 56:
            stop('unsupported_control_flow', target=address)
        else:
            result['trace'].append({'pc': address, 'bytes': bytes(uc.mem_read(address, size)).hex()})

    def read(uc, access, address, size, value, _):
        if entry + 56 <= address and address + size <= entry + 60:
            return
        if stack <= address and address + size <= stack + 4096:
            return
        if selected_pointer is not None and address == slot and size == 4:
            return
        stop('unsupplied_timer_runtime_read', address=address, size=size)

    def invalid(uc, access, address, size, value, _):
        stop('unmapped_memory_boundary', address=address, size=size, access=access)
        return False

    mu.hook_add(unicorn.UC_HOOK_CODE, code)
    mu.hook_add(unicorn.UC_HOOK_MEM_READ, read)
    mu.hook_add(unicorn.UC_HOOK_MEM_INVALID, invalid)
    try:
        mu.emu_start(entry, 0, count=100, timeout=1000000)
    except unicorn.UcError as error:
        if result['status'] == 'running':
            result.update(status='execution_fault', error=str(error))
    if result['status'] == 'running':
        result['status'] = 'timeout' if mu.query(unicorn.UC_QUERY_TIMEOUT) else 'instruction_limit'
    return result


def main():
    inventory = json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text(encoding='utf-8'))
    hashes = {row['path']: row['sha256'] for row in inventory['inputs']}
    raw = checked_input(PROJECT_ROOT, KERNEL, hashes[KERNEL])
    log = checked_input(PROJECT_ROOT, LOG_MODULE, hashes[LOG_MODULE])
    init_path = INIT_BIN.relative_to(PROJECT_ROOT).as_posix()
    checked_input(PROJECT_ROOT, init_path, hashes[init_path])
    exported = export_address(raw, TIMER_NAME)
    entry = exported['address']
    decoder = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    block = raw[entry - KERNEL_BASE:entry - KERNEL_BASE + 60]
    report = {'inputs': {p: hashes[p] for p in (KERNEL, LOG_MODULE, init_path)},
              'timer_export': exported,
              'timer_instructions': [{'pc': i.address, 'bytes': i.bytes.hex(), 'mnemonic': i.mnemonic,
                                      'operands': i.op_str} for i in decoder.disasm(block[:56], entry)],
              'timer_literal': struct.unpack_from('<I', block, 56)[0],
              'timer_attempt': timer_window(raw, entry),
              'log_functions': inspect_module(log, ['ulogio_sync_api_handler', 'ulogio_get_logaddr',
                  'ulogio_lbm_lookup_table_find', 'ulogio_lbm_init', 'ulogio_init', 'ulogio_module_init']),
              'log_boot_options': [d for d in parse_init_mounts()[2] if 'osal_ulogio.ko' in d['module']],
              'inventoried_log_configs': [p for p in hashes if p.endswith('/ulogio.bin')],
              'limits': ['Constructed stack and provisional CPU; no kernel boot, timer state or IPC responses.',
                         'Static kernel data bytes are not accepted as initialized timer pointers.',
                         'Log-service instruction evidence does not supply its live lookup table.']}
    output = PROJECT_ROOT / 'artifacts/execution/dmm-runtime-trace.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output)
    print(report['timer_attempt']['status'], report['timer_attempt'].get('boundary'))
    for function in report['log_functions']:
        print(function['name'], 'calls:', [r['call_symbol'] for r in function['rows'] if r.get('call_symbol')])


if __name__ == '__main__':
    main()
