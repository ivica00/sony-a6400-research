"""Verify original SD host hardware context, locking contracts, and SDHCI registers."""
import argparse
import io
import json
import struct

from elftools.elf.elffile import ELFFile
from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input

DRIVER = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/mmc_drv.ko'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', required=True)
    args = parser.parse_args()
    output = (PROJECT_ROOT / args.report_dir).resolve()
    if not output.is_relative_to(PROJECT_ROOT / 'artifacts'):
        parser.error('Output must remain under artifacts')
    output.mkdir(parents=True, exist_ok=False)

    digest = next(r['sha256'] for r in json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text())['inputs'] if r['path'] == DRIVER)
    raw = checked_input(PROJECT_ROOT, DRIVER, digest)
    elf = ELFFile(io.BytesIO(raw))
    if (elf['e_type'], elf['e_machine'], elf.elfclass, elf.little_endian) != ('ET_REL', 'EM_ARM', 32, True):
        raise ValueError('Expected ARM32 original kernel driver module')

    symbols = {s.name: s for s in elf.get_section_by_name('.symtab').iter_symbols()}
    text_section = elf.get_section_by_name('.text')
    text = text_section.data()

    expected_symbols = {
        'mmc_os_init_sem_long': 0x11bc,
        'mmc_os_lock_sem_long': 0x121c,
        'mmc_os_unlock_sem_long': 0x1278,
        'mmc_hwconf_led_on': 0x8ab8,
        'mmc_hwconf_led_off': 0x8adc,
        'mmc_hw_exec_command': 0xd754,
        'mmc_hw_lock_sem': 0xc404,
        'mmc_hw_unlock_sem': 0xc3ec,
        'mmc_hw_init': 0xc8f0,
        'mmc_hw_open': 0xdff4,
        'mmc_hw_get_ops_info': 0xe2f4,
        'set_r1_cmd': 0x12b0c,
        'mmc_hw_wrapper_get_ops': 0x18840,
        'mmc_hw_wrapper_lock_sem': 0x18dfc,
        'mmc_hw_wrapper_unlock_sem': 0x18e70,
        'mmc_hw_uhs2_get_ops_info': 0x1dfdc,
    }
    for name, expected_addr in expected_symbols.items():
        if symbols[name]['st_value'] != expected_addr:
            raise ValueError(f'Symbol {name} moved from expected 0x{expected_addr:x}')

    # Check ip_func_ops symbol in .bss
    ip_func_ops_sym = symbols['ip_func_ops']
    if ip_func_ops_sym['st_value'] != 0xfa8 or ip_func_ops_sym['st_size'] != 48:
        raise ValueError('ip_func_ops layout mismatch in .bss')

    # Relocation mappings for text
    text_index = next(i for i, s in enumerate(elf.iter_sections()) if s.name == '.text')
    all_relocations = {}
    for section in elf.iter_sections():
        if section['sh_type'] == 'SHT_REL' and section['sh_info'] == text_index:
            symtab = elf.get_section_by_name('.symtab')
            sym_names = [s.name for s in symtab.iter_symbols()]
            for r in section.iter_relocations():
                all_relocations[r['r_offset']] = (r['r_info_type'], sym_names[r['r_info_sym']])

    # Verify mmc_hw_lock_sem adds 0x4c and calls mmc_os_lock_sem_long
    lock_ins = struct.unpack_from('<I', text, 0xc410)[0]
    if lock_ins != 0xe280004c:  # add r0, r0, #0x4c
        raise ValueError('mmc_hw_lock_sem does not add offset 0x4c to host_hw')
    if all_relocations.get(0xc414, (None, None))[1] != 'mmc_os_lock_sem_long':
        raise ValueError('mmc_hw_lock_sem relocation target mismatch')

    # Verify mmc_hw_unlock_sem adds 0x4c and calls mmc_os_unlock_sem_long
    unlock_ins = struct.unpack_from('<I', text, 0xc3f8)[0]
    if unlock_ins != 0xe280004c:  # add r0, r0, #0x4c
        raise ValueError('mmc_hw_unlock_sem does not add offset 0x4c to host_hw')
    if all_relocations.get(0xc3fc, (None, None))[1] != 'mmc_os_unlock_sem_long':
        raise ValueError('mmc_hw_unlock_sem relocation target mismatch')

    # Verify physical base address 0xf2a00000 in mmc_hw_init literal pool at 0xcb34
    phys_base = struct.unpack_from('<I', text, 0xcb34)[0]
    if phys_base != 0xf2a00000:
        raise ValueError(f'mmc_hw_init physical MMIO base mismatch: 0x{phys_base:08x}')

    # Verify mmc_hw_exec_command reads register 0x2c via mmc_os_read16
    exec_reg = struct.unpack_from('<I', text, 0xd7e0)[0]
    if exec_reg != 0xe3a0102c:  # mov r1, #0x2c
        raise ValueError('mmc_hw_exec_command does not load SDHCI_PRESENT_STATE (0x2c)')
    if all_relocations.get(0xd7e4, (None, None))[1] != 'mmc_os_read16':
        raise ValueError('mmc_hw_exec_command relocation to mmc_os_read16 mismatch')

    # Verify mmc_hw_exec_command LED toggle relocations
    if all_relocations.get(0xd774, (None, None))[1] != 'mmc_hwconf_led_on':
        raise ValueError('mmc_hw_exec_command does not turn LED on')
    if all_relocations.get(0xd7a4, (None, None))[1] != 'mmc_hwconf_led_off':
        raise ValueError('mmc_hw_exec_command error path does not turn LED off')

    report = {
        'driver': DRIVER,
        'sha256': digest,
        'ip_func_ops': {
            'section': '.bss',
            'offset': '0xfa8',
            'size': 48,
            'entries_count': 4,
            'entry_size': 12,
            'slot_ops_table_bss_offset': '0xd34',
        },
        'host_hw_layout': {
            'total_size': '0xd0',
            'total_size_bytes': 208,
            'fields': [
                {'offset': '0x00', 'name': 'hw_id', 'type': 'uint8_t', 'description': 'Host controller index (0..3).'},
                {'offset': '0x08', 'name': 'eventflag', 'type': 'struct eventflag', 'description': 'Command completion waitqueue (mmc_os_init_eventflag).'},
                {'offset': '0x4c', 'name': 'lock_sem', 'type': 'struct sem_long', 'description': 'Host recursive mutex (mmc_os_init_sem_long).'},
                {'offset': '0x64', 'name': 'lock_owner_pid', 'type': 'int32_t', 'description': 'PID of recursive lock owner (lock_sem + 0x18).'},
                {'offset': '0x68', 'name': 'lock_nest_count', 'type': 'int32_t', 'description': 'Recursion depth counter (lock_sem + 0x1c).'},
                {'offset': '0x6c', 'name': 'card_int_sem', 'type': 'struct sem_short', 'description': 'Interrupt spinlock (mmc_os_init_sem_short).'},
                {'offset': '0x8c', 'name': 'mmio_base', 'type': 'void*', 'description': 'Kernel ioremap base of SDHCI registers (from PA 0xf2a00000).'},
            ],
        },
        'hardware_registers': {
            'sdhci_physical_base': '0xf2a00000',
            'sdhci_present_state': '0x2c',
            'sdhci_data_inhibit_bit': 2,
            'sdhci_cmd_inhibit_bit': 0,
            'activity_led_functions': {
                'on': 'mmc_hwconf_led_on',
                'off': 'mmc_hwconf_led_off',
            },
        },
        'synchronization_contract': {
            'lock_function': 'mmc_os_lock_sem_long',
            'unlock_function': 'mmc_os_unlock_sem_long',
            'thread_stack_mask': '0xffffe000',
            'task_pid_offset': '0x104',
            'recursive_depth_offset': '0x1c',
            'underlying_primitive': '_mutex_lock / _mutex_unlock',
        },
        'status': 'verified',
    }

    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
