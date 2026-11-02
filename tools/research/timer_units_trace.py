"""Original division-argument windows distinguish elapsed time from calendar data."""
import io
import json

import unicorn
from unicorn import arm_const as arm
from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.dependency_plan import analyze_function
from tools.research.mount_evidence import checked_input

BASE = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/'
CODE = 0x01000000


def divisor_window(text, start, end):
    if not 0 <= start < end < len(text) or start % 4 or end % 4 or end - start > 32:
        raise ValueError('Expected a bounded aligned argument window')
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
    mu.mem_map(CODE, (len(text) + 4095) & ~4095, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    mu.mem_write(CODE, text)
    mu.reg_write(arm.UC_ARM_REG_CPSR, 0x10)
    # Explicit sentinels: an unwritten register is not silently zero.
    mu.reg_write(arm.UC_ARM_REG_R2, 0xa5a5a5a5)
    mu.reg_write(arm.UC_ARM_REG_R3, 0x5a5a5a5a)
    report = {'status': 'running', 'start': start, 'end': end, 'trace': [], 'division_executed': False}

    def stop(reason, **details):
        report.update(status=reason, boundary={'pc': mu.reg_read(arm.UC_ARM_REG_PC), **details})
        mu.emu_stop()

    def code(uc, address, size, _):
        if address == CODE + end:
            stop('division_call_boundary')
        elif not CODE + start <= address < CODE + end:
            stop('unsupported_control_flow', address=address)
        else:
            report['trace'].append({'offset': address - CODE, 'bytes': bytes(uc.mem_read(address, size)).hex()})

    def read(uc, access, address, size, value, _):
        if not CODE <= address < address + size <= CODE + len(text):
            stop('unsupplied_data_read', address=address, size=size)

    def invalid(uc, access, address, size, value, _):
        stop('memory_boundary', address=address, size=size, access=access)
        return False

    mu.hook_add(unicorn.UC_HOOK_CODE, code)
    mu.hook_add(unicorn.UC_HOOK_MEM_READ, read)
    mu.hook_add(unicorn.UC_HOOK_MEM_INVALID, invalid)
    try:
        mu.emu_start(CODE + start, 0, count=16, timeout=1000000)
    except unicorn.UcError as error:
        if report['status'] == 'running':
            report.update(status='execution_fault', error=str(error))
    if report['status'] == 'running':
        report['status'] = 'timeout' if mu.query(unicorn.UC_QUERY_TIMEOUT) else 'instruction_limit'
    report['r2'] = mu.reg_read(arm.UC_ARM_REG_R2)
    report['r3'] = mu.reg_read(arm.UC_ARM_REG_R3)
    report['divisor_argument'] = report['r2'] | report['r3'] << 32
    return report


def main():
    rows = json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text(encoding='utf-8'))['inputs']
    hashes = {r['path']: r['sha256'] for r in rows}
    report = {'inputs': {}, 'functions': [], 'division_windows': [],
              'limitations': ['Selected original argument-construction slices, not executed clock/date services.',
                  'No timestamp, calendar value, physical frequency or image-count value is supplied.',
                  'Software units are inferred from matching conversion arithmetic and named output/use.']}
    for module, names in [('utimer.ko', ['utimer_drv_init']),
                          ('udate.ko', ['udate_get_localtime', 'udate_open_kif']),
                          ('dmm.ko', ['dmm_unit_ctrl_SetUnitAccInfo'])]:
        path = BASE + module
        raw = checked_input(PROJECT_ROOT, path, hashes[path])
        report['inputs'][path] = hashes[path]
        elf = ELFFile(io.BytesIO(raw))
        for name in names:
            result = analyze_function(raw, name)
            text = elf.get_section_by_name(result['section']).data()
            report['functions'].append({'module': module, **result})
            for row in result['instructions']:
                if row.get('call_symbol') == '__aeabi_uldivmod':
                    control = divisor_window(text, row['offset'] - 8, row['offset'])
                    report['division_windows'].append({'module': module, 'function': name,
                        'section': result['section'], **control})
    output = PROJECT_ROOT / 'artifacts/execution/timer-units-trace.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output)
    for control in report['division_windows']:
        print(control['module'], control['function'], hex(control['end']), control['status'], control['divisor_argument'])


if __name__ == '__main__':
    main()
