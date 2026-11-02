"""Verify original media read callback assignments and their syscall windows."""
import argparse
import io
import json
import struct

from elftools.elf.elffile import ELFFile
from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input
from tools.research.startup_trace import decode_block, plt_symbols

TARGET = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libInfraMediaCommon.so'
DRIVER = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/mmc_drv.ko'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', required=True)
    args = parser.parse_args()
    output = (PROJECT_ROOT / args.report_dir).resolve()
    if not output.is_relative_to(PROJECT_ROOT / 'artifacts'):
        parser.error('Output must remain under artifacts')
    output.mkdir(parents=True, exist_ok=False)
    digest = next(r['sha256'] for r in json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text())['inputs'] if r['path'] == TARGET)
    raw = checked_input(PROJECT_ROOT, TARGET, digest)
    elf = ELFFile(io.BytesIO(raw))
    if (elf['e_type'], elf['e_machine'], elf.elfclass, elf.little_endian) != ('ET_DYN', 'EM_ARM', 32, True):
        raise ValueError('Expected ARM32 original library')
    symbols = {s.name: s for s in elf.get_section_by_name('.dynsym').iter_symbols()}
    plts = plt_symbols(elf)
    functions = []
    for name in ('mcmn_drv_mmc_open', 'mcmn_drv_default_read', 'mcmn_drv_default_read_impl', 'mcmn_drv_mmc_mount4sd'):
        symbol = symbols[name]
        if symbol['st_shndx'] == 'SHN_UNDEF' or symbol['st_info']['type'] != 'STT_FUNC' or not 0 < symbol['st_size'] <= 2048:
            raise ValueError('Selected original function is not bounded source code')
        functions.append({'name': name, 'entry': symbol['st_value'], 'size': symbol['st_size'],
                          'instructions': decode_block(elf, raw, symbol['st_value'], symbol['st_size'], plts)})
    opener = {i['address']: i for i in functions[0]['instructions']}
    bindings = []
    for producer, store, register, offset, expected in ((79072, 79078, 'r0', 0xcc, 0x12869), (79076, 79084, 'r1', 0xd0, 0x117d1)):
        if opener[producer].get('pc_relative_value') != expected or opener[store]['operands'] != f'{register}, [r4, #{offset:#x}]' or opener[store]['mnemonic'] != 'str.w':
            raise ValueError('Original callback assignment changed')
        bindings.append({'producer_pc': producer, 'store_pc': store, 'field_offset': offset, 'thumb_entry': expected})
    for label, entry, size in (('registered_read_wrapper', 0x12869, 92), ('registered_read_impl', 0x117d1, 264)):
        functions.append({'name': label, 'entry': entry, 'size': size,
                          'instructions': decode_block(elf, raw, entry, size, plts)})
    report = {'input': {'path': TARGET, 'sha256': digest}, 'bindings': bindings, 'functions': functions,
              'limitations': ['Static original assignments on a successful open branch, not a live initialized device.',
                              'Registered implementation uses ioctl0x10f; generic lseek64/read is not its callback.',
                              'No ioctl, mount, transfer or hardware response is executed/supplied.']}
    driver_digest = next(r['sha256'] for r in json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text())['inputs'] if r['path'] == DRIVER)
    driver_raw = checked_input(PROJECT_ROOT, DRIVER, driver_digest)
    driver = ELFFile(io.BytesIO(driver_raw))
    descriptor = struct.pack('<III', 0x10f, 16, 0)
    matches = []
    for section in driver.iter_sections():
        if section['sh_flags'] & 2 and section['sh_type'] != 'SHT_NOBITS':
            data = section.data()
            matches.extend((section.name, offset) for offset in range(0, len(data) - 11, 4) if data[offset:offset + 12] == descriptor)
    if matches != [('.data', 0x138)]:
        raise ValueError('Original ioctl descriptor is missing or ambiguous')
    report['driver'] = {'path': DRIVER, 'sha256': driver_digest,
                        'read_ioctl_descriptor': {'section': '.data', 'offset': 0x138, 'command': 0x10f, 'bytes': 16, 'status_offset': 0}}
    checked_input(PROJECT_ROOT, DRIVER, driver_digest)
    checked_input(PROJECT_ROOT, TARGET, digest)
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    print(output, 'verified original callback offsets cc/d0')


if __name__ == '__main__':
    main()
