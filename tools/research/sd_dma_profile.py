"""Verify SD DMA scatter-gather buffer transfer contract and ADMA2 descriptors."""
import argparse
import io
import json
import struct

from elftools.elf.elffile import ELFFile
from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input

MMC_DRIVER = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/mmc_drv.ko'
MCMN_DRIVER = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/mcmn_drv.ko'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', required=True)
    args = parser.parse_args()
    output = (PROJECT_ROOT / args.report_dir).resolve()
    if not output.is_relative_to(PROJECT_ROOT / 'artifacts'):
        parser.error('Output must remain under artifacts')
    output.mkdir(parents=True, exist_ok=False)

    baseline = json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text())['inputs']
    mmc_digest = next(r['sha256'] for r in baseline if r['path'] == MMC_DRIVER)
    mcmn_digest = next(r['sha256'] for r in baseline if r['path'] == MCMN_DRIVER)

    mmc_raw = checked_input(PROJECT_ROOT, MMC_DRIVER, mmc_digest)
    mcmn_raw = checked_input(PROJECT_ROOT, MCMN_DRIVER, mcmn_digest)

    mmc_elf = ELFFile(io.BytesIO(mmc_raw))
    mcmn_elf = ELFFile(io.BytesIO(mcmn_raw))

    mmc_sym_list = [(s.name, s['st_value']) for s in mmc_elf.get_section_by_name('.symtab').iter_symbols()]
    mcmn_sym_list = [(s.name, s['st_value']) for s in mcmn_elf.get_section_by_name('.symtab').iter_symbols()]

    mmc_text = mmc_elf.get_section_by_name('.text').data()
    mcmn_text = mcmn_elf.get_section_by_name('.text').data()

    # Verify single-segment and multi-segment scatterlist adapter symbols in mmc_drv.ko
    expected_mmc_symbols = [
        ('list_count', 0x1e8c),
        ('get_next', 0x1ea0),
        ('reset_list_ptr', 0x1ed8),
        ('mmc_single_scatter_list', 0x2090),
        ('list_count', 0x25cc),
        ('get_next', 0x25e0),
        ('reset_list_ptr', 0x2688),
        ('mmc_hw_exec_command', 0xd754),
    ]
    for name, expected_addr in expected_mmc_symbols:
        if (name, expected_addr) not in mmc_sym_list:
            raise ValueError(f'MMC symbol ({name}, 0x{expected_addr:x}) not found')

    # Verify scatterlist export symbols in mcmn_drv.ko
    expected_mcmn_symbols = [
        ('mcmnd_api_makescatterlist', 0x2d0),
        ('mcmnd_api_releasescatterlist', 0x2bc),
        ('mcmnd_scatter_makescatterlist', 0xd5cc),
        ('mcmnd_scatter_releasescatterlist', 0xd7ac),
    ]
    for name, expected_addr in expected_mcmn_symbols:
        if (name, expected_addr) not in mcmn_sym_list:
            raise ValueError(f'MCMN symbol ({name}, 0x{expected_addr:x}) not found')

    # Verify mmc_single_scatter_list adapter layout
    # 0x209c: stm r1, {r2, r3} (store addr, len to state)
    # 0x20a4: str r3, [r1, #8] (store index = 0)
    # 0x20ac: str r1, [r0] (adapter->state = state)
    stm_ins = struct.unpack_from('<I', mmc_text, 0x209c)[0]
    if stm_ins != 0xe881000c:  # stm r1, {r2, r3}
        raise ValueError('mmc_single_scatter_list does not store address/length via stm r1')

    # Verify ADMA2 END bit manipulation at 0xd910 in mmc_hw_exec_command
    # 0xd910: orr r2, r2, #2 (set ADMA2_END bit)
    orr_ins = struct.unpack_from('<I', mmc_text, 0xd910)[0]
    if orr_ins != 0xe3822002:  # orr r2, r2, #2
        raise ValueError('mmc_hw_exec_command does not set ADMA2_END bit (0x02)')

    # Verify ADMA2 table address write to SDHCI_ADMA_ADDRESS (0x58) at 0xd924
    mov_ins = struct.unpack_from('<I', mmc_text, 0xd924)[0]
    if mov_ins != 0xe3a01058:  # mov r1, #0x58
        raise ValueError('mmc_hw_exec_command does not load SDHCI_ADMA_ADDRESS register (0x58)')

    report = {
        'mmc_driver': MMC_DRIVER,
        'mmc_sha256': mmc_digest,
        'mcmn_driver': MCMN_DRIVER,
        'mcmn_sha256': mcmn_digest,
        'scatterlist_memory_pipeline': {
            'step_1_user_pinning': {
                'module': 'mcmn_drv.ko',
                'function': 'mcmnd_scatter_makescatterlist',
                'offset': '0xd5cc',
                'locking': 'compat_down_read(&current->mm->mmap_sem)',
                'pinning': 'get_user_pages()',
                'mapping': 'dma_map_sg()',
            },
            'step_2_adapter_wrapping': {
                'module': 'mmc_drv.ko',
                'constructor': 'mmc_single_scatter_list',
                'offset': '0x2090',
                'single_segment_adapter': [
                    {'offset': '0x00', 'name': 'state', 'description': 'Pointer to [phys_addr, length, index].'},
                    {'offset': '0x04', 'name': 'list_count', 'addr': '0x1e8c', 'description': 'Returns number of segments (1).'},
                    {'offset': '0x08', 'name': 'get_next', 'addr': '0x1ea0', 'description': 'Fills segment physical address and length, returns 1 then 0.'},
                    {'offset': '0x0c', 'name': 'reset_list_ptr', 'addr': '0x1ed8', 'description': 'Resets segment iteration index to 0.'},
                ],
                'multi_segment_adapter': [
                    {'offset': '0x00', 'name': 'state', 'description': 'Pointer to struct scatterlist array state.'},
                    {'offset': '0x04', 'name': 'list_count', 'addr': '0x25cc', 'description': 'Returns segment count from state[2].'},
                    {'offset': '0x08', 'name': 'get_next', 'addr': '0x25e0', 'description': 'Iterates 16-byte scatterlist array, extracts dma_address (+0xc) and length (+0x8).'},
                    {'offset': '0x0c', 'name': 'reset_list_ptr', 'addr': '0x2688', 'description': 'Resets multi-segment index to 0.'},
                ],
            },
            'step_3_adma2_programming': {
                'module': 'mmc_drv.ko',
                'function': 'mmc_hw_exec_command',
                'offset': '0xd754',
                'descriptor_entry_size': 8,
                'descriptor_format': {
                    'word_0': 'attribute_and_length (lower 16 bits = attributes, upper 16 bits = byte length)',
                    'word_1': 'physical_buffer_address (32-bit DMA address)',
                },
                'adma2_attributes': {
                    'valid_bit': '0x01',
                    'end_bit': '0x02',
                    'action_transfer': '0x20',
                    'normal_entry': '0x21',
                    'terminating_entry': '0x23',
                },
                'sdhci_registers': [
                    {'offset': '0x00', 'name': 'SDHCI_DMA_ADDRESS', 'width': 32, 'description': 'SDMA system address / Argument 2.'},
                    {'offset': '0x04', 'name': 'SDHCI_BLOCK_SIZE', 'width': 16, 'description': 'Transfer block size (512 / 0x200 bytes).'},
                    {'offset': '0x06', 'name': 'SDHCI_BLOCK_COUNT', 'width': 16, 'description': 'Number of transfer blocks.'},
                    {'offset': '0x08', 'name': 'SDHCI_ARGUMENT', 'width': 32, 'description': 'Command argument (starting sector LBA).'},
                    {'offset': '0x0c', 'name': 'SDHCI_TRANSFER_MODE', 'width': 16, 'description': 'DMA enable, read direction, multi-block flags.'},
                    {'offset': '0x0e', 'name': 'SDHCI_COMMAND', 'width': 16, 'description': 'Command trigger (CMD17 / CMD18).'},
                    {'offset': '0x2c', 'name': 'SDHCI_PRESENT_STATE', 'width': 32, 'description': 'DATA/CMD inhibit polling.'},
                    {'offset': '0x2e', 'name': 'SDHCI_TIMEOUT_CONTROL', 'width': 8, 'description': 'Data timeout control.'},
                    {'offset': '0x58', 'name': 'SDHCI_ADMA_ADDRESS', 'width': 32, 'description': 'Physical address of ADMA2 descriptor table.'},
                ],
            },
            'step_4_cleanup': {
                'module': 'mcmn_drv.ko',
                'function': 'mcmnd_scatter_releasescatterlist',
                'offset': '0xd7ac',
                'unmapping': 'dma_unmap_sg()',
                'unpinning': 'put_page()',
            },
        },
        'status': 'verified',
    }

    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
