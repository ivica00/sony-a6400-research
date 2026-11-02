"""Original timer rollover helper and separate free-running counter boundary."""
import io
import json
import struct

import unicorn
from unicorn import arm_const as arm
from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.mount_evidence import checked_input, symbol

MODULE = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/utimer.ko'
CODE, STACK, STATE, RETURN = 0x10000, 0x20000, 0x30000, 0x40000


def execute(code, counter=0, previous=0):
    if not code or len(code) > 4096 or len(code) % 4:
        raise ValueError('Expected a bounded aligned ARM window')
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
    mu.mem_map(CODE, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    mu.mem_write(CODE, code)
    for address in (STACK, STATE):
        mu.mem_map(address, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
    mu.mem_map(RETURN, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    mu.mem_write(STATE, struct.pack('<I', previous))
    mu.reg_write(arm.UC_ARM_REG_CPSR, 0x10)
    mu.reg_write(arm.UC_ARM_REG_SP, STACK + 4096)
    mu.reg_write(arm.UC_ARM_REG_LR, RETURN)
    mu.reg_write(arm.UC_ARM_REG_R0, counter)
    mu.reg_write(arm.UC_ARM_REG_R1, STATE)
    result = {'status': 'running', 'counter_control': counter, 'previous_control': previous,
              'trace': [], 'hardware_values_supplied': 0}

    def stop(reason, **details):
        result.update(status=reason, boundary={'pc': mu.reg_read(arm.UC_ARM_REG_PC), **details})
        mu.emu_stop()

    def instruction(uc, address, size, _):
        if address == RETURN:
            stop('isolated_function_return')
        elif not CODE <= address < CODE + len(code):
            stop('unsupported_control_flow', target=address)
        else:
            result['trace'].append({'offset': address - CODE, 'bytes': bytes(uc.mem_read(address, size)).hex()})

    def invalid(uc, access, address, size, value, _):
        stop('unsupplied_memory_boundary', address=address, size=size, access=access)
        return False

    mu.hook_add(unicorn.UC_HOOK_CODE, instruction)
    mu.hook_add(unicorn.UC_HOOK_MEM_INVALID, invalid)
    try:
        mu.emu_start(CODE, 0, count=100, timeout=1000000)
    except unicorn.UcError as error:
        if result['status'] == 'running':
            result.update(status='execution_fault', error=str(error))
    if result['status'] == 'running':
        result['status'] = 'timeout' if mu.query(unicorn.UC_QUERY_TIMEOUT) else 'instruction_limit'
    result['r0'] = mu.reg_read(arm.UC_ARM_REG_R0)
    result['state_after'] = struct.unpack('<I', mu.mem_read(STATE, 4))[0]
    return result


def main():
    inputs = json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text(encoding='utf-8'))['inputs']
    expected = next(row['sha256'] for row in inputs if row['path'] == MODULE)
    raw = checked_input(PROJECT_ROOT, MODULE, expected)
    elf = ELFFile(io.BytesIO(raw))
    text = elf.get_section_by_name('.text').data()
    helper = text[0x1394:0x13d4]
    reader = symbol(elf, 'utimer_read_freerun')
    reader_code = text[reader['st_value']:reader['st_value'] + reader['st_size']]
    controls = [(0, 0), (0x80000000, 0), (0xffffffff, 0x80000000),
                (0, 0x80000000), (0x80000000, 1), (0, 0x80000001)]
    report = {'input': {'path': MODULE, 'sha256': expected},
              'helper_offset': 0x1394, 'helper_bytes': helper.hex(),
              'rollover_controls': [execute(helper, value, state) for value, state in controls],
              'freerun_offset': reader['st_value'], 'freerun_bytes': reader_code.hex(),
              'freerun_boundary': execute(reader_code),
              'limitations': ['Constructed counter/history inputs validate only the original helper arithmetic.',
                  'No live counter/history, clock origin, locks, IPC response or timer hardware value supplied.',
                  'Separate freerun MMIO remains unmapped; no original application progress claimed.']}
    output = PROJECT_ROOT / 'artifacts/execution/utimer-counter-trace.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output)
    for control in report['rollover_controls']:
        print(hex(control['counter_control']), hex(control['previous_control']), control['status'],
              hex(control['r0']), hex(control['state_after']))
    print(report['freerun_boundary']['status'], report['freerun_boundary'].get('boundary'))


if __name__ == '__main__':
    main()
