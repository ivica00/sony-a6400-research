"""Static trace connecting RingBuffer producer and physical storage write path.

No updater, synchronization service, kernel request or hardware write is executed.
"""
import io
import json
import struct

from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.mount_evidence import checked_input
from tools.research.startup_trace import decode_block, plt_symbols
from tools.research.storage_trace import module_relocations, decode_arm_range, inspect_module


def inspect_crypter_range(elf, data, address, size, calls, name_basis):
    rows = decode_block(elf, data, address, size, calls)
    literals = {row['literal_address'] for row in rows if 'literal_address' in row}
    for row in rows:
        row['kind'] = 'literal_data' if row['address'] & ~3 in literals else 'instruction_candidate'
        if row['kind'] == 'literal_data':
            for key in ('mnemonic', 'operands', 'call_target', 'call_symbol'):
                row.pop(key, None)
    return {'name_basis': name_basis, 'entry': address & ~1, 'size': size,
            'is_thumb': bool(address & 1), 'rows': rows}


def data_table_relocations(elf, section_name, start_offset, size):
    section_index = elf.get_section_index(section_name)
    section = elf.get_section(section_index)
    relocs = module_relocations(elf)
    rows = []
    for offset in range(start_offset, start_offset + size, 4):
        key = (section_index, offset)
        rel = relocs.get(key)
        raw = section.data()[offset:offset + 4]
        row = {'offset': offset, 'raw_hex': raw.hex(),
               'value': struct.unpack('<I', raw)[0]}
        if rel:
            row['relocation'] = rel
        rows.append(row)
    return rows


def find_calls_to_target(rows, target_offset):
    results = []
    for row in rows:
        if row.get('kind') == 'instruction_candidate' and row.get('mnemonic') in ('b', 'bl'):
            operands = row.get('operands', '')
            try:
                dest = int(operands.lstrip('#'), 0)
                if dest == target_offset:
                    results.append({'offset': row['offset'], 'mnemonic': row['mnemonic'],
                                    'target': dest})
            except (ValueError, TypeError):
                pass
    return results


def main():
    folder = PROJECT_ROOT / 'artifacts/inventory'
    expected = {row['path']: row['sha256'] for row in
                json.loads((folder / 'baseline.json').read_text(encoding='utf-8'))['inputs']}
    paths = {
        'crypter': 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/bin/crypter.elf',
        'body': 'firmware/extracted_a6400/updater.img_unpacked/bodylib/libupdaterbody.so',
        'common': 'firmware/extracted_a6400/updater.img_unpacked/usr/lib/libupdatercommon.so',
        'storage': 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/initrd.img_unpacked/kmod/emmc.ko',
    }
    inputs = {name: checked_input(PROJECT_ROOT, path, expected[path]) for name, path in paths.items()}

    crypter_elf = ELFFile(io.BytesIO(inputs['crypter']))
    crypter_calls = plt_symbols(crypter_elf)

    storage_elf = ELFFile(io.BytesIO(inputs['storage']))
    storage_sec_idx = storage_elf.get_section_index('.text')
    storage_sec = storage_elf.get_section(storage_sec_idx)
    storage_relocs = {offset: row for (i, offset), row in module_relocations(storage_elf).items()
                      if i == storage_sec_idx}

    kthread_rows = inspect_module(inputs['storage'], ('emmc_blk_kthread',))[0]['rows']
    kthread_emmc_write_calls = find_calls_to_target(kthread_rows, 0xa89c)

    report = {
        'schema_version': 1,
        'status': 'static_producer_and_physical_storage_trace',
        'updater_executed': False,
        'camera_fidelity_validated': False,
        'runtime_device_identity_selected': False,
        'sources': {name: {'path': path, 'sha256': expected[path]} for name, path in paths.items()},
        'producer_pipeline': {
            'base_module_init': inspect_crypter_range(
                crypter_elf, inputs['crypter'], 0xcfe1, 0x58, crypter_calls,
                'Diagnostic string: virtual void Updater::BaseModule::Initialize'
            ),
            'body_loader_execute': inspect_crypter_range(
                crypter_elf, inputs['crypter'], 0xc491, 0x1a0, crypter_calls,
                'String: BaseBodyLoaderModule.cpp; dlopen libupdaterbody.so, GetBody, Execute'
            ),
            'decryptor_execute': inspect_crypter_range(
                crypter_elf, inputs['crypter'], 0xdfe1, 0x38, crypter_calls,
                'String: DecryptorModule.cpp; Dec_Scramble 16-byte block loop'
            ),
            'file_input_read_loop': inspect_crypter_range(
                crypter_elf, inputs['crypter'], 0xb935, 0x1a0, crypter_calls,
                'String: FileInputUpdaterManager.cpp; FileHandler::Read and WriteData loop'
            ),
        },
        'storage_physical_path': {
            'kthread_write_dispatches': kthread_emmc_write_calls,
            'decomp_callback_table': {
                'section': '.data',
                'start_offset': 0x94,
                'size': 8,
                'slots': data_table_relocations(storage_elf, '.data', 0x94, 8),
            },
            'storage_write_helper': {
                'name_basis': 'diagnostic string emmc_write, not a recovered function symbol',
                'section': '.text', 'start': 0xa89c, 'size': 0xa8,
                'rows': decode_arm_range(storage_sec.data(), 0xa89c, 0xa8, storage_relocs),
            },
            'emmc_seq_write': inspect_module(inputs['storage'], ('emmc_seq_write',))[0],
            'write_block_retry': {
                'name_basis': 'diagnostic string write_block_retry() ended failure...',
                'section': '.text', 'start': 0x12ea8, 'size': 0x150,
                'rows': decode_arm_range(storage_sec.data(), 0x12ea8, 0x150, storage_relocs),
            },
            'exec_emmc_data_cmd': {
                'name_basis': 'diagnostic string exec_emmc_data_cmd',
                'section': '.text', 'start': 0xf270, 'size': 0x160,
                'rows': decode_arm_range(storage_sec.data(), 0xf270, 0x160, storage_relocs),
            },
            'sdhci_emmc_exec_data_cmd': inspect_module(inputs['storage'], ('sdhci_emmc_exec_data_cmd',))[0],
        },
        'limitations': [
            'No updater function, decryption key schedule, kernel request or hardware write is executed.',
            'Crypter module pipeline connections are observed from static code, vtables, and diagnostic assertions.',
            'Storage driver path traces from kthread direct/buffered dispatch down to SDHCI host controller data_cmd.',
            'Physical nonvolatile flash state, runtime device mounts, and writable /etc contents remain unobserved.',
        ],
    }

    output = folder / 'producer-physical-storage-trace.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Recorded producer pipeline and physical storage-write path; no updater/device operations executed.')
    print(f'Report: {output}')


if __name__ == '__main__':
    main()
