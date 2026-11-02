"""Isolated LIRO entry/address windows; no module loading or kernel replies."""
import io
import json
import struct

import unicorn
from unicorn import arm_const as arm
from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.mount_evidence import checked_input
from tools.research.storage_trace import inspect_module, module_relocations
from tools.research.startup_trace import analyze
from src.a6400.execution.guest_memory import cstring_preview

BASE, DATA, STRINGS, STATE, STACK = 0x10000, 0x20000, 0x30000, 0x40000, 0x50000
SOURCE = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/liro.ko'


def run_slice(code, start, allowed, terminals, registers, regions=(), budget=100, *, thumb=False):
    """Explicit constructed mappings; stop before terminal calls, never answer them."""
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_THUMB if thumb else unicorn.UC_MODE_ARM)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
    mu.mem_map(BASE, (len(code) + 4095) & ~4095, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    mu.mem_write(BASE, code)
    mu.mem_map(STACK, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
    for address, content, permissions in regions:
        mu.mem_map(address, (len(content) + 4095) & ~4095, permissions)
        mu.mem_write(address, content)
    mu.reg_write(arm.UC_ARM_REG_CPSR, 0x30 if thumb else 0x10)
    mu.reg_write(arm.UC_ARM_REG_SP, STACK + 4096)
    mu.reg_write(arm.UC_ARM_REG_FP, STACK + 4096)
    for register, value in registers.items():
        mu.reg_write(register, value)
    report = {'status': 'running', 'trace': [], 'instruction_budget': budget, 'timeout_us': 100000,
              'kernel_responses_supplied': 0, 'host_commands_executed': 0}
    def hook(uc, address, size, _):
        offset = address - BASE
        if offset in terminals:
            report.update(status=terminals[offset], boundary_offset=offset)
            uc.emu_stop()
        elif not any(begin <= offset < end for begin, end in allowed):
            report.update(status='unexpected_control_flow', boundary_offset=offset)
            uc.emu_stop()
        else:
            report['trace'].append({'offset': offset, 'bytes': bytes(uc.mem_read(address, size)).hex()})
    mu.hook_add(unicorn.UC_HOOK_CODE, hook)
    try:
        mu.emu_start((BASE + start) | int(thumb), 0, count=budget, timeout=100000)
    except unicorn.UcError as error:
        report.update(status='execution_fault', error=str(error))
    if report['status'] == 'running':
        report['status'] = 'timeout' if mu.query(unicorn.UC_QUERY_TIMEOUT) else 'instruction_budget_exhausted'
    report['registers'] = {name: mu.reg_read(getattr(arm, 'UC_ARM_REG_' + name.upper()))
                           for name in ('r0', 'r1', 'r2', 'r3', 'r4', 'sp', 'lr', 'pc')}
    return report, mu


def main():
    inventory = json.loads((PROJECT_ROOT / 'artifacts/inventory/elf-inventory.json').read_text(encoding='utf-8'))
    expected = {entry['path']: entry['sha256'] for entry in inventory['entries']}
    raw = checked_input(PROJECT_ROOT, SOURCE, expected[SOURCE])
    elf = ELFFile(io.BytesIO(raw))
    init_index = next(index for index, section in enumerate(elf.iter_sections()) if section.name == '.init.text')
    code = bytearray(elf.get_section(init_index).data())
    relocations = module_relocations(elf)
    applied = []
    for offset, section_name, placement, target in ((0x538, '.data', DATA, 0x6c),
                                                  (0x120, '.rodata.str1.1', STRINGS, 0x308),
                                                  (0x124, '.rodata.str1.1', STRINGS, 0x336)):
        relocation = relocations[(init_index, offset)]
        if relocation['type'] != 2 or relocation['symbol_section'] != section_name or relocation['target_offset'] != target:
            raise ValueError('Selected LIRO literal relocation preimage mismatch')
        struct.pack_into('<I', code, offset, placement + target)
        applied.append({'offset': offset, 'relocation': relocation, 'constructed_address': placement + target})
    strings = elf.get_section_by_name('.rodata.str1.1').data()
    regions = [(DATA, elf.get_section_by_name('.data').data(), unicorn.UC_PROT_READ),
               (STRINGS, strings, unicorn.UC_PROT_READ), (STATE, bytes(4096), unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)]
    entry, mu = run_slice(bytes(code), 0x50c, [(0x50c, 0x52c)], {0x52c: 'udif_driver_register_boundary'}, {}, regions)
    pointer = struct.unpack('<I', mu.mem_read(entry['registers']['r0'], 4))[0]
    entry['constructed_driver_pointer'] = pointer
    if entry['status'] != 'udif_driver_register_boundary' or pointer != DATA + 0x6c or entry['registers']['r1'] != 1:
        raise ValueError('Original module entry did not establish registration arguments')
    cases = []
    for address in (0, 0x10000000, 0xc0000000):
        state = bytearray(4096)
        struct.pack_into('<I', state, 0x2c, address)
        selected_regions = [*regions[:2], (STATE, bytes(state), unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)]
        result, mu = run_slice(bytes(code), 0x50, [(0x50, 0x74)],
                               {0xf4: 'address_not_set_printk_boundary', 0x74: 'entry_point_printk_boundary'},
                               {arm.UC_ARM_REG_R4: STATE}, selected_regions)
        result.update(input_address=address, converted_address=struct.unpack('<I', mu.mem_read(STATE + 0x2c, 4))[0],
                      diagnostic_string=cstring_preview(mu, result['registers']['r0']))
        desired = 'address_not_set_printk_boundary' if address == 0 else 'entry_point_printk_boundary'
        if result['status'] != desired:
            raise ValueError('Original address-selection window did not reach its expected call boundary')
        cases.append(result)
    backup = SOURCE.replace('kmod/liro.ko', 'lib/libbackup.so')
    app = SOURCE.replace('kmod/liro.ko', 'bin/im.elf')
    for path in (backup, app):
        checked_input(PROJECT_ROOT, path, expected[path])
    report = {'module': {'path': SOURCE, 'sha256': expected[SOURCE]},
              'static_functions': inspect_module(raw, ['init_module', 'liro_init', 'tsk_entry']),
              'driver_data_relocations': [dict(section_offset=offset, **relocation)
                                          for (index, offset), relocation in relocations.items()
                                          if elf.get_section(index).name == '.data' and 0x6c <= offset < 0xf0],
              'selected_literal_relocations': applied, 'entry_window': entry, 'address_cases': cases,
              'backup_consumer': analyze(PROJECT_ROOT / backup, [], named_functions=['Backup_read', 'backup_sync_msg']),
              'parameter_producer': analyze(PROJECT_ROOT / app, [], explicit_blocks=[('LIRO parameter producer', 0xb315, 0xcc)]),
              'limitations': ['Explicit constructed section/stack/state addresses; selected ABS32 literals only, not a module loader.',
                              'Callback window begins after unexecuted earlier helpers; no completion or return is assumed for them.',
                              'Nonzero addresses are constructed controls, not identified camera addresses or supplied firmware.',
                              'No printk, UDIF registration, backup service, kernel thread, firmware entry or device operation executed.']}
    output = PROJECT_ROOT / 'artifacts/execution/package-h-liro-startup.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output)
    print('entry:', entry['status'], len(entry['trace']))
    for case in cases:
        print(hex(case['input_address']), case['status'], hex(case['converted_address']))


if __name__ == '__main__':
    main()
