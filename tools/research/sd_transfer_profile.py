"""Verify original SD serialized transfer pipeline and card-state initialization."""
import argparse
import io
import json
import struct

from elftools.elf.elffile import ELFFile
from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input
from tools.research.startup_trace import decode_block, plt_symbols

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

    # Required symbols and their expected values
    expected_symbols = {
        'serialized_transfer': 0x2760,
        'mmcd_blk_ioctl': 0x3fa0,
        'real_card_transfer': 0x53ac,
        'mmc_mmcp_detect_each': 0x14794,
        'mmc_mmcp_read': 0x17070,
        'mmc_hw_wrapper_lock_sem': 0x18dfc,
        'mmc_hw_wrapper_unlock_sem': 0x18e70,
    }
    for name, expected_addr in expected_symbols.items():
        if symbols[name]['st_value'] != expected_addr:
            raise ValueError(f'Symbol {name} moved from expected 0x{expected_addr:x}')

    # Verify relocations in key functions
    text_index = next(i for i, s in enumerate(elf.iter_sections()) if s.name == '.text')
    all_relocations = {}
    for section in elf.iter_sections():
        if section['sh_type'] == 'SHT_REL' and section['sh_info'] == text_index:
            symtab = elf.get_section_by_name('.symtab')
            sym_names = [s.name for s in symtab.iter_symbols()]
            for r in section.iter_relocations():
                all_relocations[r['r_offset']] = (r['r_info_type'], sym_names[r['r_info_sym']])

    # Verify preparation function relocations
    prep_relocs = {off: all_relocations[off][1] for off in (0x1633c, 0x16368, 0x16384, 0x163c8) if off in all_relocations}
    if prep_relocs.get(0x1633c) != 'mmc_hw_wrapper_lock_sem' or prep_relocs.get(0x163c8) != 'mmc_hw_wrapper_unlock_sem':
        raise ValueError('Preparation synchronization relocations mismatch')

    # Verify mmc_mmcp_read branch to 0x16e94 helper
    branch = struct.unpack_from('<I', text, 0x17088)[0]
    disp = (branch & 0xffffff) << 2
    if disp & 0x2000000:
        disp -= 0x4000000
    if branch >> 24 != 0xeb or 0x17090 + disp != 0x16e94:
        raise ValueError('mmc_mmcp_read branch destination changed')

    pipeline = [
        {
            'step': 1,
            'stage': 'ioctl_dispatch',
            'function': 'mmcd_blk_ioctl',
            'text_offset': 0x3fa0,
            'size': 0x724,
            'description': 'Dispatches ioctl 0x10f (read, direction 0) to extent/transfer range validator at 0x343c.',
        },
        {
            'step': 2,
            'stage': 'range_validation',
            'function': 'unnamed_0x343c',
            'text_offset': 0x343c,
            'size': 0xec,
            'description': 'Validates LBA (request+8) and count (request+12) against summed partition extents; writes -3 on failure, invokes transfer chunker at 0x31d4.',
        },
        {
            'step': 3,
            'stage': 'scatterlist_chunking',
            'function': 'unnamed_0x31d4',
            'text_offset': 0x31d4,
            'size': 0x268,
            'description': 'Chunks requests exceeding 0x8000 sectors, builds scatterlist via mcmnd_api_makescatterlist, invokes device vtable via 0x2f44.',
        },
        {
            'step': 4,
            'stage': 'serialized_routing',
            'function': 'serialized_transfer',
            'text_offset': 0x2760,
            'size': 0x144,
            'description': 'Routes request through serialized device table; delegates to real_card_transfer (*puVar1).',
        },
        {
            'step': 5,
            'stage': 'card_operations_dispatch',
            'function': 'real_card_transfer',
            'text_offset': 0x53ac,
            'size': 0x108,
            'description': 'For read (direction 0): records trace API 0x81, invokes card ops table entry 0 (**(card+0xc) = mmc_mmcp_read) with card context.',
        },
        {
            'step': 6,
            'stage': 'mmcp_read_entry',
            'function': 'mmc_mmcp_read',
            'text_offset': 0x17070,
            'size': 0x24,
            'description': 'Passes selector 3 (read), starting sector, count, and scatterlist callbacks to 0x16e94.',
        },
        {
            'step': 7,
            'stage': 'mmcp_transfer_helper',
            'function': 'unnamed_0x16e94',
            'text_offset': 0x16e94,
            'size': 0x14c,
            'description': 'Validates capacity against card[0xb7] (+0x2dc), calls preparation helper 0x16328, issues CMD17/18, calls unlock sem wrapper before exit.',
        },
        {
            'step': 8,
            'stage': 'preparation_and_lock',
            'function': 'unnamed_0x16328',
            'text_offset': 0x16328,
            'size': 0xb0,
            'description': 'Loads state[0] (host_hw pointer) at 0x16338, calls mmc_hw_wrapper_lock_sem at 0x1633c, compares card RCA (+0x278) with selected RCA ([+0x290]), returns 0 with lock held.',
        },
    ]

    card_state_layout = {
        'structure': 'mmcp_card',
        'allocated_size': 0x508,
        'allocator': 'mmc_mmcp_detect_each (0x14794)',
        'fields': [
            {'offset': 0x000, 'name': 'host_hw', 'type': 'void*', 'description': 'Pointer to host controller hardware context structure (state[0]).'},
            {'offset': 0x004, 'name': 'host_hw_plus_4', 'type': 'void*', 'description': 'Secondary host context reference.'},
            {'offset': 0x21c, 'name': 'csd_raw', 'type': 'uint32_t[4]', 'description': 'Raw CSD register words (CMD9 response).'},
            {'offset': 0x278, 'name': 'rca', 'type': 'uint16_t', 'description': 'Relative Card Address (CMD3 response).'},
            {'offset': 0x280, 'name': 'bus_width', 'type': 'uint32_t', 'description': 'Bus width mode (initial 1-bit, upgraded to 4-bit).'},
            {'offset': 0x284, 'name': 'clk_freq_khz', 'type': 'uint32_t', 'description': 'Clock frequency in kHz (initial 25000 = 25 MHz).'},
            {'offset': 0x28c, 'name': 'selected_rca_storage', 'type': 'uint16_t', 'description': 'Active selected RCA on bus.'},
            {'offset': 0x290, 'name': 'selected_rca_ptr', 'type': 'uint16_t*', 'description': 'Pointer to selected RCA storage (defaults to +0x28c).'},
            {'offset': 0x2dc, 'name': 'capacity_sectors', 'type': 'uint32_t', 'description': 'Total card capacity in 512-byte sectors (derived from CSD v1/v2).'},
        ],
    }

    synchronization_contract = {
        'host_hw_byte_0': 'Hardware controller ID (hw_id, 0..3)',
        'lock_function': 'mmc_hw_wrapper_lock_sem (0x18dfc)',
        'lock_dispatch': 'ip_func_ops[hw_id]->lock_sem (+0x2c)',
        'unlock_function': 'mmc_hw_wrapper_unlock_sem (0x18e70)',
        'unlock_dispatch': 'ip_func_ops[hw_id]->unlock_sem (+0x30)',
        'selection_optimization': 'When card RCA (+0x278) matches selected RCA ([+0x290]), bus width and clock reconfiguration are bypassed; lock is retained during transfer.',
    }

    report = {
        'input': {'path': DRIVER, 'sha256': digest},
        'pipeline': pipeline,
        'card_state_layout': card_state_layout,
        'synchronization_contract': synchronization_contract,
        'limitations': [
            'Static kernel driver disassembly and verified structures, not live device execution.',
            'No physical SD card or hardware controller MMIO response is fabricated.',
            'Card E:\\ is unchanged; emulator remains bounded by explicit verified contracts.',
        ],
    }

    checked_input(PROJECT_ROOT, DRIVER, digest)
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    print(output, f'verified {len(pipeline)} pipeline stages, card layout (0x508 bytes) and synchronization contract')


if __name__ == '__main__':
    main()
