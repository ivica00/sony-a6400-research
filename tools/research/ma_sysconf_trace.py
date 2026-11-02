"""Static original sysconf(30) dependency; no runtime page-size reply."""
import argparse
import io
import json
import struct

from elftools.elf.elffile import ELFFile
from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input
from tools.research.startup_trace import read_va, decode_block

LIBC = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/lib/libc-2.11.2.so'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', required=True)
    args = parser.parse_args()
    output = (PROJECT_ROOT / args.report_dir).resolve()
    if not output.is_relative_to(PROJECT_ROOT / 'artifacts'):
        parser.error('Output must remain under artifacts')
    output.mkdir(parents=True, exist_ok=False)
    digest = next(r['sha256'] for r in json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text())['inputs'] if r['path'] == LIBC)
    raw = checked_input(PROJECT_ROOT, LIBC, digest)
    elf = ELFFile(io.BytesIO(raw))
    symbols = {s.name: s for s in elf.get_section_by_name('.dynsym').iter_symbols()}
    if symbols['sysconf']['st_value'] != 0x7b56d or symbols['getpagesize']['st_value'] != 0x9b581:
        raise ValueError('Original Thumb function coordinates changed')
    table = 0x7b596
    entry_address = table + 30 * 2
    offset = struct.unpack('<H', read_va(elf, raw, entry_address, 2))[0]
    target = table + 2 * offset
    case = decode_block(elf, raw, target | 1, 8)
    if case[0].get('call_target') != 0x9b580:
        raise ValueError('Selector no longer calls original getpagesize')
    word = lambda a: struct.unpack('<I', read_va(elf, raw, a, 4))[0]
    slot = (word(0x9b594) + 0x9b588 + word(0x9b598)) & 0xffffffff
    matches = []
    for section in elf.iter_sections():
        if section['sh_type'] != 'SHT_REL':
            continue
        for relocation in section.iter_relocations():
            if relocation['r_offset'] == slot:
                symbol = elf.get_section(section['sh_link']).get_symbol(relocation['r_info_sym'])
                matches.append({'type': relocation['r_info_type'], 'symbol': symbol.name, 'section': symbol['st_shndx']})
    if matches != [{'type': 21, 'symbol': '_rtld_global_ro', 'section': 'SHN_UNDEF'}]:
        raise ValueError('Page-size loader dependency changed')
    report = {'input': {'path': LIBC, 'sha256': digest}, 'method': 'Static original Thumb instructions and relocations; no execution',
        'selector': 30, 'table_address': table, 'entry_address': entry_address, 'entry_halfword': offset,
        'case_target': target, 'case_instructions': case, 'getpagesize': 0x9b580,
        'getpagesize_instructions': decode_block(elf, raw, 0x9b581, 20),
        'getpagesize_got_slot': slot, 'relocations': matches,
        'limitations': ['Undefined loader object and runtime field are not supplied.',
            'Observed zero-field fallback4096 is not a runtime response or permission to skip its preceding read.']}
    checked_input(PROJECT_ROOT, LIBC, digest)
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    print(output, 'sysconf30 -> getpagesize -> _rtld_global_ro (unsupplied)')


if __name__ == '__main__':
    main()
