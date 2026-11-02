"""Recover static mount/device candidates without selecting runtime identities."""
import hashlib
import io
import json
import struct
from pathlib import Path

from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.startup_trace import decode_block, plt_symbols, read_va


def checked_input(root, relative, expected):
    path = (root / relative).resolve()
    if not path.is_relative_to((root / 'firmware').resolve()):
        raise ValueError('Evidence input escapes firmware directory')
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise ValueError('Evidence input hash mismatch')
    return data


def terminated_ascii(data, offset):
    if not 0 <= offset < len(data):
        raise ValueError('Evidence string offset outside source')
    end = data.find(b'\0', offset, min(offset + 1024, len(data)))
    if end < 0:
        raise ValueError('Evidence string is not bounded/terminated')
    try:
        return data[offset:end].decode('ascii')
    except UnicodeDecodeError as error:
        raise ValueError('Non-ASCII evidence string') from error


def mount_rows(raw, string):
    if not raw or len(raw) % 20:
        raise ValueError('Invalid mount table record size')
    rows = []
    for offset in range(0, len(raw), 20):
        source, target, filesystem, flags, options = struct.unpack_from('<5I', raw, offset)
        rows.append({'record_offset': offset, 'source': string(source),
                     'target': string(target), 'filesystem': string(filesystem),
                     'flags': flags, 'options': string(options) if options else None})
    return rows


def device_rows(raw, names):
    """Observed 12-byte layout; field semantics remain a documented inference."""
    if not raw or len(raw) % 12 or set(names) != set(range(0, len(raw), 12)):
        raise ValueError('Incomplete device table pointer relocations')
    rows = []
    for offset in range(0, len(raw), 12):
        pointer_addend, kind, major, first_minor, count = struct.unpack_from('<I4H', raw, offset)
        if kind not in (0, 1) or not count or first_minor + count > 65536:
            raise ValueError('Unsupported device table record')
        rows.append({'record_offset': offset, 'name': names[offset],
                     'pointer_addend': pointer_addend,
                     'raw_halfwords': [kind, major, first_minor, count],
                     'inferred_kind': 'block' if kind else 'character',
                     'inferred_major': major, 'inferred_first_minor': first_minor,
                     'inferred_count': count})
    return rows


def unsupplied_mount_roots(rows, supplied=('/usr', '/rootfs')):
    """Conservative candidates, including conditional attempts; no success claim."""
    roots = set()
    for row in rows:
        target = row['target']
        if not target.startswith('/') or '..' in target.split('/'):
            raise ValueError('Invalid absolute mount target')
        target = target.rstrip('/') or '/'
        if target not in supplied:
            roots.add(target)
    return sorted(roots)


def symbol(elf, name):
    table = elf.get_section_by_name('.symtab')
    found = table.get_symbol_by_name(name) if table else None
    if not found or len(found) != 1:
        raise ValueError(f'Unique evidence symbol required: {name}')
    return found[0]


def inspect_init(data):
    elf = ELFFile(io.BytesIO(data))
    if elf.elfclass != 32 or not elf.little_endian or elf['e_machine'] != 'EM_ARM':
        raise ValueError('Expected little-endian ELF32 ARM init')
    table = symbol(elf, 'mnts')
    raw = read_va(elf, data, table['st_value'], table['st_size'])
    if raw is None:
        raise ValueError('Mount table is not file-backed')
    def string(address):
        # Read only file-backed bytes, including a mandatory terminator.
        value = bytearray()
        for index in range(1024):
            byte = read_va(elf, data, address + index, 1)
            if byte is None:
                raise ValueError('Mount string escapes file-backed memory')
            value.extend(byte)
            if byte == b'\0':
                return terminated_ascii(value, 0)
        raise ValueError('Mount string exceeds evidence bound')
    rows = mount_rows(raw, string)
    for row in rows:
        row['address'] = table['st_value'] + row['record_offset']
    main = symbol(elf, 'main')
    helper = symbol(elf, 'mount_partition')
    return {'mount_table_address': table['st_value'], 'mounts': rows,
            'main_mount_sequence': decode_block(elf, data, main['st_value'],
                                                 min(main['st_size'], 0x17a), plt_symbols(elf)),
            'mount_helper': decode_block(elf, data, helper['st_value'],
                                          min(helper['st_size'], 0x13c), plt_symbols(elf))}


def inspect_device_table(data):
    elf = ELFFile(io.BytesIO(data))
    if elf.elfclass != 32 or not elf.little_endian or elf['e_machine'] != 'EM_ARM' or elf['e_type'] != 'ET_REL':
        raise ValueError('Expected little-endian ELF32 ARM relocatable device module')
    table = symbol(elf, 'udif_devnodes')
    section_index = table['st_shndx']
    section = elf.get_section(section_index)
    start, size = table['st_value'], table['st_size']
    raw = section.data()[start:start + size]
    if len(raw) != size:
        raise ValueError('Truncated device table')
    names = {}
    for relocations in elf.iter_sections():
        if relocations['sh_type'] != 'SHT_REL' or relocations['sh_info'] != section_index:
            continue
        symbols = elf.get_section(relocations['sh_link'])
        for relocation in relocations.iter_relocations():
            offset = relocation['r_offset'] - start
            if not 0 <= offset < size:
                continue
            if offset % 12 or relocation['r_info_type'] != 2 or offset in names:
                raise ValueError('Unsupported device name relocation')
            name_symbol = symbols.get_symbol(relocation['r_info_sym'])
            if not isinstance(name_symbol['st_shndx'], int):
                raise ValueError('Device name relocation is not section-backed')
            strings = elf.get_section(name_symbol['st_shndx']).data()
            addend = struct.unpack_from('<I', raw, offset)[0]
            names[offset] = terminated_ascii(strings, name_symbol['st_value'] + addend)
    return {'table_section': section.name, 'table_file_offset': section['sh_offset'] + start,
            'record_size': 12, 'field_semantics': 'inferred; not a runtime device attestation',
            'devices': device_rows(raw, names)}


def main():
    folder = PROJECT_ROOT / 'artifacts/inventory'
    baseline = json.loads((folder / 'baseline.json').read_text(encoding='utf-8'))
    expected = {item['path']: item['sha256'] for item in baseline['inputs']}
    base = 'firmware/extracted_a6400/firmware.tar_unpacked/'
    paths = {'init': base + '0700_part_image/dev/nflasha7_unpacked/sbin/init',
             'initrd_init': base + '0700_part_image/dev/nflasha3_unpacked/initrd.img_unpacked/sbin/init',
             'device_table': base + '0700_part_image/dev/nflasha3_unpacked/initrd.img_unpacked/kmod/devno.ko',
             'mount_configuration': base + '0100_config/mount.conf'}
    inputs = {key: checked_input(PROJECT_ROOT, path, expected[path]) for key, path in paths.items()}
    report = {'schema_version': 1, 'status': 'static_candidates_only',
              'camera_fidelity_validated': False, 'runtime_device_identity_selected': False,
              'sources': {key: {'path': path, 'sha256': expected[path]} for key, path in paths.items()},
              'init_copies_identical': inputs['init'] == inputs['initrd_init'],
              'init': inspect_init(inputs['init']),
              'device_table': inspect_device_table(inputs['device_table']),
              'mount_configuration': inputs['mount_configuration'].decode('ascii'),
              'limitations': ['Static tables and branches do not establish mount success or the observed boot mode.',
                              'Compressed and direct device paths differ; do not choose st_dev from a filename.',
                              'No new execution policy, device response, host mount or camera operation is supplied.']}
    output = folder / 'mount-evidence.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'Recovered {len(report["init"]["mounts"])} mount records and '
          f'{len(report["device_table"]["devices"])} device records; runtime identity remains unselected.')
    print(f'Report: {output}')


if __name__ == '__main__':
    main()
