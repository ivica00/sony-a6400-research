"""Read-only updater image-write evidence; never execute updater operations."""
import io
import json
import struct

from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.mount_evidence import checked_input
from tools.research.startup_trace import decode_block, plt_symbols, read_va


BODY_FUNCTIONS = (
    '_ZN7Updater20PartitionImageKeyTag7ExtractEPNS_15BodyInformationEPNS_20PackedFirmwareBufferERKNS_28NewFirmwareFileInformation_tE',
    '_ZN7Updater20NewFirmwareImageFile11extractFileEPNS_20PackedFirmwareBufferE',
    '_ZN7Updater20NewFirmwareImageFile16extractImageFileEPNS_20PackedFirmwareBufferE',
    '_ZN7Updater20PackedFirmwareBuffer19ReadDataWithoutCopyEPPhj',
    '_ZN7Updater20PackedFirmwareBuffer9SkipBlockEj')
COMMON_FUNCTIONS = ('_ZN7Updater11FileHandler4OpenEPKci',
                    '_ZN7Updater11FileHandler8WriteAllEPKhjPj')


def inspect_functions(data, names):
    elf = ELFFile(io.BytesIO(data))
    if elf.elfclass != 32 or not elf.little_endian or elf['e_machine'] != 'EM_ARM':
        raise ValueError('Updater evidence requires little-endian ELF32 ARM')
    symbols = elf.get_section_by_name('.dynsym')
    if symbols is None:
        raise ValueError('Updater evidence requires dynamic symbols')
    calls = plt_symbols(elf)
    functions = []
    for name in names:
        found = symbols.get_symbol_by_name(name)
        if not found or len(found) != 1 or not 0 < found[0]['st_size'] <= 8192:
            raise ValueError('Unique bounded updater function required: ' + name)
        entry = found[0]
        if entry['st_shndx'] == 'SHN_UNDEF' or entry['st_info']['type'] != 'STT_FUNC':
            raise ValueError('Updater function must be defined')
        rows = decode_block(elf, data, entry['st_value'], entry['st_size'], calls)
        literals = {row['literal_address'] for row in rows if 'literal_address' in row}
        for row in rows:
            row['kind'] = 'literal_data' if row['address'] & ~3 in literals else 'instruction_candidate'
            if row['kind'] == 'literal_data':
                for key in ('mnemonic', 'operands', 'call_target', 'call_symbol'):
                    row.pop(key, None)
        functions.append({'symbol': name, 'entry': entry['st_value'], 'size': entry['st_size'], 'rows': rows})
    return {'resolved_plt_entries': len(calls), 'functions': functions}


def symbol_vtable(data, name):
    elf = ELFFile(io.BytesIO(data))
    symbols = elf.get_section_by_name('.dynsym')
    found = symbols.get_symbol_by_name(name) if symbols else None
    if not found or len(found) != 1 or not 0 < found[0]['st_size'] <= 4096:
        raise ValueError('Unique bounded virtual table required')
    table = found[0]
    start, size = table['st_value'], table['st_size']
    rows = []
    for section in elf.iter_sections():
        if section['sh_type'] != 'SHT_REL':
            continue
        symbols = elf.get_section(section['sh_link'])
        for relocation in section.iter_relocations():
            address = relocation['r_offset']
            if start <= address < start + size:
                entry = symbols.get_symbol(relocation['r_info_sym'])
                raw = read_va(elf, data, address, 4)
                if raw is None:
                    raise ValueError('Virtual table relocation is not file-backed')
                rows.append({'address': address, 'offset': address - start,
                             'relocation_type': relocation['r_info_type'], 'symbol': entry.name,
                             'symbol_value': entry['st_value'], 'addend': struct.unpack('<I', raw)[0]})
    return {'symbol_address': start, 'size': size, 'relocations': sorted(rows, key=lambda row: row['address'])}


def image_vtable(data):
    return symbol_vtable(data, '_ZTVN7Updater20NewFirmwareImageFileE')


def virtual_slot(table, address_point, dispatch_offset):
    """Resolve an explicit table candidate; never claim its runtime selection."""
    offset = address_point + dispatch_offset
    if address_point < 0 or dispatch_offset < 0 or offset % 4 or offset + 4 > table['size']:
        raise ValueError('Virtual dispatch offset outside declared table')
    rows = [row for row in table['relocations'] if row['offset'] == offset]
    if len(rows) != 1 or rows[0]['relocation_type'] != 2 or rows[0]['addend'] != 0:
        raise ValueError('Unique unadjusted ARM ABS32 slot required')
    return {'table_offset': offset, 'dispatch_offset': dispatch_offset,
            'candidate_symbol': rows[0]['symbol'], 'symbol_value': rows[0]['symbol_value'],
            'runtime_dispatch_observed': False}


def main():
    folder = PROJECT_ROOT / 'artifacts/inventory'
    expected = {row['path']: row['sha256'] for row in
                json.loads((folder / 'baseline.json').read_text(encoding='utf-8'))['inputs']}
    root = 'firmware/extracted_a6400/updater.img_unpacked/'
    paths = {'body': root + 'bodylib/libupdaterbody.so',
             'common': root + 'usr/lib/libupdatercommon.so'}
    inputs = {key: checked_input(PROJECT_ROOT, path, expected[path]) for key, path in paths.items()}
    report = {'schema_version': 1, 'status': 'static_updater_write_evidence',
              'updater_executed': False, 'camera_fidelity_validated': False,
              'runtime_device_identity_selected': False,
              'sources': {key: {'path': path, 'sha256': expected[path]} for key, path in paths.items()},
              'body': inspect_functions(inputs['body'], BODY_FUNCTIONS),
              'common': inspect_functions(inputs['common'], COMMON_FUNCTIONS),
              'image_vtable': image_vtable(inputs['body']),
              'limitations': ['Static instructions and relocations do not establish completed writes.',
                              'The observed copy loop does not establish downstream driver transformations.',
                              'Boot state, mounts and writable /etc contents remain unknown.',
                              'No updater function, script, USB operation or host device write is executed.']}
    output = folder / 'updater-write-trace.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Recorded original image-copy loop, write wrapper and vtable evidence; updater not executed.')
    print(f'Report: {output}')


if __name__ == '__main__':
    main()
