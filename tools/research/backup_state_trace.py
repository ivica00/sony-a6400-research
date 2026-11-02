"""Original backup dispatcher and read-only preset lookup windows.

These isolated, constructed mappings are not a loaded driver or runtime settings.
"""
import io
import json
import struct

import unicorn
from unicorn import arm_const as arm
from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.mount_evidence import checked_input, symbol
from tools.research.storage_trace import inspect_module, module_relocations
from tools.research.liro_startup_trace import BASE, STRINGS, STATE, run_slice
from tools.research.startup_trace import analyze, read_va

MODULE = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/backup.ko'
PRESETS = 'firmware/extracted_a6400/firmware.tar_unpacked/0110_backup/SYSASTRA-DSLR/DX2/'
PRESET_BASE = 0x1000000
RETURN = BASE + 0xf000
FUNCTIONS = ('Data_init', 'Data_GetFormatRevision', 'Data_SearchId', 'Data_GetDataPt',
             'Data_GetSize', 'Data_GetVmaxSize', 'Data_GetAttr')
LOCAL_RANGES = ((0x2f58, 0x2f98), (0x3004, 0x301c))


def checked_bk4(raw):
    """Independent structural/checksum preflight; never manufacture missing data."""
    if len(raw) < 0x100 or raw[12:16] != b'BK4\0':
        raise ValueError('Expected a complete BK4 header')
    subsystems, properties, data_offset, data_size, checksum = struct.unpack_from('<5I', raw, 0x10)
    if 0x100 + 6 * subsystems + 6 * properties > data_offset:
        raise ValueError('Preset tables overlap data or exceed its offset')
    if data_offset > len(raw) or data_size > len(raw) - data_offset:
        raise ValueError('Preset payload exceeds supplied bytes')
    end = data_offset + data_size
    if (sum(raw[:0x20]) + sum(raw[0x24:end])) & 0xffffffff != checksum:
        raise ValueError('Preset checksum mismatch')
    return {'subsystems': subsystems, 'properties': properties,
            'data_offset': data_offset, 'data_size': data_size, 'checksum': checksum}


def prepare(raw):
    elf = ELFFile(io.BytesIO(raw))
    if elf.elfclass != 32 or not elf.little_endian or elf['e_machine'] != 'EM_ARM' or elf['e_type'] != 'ET_REL':
        raise ValueError('Expected original ELF32 ARM module')
    index = next(i for i, s in enumerate(elf.iter_sections()) if s.name == '.text')
    code = bytearray(elf.get_section(index).data())
    relocations = module_relocations(elf)
    entries = {name: symbol(elf, name) for name in FUNCTIONS}
    ranges = [*LOCAL_RANGES, *((s['st_value'], s['st_value'] + s['st_size']) for s in entries.values())]
    # Include exactly the operation-8 table entry and the dispatcher windows.
    selected = [*ranges, (0x526c, 0x5270)]
    patched = []
    for (section_index, offset), relocation in relocations.items():
        if section_index != index or not any(begin <= offset < end for begin, end in selected):
            continue
        kind = relocation['type']
        if kind == 2 and relocation['symbol_section'] in ('.bss', '.rodata.str1.1', '.text'):
            placement = {'.bss': STATE, '.rodata.str1.1': STRINGS, '.text': BASE}[relocation['symbol_section']]
            value = placement + relocation['target_offset']
        elif kind == 28 and relocation['symbol_section'] == '.text':
            word = struct.unpack_from('<I', code, offset)[0]
            if word >> 24 != 0xeb:
                raise ValueError('Selected ARM call relocation is not an unconditional BL')
            addend = (word & 0xffffff) << 2
            if addend & 0x2000000:
                addend -= 0x4000000
            delta = relocation['symbol_value'] + addend - offset
            if delta % 4 or not -(1 << 25) <= delta < (1 << 25):
                raise ValueError('Selected local call is not representable')
            value = (word & 0xff000000) | ((delta >> 2) & 0xffffff)
        else:
            raise ValueError(f'Unsupported relocation in selected backup window: {relocation}')
        struct.pack_into('<I', code, offset, value)
        patched.append({'offset': offset, 'relocation': relocation, 'constructed_word': value})
    return elf, bytes(code), entries, ranges, patched


def call(code, entry, ranges, regions, argument):
    report, mu = run_slice(code, entry, ranges, {RETURN - BASE: 'isolated_function_return'},
                           {arm.UC_ARM_REG_R0: argument, arm.UC_ARM_REG_LR: RETURN}, regions, budget=1000)
    if report['status'] != 'isolated_function_return':
        raise ValueError(f'Backup window did not return: {report}')
    return report, mu


def main():
    inv = PROJECT_ROOT / 'artifacts/inventory'
    expected = {row['path']: row['sha256'] for row in json.loads((inv / 'elf-inventory.json').read_text(encoding='utf-8'))['entries']}
    preserved = {row['path']: row['sha256'] for row in json.loads((inv / 'baseline.json').read_text(encoding='utf-8'))['inputs']}
    raw = checked_input(PROJECT_ROOT, MODULE, expected[MODULE])
    elf, code, entries, ranges, patched = prepare(raw)
    shared = [(STRINGS, elf.get_section_by_name('.rodata.str1.1').data(), unicorn.UC_PROT_READ),
              (RETURN, bytes(4), unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)]
    # Request values copied from E0029, not answered or forwarded to a service.
    request = struct.pack('<16I', 8, 0, 3, 0x3e014d, 0, 0, 0x3e, 0x3e000b, 0x7feffd74, 0, 0, 0, 0, 0, 0, 0)
    dispatch, dispatch_mu = run_slice(code, 0x5204, [(0x5204, 0x5248), (0x559c, 0x55e0)],
                             {0x55e0: 'Backup_write_call_boundary'}, {arm.UC_ARM_REG_R0: STATE},
                             [(STATE, request, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)], budget=100)
    if dispatch['status'] != 'Backup_write_call_boundary':
        raise ValueError(f'Original dispatcher did not reach expected call: {dispatch}')
    if [dispatch['registers'][name] for name in ('r0', 'r1', 'r2')] != [0x3e, 0x3e000b, 0x7feffd74]:
        raise ValueError('Original dispatcher arguments differ from the blocked request')
    dispatch['message_unchanged'] = bytes(dispatch_mu.mem_read(STATE, len(request))) == request
    if not dispatch['message_unchanged']:
        raise ValueError('Dispatcher changed the message before the selected call boundary')
    app_path = MODULE.replace('kmod/backup.ko', 'bin/im.elf')
    app = checked_input(PROJECT_ROOT, app_path, expected[app_path])
    app_elf = ELFFile(io.BytesIO(app))
    producer_code = read_va(app_elf, app, 0x99c4, 0x2c)
    producer, producer_mu = run_slice(producer_code, 0, [(0, 0x14)], {0x14: 'Backup_write_call_boundary'},
                                      {}, thumb=True)
    if (producer['status'] != 'Backup_write_call_boundary'
            or producer['registers']['r0'] != 0x3e or producer['registers']['r1'] != 0x3e000b):
        raise ValueError('Original Thumb startup producer did not construct the expected request')
    producer['payload_word'] = struct.unpack('<I', producer_mu.mem_read(producer['registers']['r2'], 4))[0]
    if producer['payload_word'] != 1:
        raise ValueError('Original startup producer payload differs')
    cases = []
    for path in sorted(p for p in preserved if p.startswith(PRESETS) and p.endswith('.bin')):
        preset = checked_input(PROJECT_ROOT, path, preserved[path])
        header = checked_bk4(preset)
        initial = [(STATE, bytes(elf.get_section_by_name('.bss')['sh_size']), unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE),
                   (PRESET_BASE, preset, unicorn.UC_PROT_READ), *shared]
        init, mu = call(code, entries['Data_init']['st_value'], ranges, initial, PRESET_BASE)
        state = bytes(mu.mem_read(STATE, elf.get_section_by_name('.bss')['sh_size']))
        if init['registers']['r0'] != 0:
            raise ValueError('Original Data_init rejected an inventoried preset')
        regions = [(STATE, state, unicorn.UC_PROT_READ), (PRESET_BASE, preset, unicorn.UC_PROT_READ), *shared]
        properties = []
        for unit in (0x003e000b, 0x00fa007c, 0x00fa0076):
            lookup, _ = call(code, entries['Data_SearchId']['st_value'], ranges, regions, unit)
            descriptor = lookup['registers']['r0']
            item = {'unit': unit, 'lookup': lookup}
            if descriptor:
                if not PRESET_BASE <= descriptor <= PRESET_BASE + len(preset) - 6:
                    raise ValueError('Original lookup returned a descriptor outside the preset')
                item['descriptor_file_offset'] = descriptor - PRESET_BASE
                item['getters'] = {}
                for name in ('Data_GetDataPt', 'Data_GetSize', 'Data_GetVmaxSize', 'Data_GetAttr'):
                    result, _ = call(code, entries[name]['st_value'], ranges, regions, descriptor)
                    item['getters'][name] = result
                pointer = item['getters']['Data_GetDataPt']['registers']['r0']
                size = item['getters']['Data_GetSize']['registers']['r0']
                offset = pointer - PRESET_BASE
                if offset < 0 or offset > len(preset) or size > len(preset) - offset:
                    raise ValueError('Original data getter exceeds supplied preset')
                item.update(data_file_offset=offset, size=size,
                            data_preview_hex=preset[offset:offset + min(size, 16)].hex())
            properties.append(item)
        cases.append({'path': path, 'sha256': preserved[path], 'header': header,
                      'initialization': init, 'initialized_table_words': list(struct.unpack_from('<3I', state, 24)),
                      'properties': properties})
    report = {'module': {'path': MODULE, 'sha256': expected[MODULE]},
              'status': 'isolated_original_dispatch_and_preset_lookups',
              'selected_relocations': patched, 'dispatcher': dispatch, 'presets': cases,
              'startup_producer': {'path': app_path, 'sha256': expected[app_path],
                                   'linked_start': 0x99c4, 'slice': producer,
                                   'static': analyze(PROJECT_ROOT / app_path, [],
                                                     explicit_blocks=[('startup backup write', 0x99c5, 0x28)])},
              'static_functions': inspect_module(raw, [*FUNCTIONS, 'Backup_write', 'backup_osal_call_func',
                                                       'backup_init', 'backupfile_init', 'backup_osal_init']),
              'module_defaults': {name: elf.get_section((s := symbol(elf, name))['st_shndx']).data()[
                  s['st_value']:s['st_value'] + s['st_size']].hex()
                  for name in ('Backup_pri_file', 'Backup_sec_file', 'Backup_load', 'Backup_save')},
              'limitations': ['Constructed section, stack and preset mappings, provisional Cortex-A9.',
                              'Only selected ABS32 and same-section ARM CALL relocations; no module loader.',
                              'Read-only package presets are not current camera persistent state or a boot selection.',
                              'No kernel response, service reply, write, callback, file operation or device request supplied.',
                              'The startup backup guard remains unchanged; no framebuffer or camera UI.']}
    output = PROJECT_ROOT / 'artifacts/execution/package-h-backup-state.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output)
    print('dispatcher:', dispatch['status'], 'instructions:', len(dispatch['trace']))
    for case in cases:
        print(case['path'].rsplit('/', 1)[-1], [(hex(p['unit']), p.get('size'), p.get('data_preview_hex')) for p in case['properties']])


if __name__ == '__main__':
    main()
