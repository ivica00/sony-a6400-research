"""Generate ARM chunk-framing bytes for the offline Unicorn EP0 model."""
import argparse
import hashlib
import json
from pathlib import Path

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection

ROOT = Path(__file__).resolve().parents[2]
SECTION = '.text'
DEFAULT_OBJECT = ROOT / 'artifacts/native/ep0-chunk-e0405/gadgetcore_chunk.o'
OUTPUT = ROOT / 'src/a6400/debug/gadgetcore_chunk_stub.py'
SOURCE = ROOT / 'tools/native_camera/gadgetcore_chunk.c'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--object', type=Path, default=DEFAULT_OBJECT)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    raw = args.object.read_bytes()
    with args.object.open('rb') as handle:
        elf = ELFFile(handle)
        if elf.header.e_machine != 'EM_ARM' or not elf.little_endian:
            raise SystemExit('chunk object is not little-endian ARM')
        section = elf.get_section_by_name(SECTION)
        if section is None:
            raise SystemExit('missing .text')
        symbols = {}
        for table in elf.iter_sections():
            if isinstance(table, SymbolTableSection):
                for symbol in table.iter_symbols():
                    if (symbol.name and symbol['st_info']['type'] == 'STT_FUNC'
                            and symbol['st_shndx'] != 'SHN_UNDEF'
                            and section['sh_addr'] <= symbol['st_value']
                            < section['sh_addr'] + section['sh_size']):
                        symbols[symbol.name] = symbol['st_value'] - section['sh_addr']
        code = section.data()
    required = ['a6400_chunk_extract', 'a6400_chunk_insert']
    if any(name not in symbols for name in required):
        raise SystemExit(f'missing functions: {symbols}')
    module = [
        '"""Generated ARM64-free chunk framing bytes (E0405b). Do not edit."""',
        f'# source_sha256={hashlib.sha256(SOURCE.read_bytes()).hexdigest()}',
        f'# object_sha256={hashlib.sha256(raw).hexdigest()}',
        f'# stub_sha256={hashlib.sha256(code).hexdigest()}',
        f'STUB_TEXT = bytes.fromhex("{code.hex()}")',
        'STUB_SYMBOLS = {',
    ]
    for name in required:
        module.append(f'    {name!r}: {symbols[name]},')
    module.append('}')
    args.output.write_text('\n'.join(module) + '\n', encoding='utf-8')
    receipt = {'object': str(args.object), 'bytes': len(code),
               'sha256': hashlib.sha256(code).hexdigest(),
               'symbols': {name: symbols[name] for name in required}}
    args.object.with_suffix('.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
