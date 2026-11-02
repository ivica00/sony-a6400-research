"""Reproduce bounded static startup evidence for the current extracted firmware.

Disassembly and string references are observations, not executed control flow.
"""
import json
import re
import struct
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB
from elftools.elf.elffile import ELFFile
from project_paths import PROJECT_ROOT
from tools.research.inventory import digest


def arm_rotated_immediate(word):
    value, rotation = word & 255, ((word >> 8) & 15) * 2
    return ((value >> rotation) | (value << (32 - rotation))) & 0xffffffff if rotation else value


def plt_symbols(elf):
    """Recognize ARM add/add/ldr PLT stubs by their GOT relocation targets."""
    section = elf.get_section_by_name('.plt')
    relocations = elf.get_section_by_name('.rel.plt')
    if section is None or relocations is None:
        return {}
    symbols = elf.get_section(relocations['sh_link'])
    slots = {r['r_offset']: symbols.get_symbol(r['r_info_sym']).name
             for r in relocations.iter_relocations() if r['r_info_type'] == 22}
    data = section.data()
    result = {}
    for offset in range(0, len(data) - 11, 4):
        first, second, third = struct.unpack_from('<3I', data, offset)
        if (first & 0xfffff000 != 0xe28fc000 or second & 0xfffff000 != 0xe28cc000
                or third & 0xfffff000 not in (0xe59cf000, 0xe5bcf000)):
            continue
        address = section['sh_addr'] + offset
        slot = (address + 8 + arm_rotated_immediate(first) +
                arm_rotated_immediate(second) + (third & 4095)) & 0xffffffff
        if slot in slots:
            result[address] = slots[slot]
    return result


def file_to_va(elf, offset):
    for segment in elf.iter_segments():
        if segment['p_type'] == 'PT_LOAD' and segment['p_offset'] <= offset < segment['p_offset'] + segment['p_filesz']:
            return segment['p_vaddr'] + offset - segment['p_offset']
    return None


def read_va(elf, data, address, size):
    for segment in elf.iter_segments():
        if segment['p_type'] == 'PT_LOAD' and segment['p_vaddr'] <= address and address + size <= segment['p_vaddr'] + segment['p_filesz']:
            offset = segment['p_offset'] + address - segment['p_vaddr']
            return data[offset:offset + size]
    return None


def string_va(elf, data, address):
    value = bytearray()
    for index in range(160):
        byte = read_va(elf, data, address + index, 1)
        if byte == b'\0':
            return value.decode('ascii') if len(value) >= 4 else None
        if byte is None or not 32 <= byte[0] < 127:
            return None
        value.extend(byte)
    return None


def decode_block(elf, data, address, size, symbols=None):
    thumb = bool(address & 1)
    address &= ~1
    code = read_va(elf, data, address, size)
    if code is None:
        raise ValueError(f'Code range is not file-backed: {address:#x}+{size:#x}')
    decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    decoder.skipdata = True
    decoder.detail = True
    rows = []
    register_literals = {}
    for instruction in decoder.disasm(code, address):
        row = {'address': instruction.address, 'bytes': instruction.bytes.hex(),
               'mnemonic': instruction.mnemonic, 'operands': instruction.op_str}
        target = re.fullmatch(r'#(0x[0-9a-f]+|[0-9]+)', instruction.op_str)
        if instruction.mnemonic in ('bl', 'blx') and target:
            destination = int(target[1], 0)
            row['call_target'] = destination
            if symbols and destination in symbols:
                row['call_symbol'] = symbols[destination]
        literal = re.fullmatch(r'(\w+), \[pc(?:, #(-?0x[0-9a-f]+|-?[0-9]+))?\]', instruction.op_str)
        if instruction.mnemonic == 'ldr' and literal:
            pc = ((instruction.address + 4) & ~3) if thumb else instruction.address + 8
            pool = pc + (int(literal[2], 0) if literal[2] else 0)
            raw = read_va(elf, data, pool, 4)
            if raw:
                value = struct.unpack('<I', raw)[0]
                row.update(literal_address=pool, literal_value=value)
                text = string_va(elf, data, value)
                if text:
                    row['literal_string'] = text
        pic = re.fullmatch(r'(\w+), pc', instruction.op_str)
        if instruction.mnemonic == 'add' and pic and pic[1] in register_literals:
            value = (register_literals[pic[1]] + instruction.address + (4 if thumb else 8)) & 0xffffffff
            row['pc_relative_value'] = value
            text = string_va(elf, data, value)
            if text:
                row['pc_relative_string'] = text
        if instruction.id:
            _, writes = instruction.regs_access()
            for register in writes:
                register_literals.pop(instruction.reg_name(register), None)
        if literal and 'literal_value' in row:
            register_literals[literal[1]] = row['literal_value']
        if instruction.mnemonic in ('b', 'bl', 'blx', 'bx', 'pop', 'pop.w'):
            register_literals.clear()
        rows.append(row)
    return rows


def analyze(path, needles, named_functions=(), explicit_blocks=()):
    path = path.resolve()
    data = path.read_bytes()
    with path.open('rb') as stream:
        elf = ELFFile(stream)
        symbols, by_name = {}, {}
        for name in ('.dynsym', '.symtab'):
            table = elf.get_section_by_name(name)
            if table:
                for symbol in table.iter_symbols():
                    if symbol['st_info']['type'] == 'STT_FUNC' and symbol['st_value']:
                        symbols[symbol['st_value'] & ~1] = symbol.name
                        by_name[symbol.name] = symbol
        symbols.update(plt_symbols(elf))
        references = []
        for needle in needles:
            for match in re.finditer(re.escape(needle.encode()), data):
                address = file_to_va(elf, match.start())
                pointer_sites = []
                if address is not None:
                    for pointer in re.finditer(re.escape(struct.pack('<I', address)), data):
                        pointer_sites.append({'file_offset': pointer.start(),
                                              'virtual_address': file_to_va(elf, pointer.start())})
                references.append({'string': needle, 'file_offset': match.start(),
                                   'virtual_address': address, 'absolute_pointer_candidates': pointer_sites})
        blocks = []
        for name in named_functions:
            if name == '@text':
                text = elf.get_section_by_name('.text')
                blocks.append({'name': name, 'source': 'linear .text decode; includes literal pools',
                               'instructions': decode_block(elf, data, text['sh_addr'] | (elf['e_entry'] & 1),
                                                            text['sh_size'], symbols)})
                continue
            if name not in by_name:
                continue
            symbol = by_name[name]
            blocks.append({'name': name, 'source': 'ELF symbol',
                           'instructions': decode_block(elf, data, symbol['st_value'], symbol['st_size'], symbols)})
        for name, address, size in explicit_blocks:
            if address is None:
                address = elf['e_entry']
            blocks.append({'name': name, 'source': 'manually selected address; firmware specific',
                           'instructions': decode_block(elf, data, address, size, symbols)})
        return {'path': path.relative_to(PROJECT_ROOT).as_posix(), 'sha256': digest(path),
                'string_references': references, 'blocks': blocks}


def imdb_entries(path):
    """Decode the observed 44-byte entries, retaining uninterpreted raw fields."""
    data = path.read_bytes()
    with path.open('rb') as stream:
        elf = ELFFile(stream)
        symbol = next(s for s in elf.get_section_by_name('.dynsym').iter_symbols() if s.name == 'imdb_raw')
        start = symbol['st_value'] + 0x84
        entries = []
        for index in range(4096):
            address = start + index * 0x2c
            raw = read_va(elf, data, address, 0x2c)
            if raw is None:
                raise ValueError('IMDB table ended without observed sentinel')
            words = struct.unpack('<11I', raw)
            if words[0] == 0x28:
                return {'path': path.relative_to(PROJECT_ROOT).as_posix(), 'sha256': digest(path),
                        'layout_basis': 'IMDB_get_entries +0x84; IMDB_find_entry stride 0x2c and sentinel 0x28',
                        'entries': entries, 'sentinel_address': address}
            strings = {str(offset * 4): string_va(elf, data, word) for offset, word in enumerate(words[4:], 4)}
            entries.append({'index': index, 'address': address, 'raw_words': list(words),
                            'selector_halfword_0e': words[3] >> 16,
                            'string_fields': {key: value for key, value in strings.items() if value}})
    raise ValueError('IMDB table exceeds research bound')


def main():
    base = PROJECT_ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev'
    cases = [
        ('nflasha7_unpacked/sbin/init', ['/usr/bin/bootin.elf', '/usr/bin/launch_shell.elf', 'qemu'],
         ('main', 'run_bg_process', 'check_qemu', 'launch_shell'), ()),
        ('nflasha15_unpacked/bin/bootin.elf', ['im.elf', 'target=qemu'], ('@text',),
         (('entry', None, 96),)),
        ('nflasha15_unpacked/bin/im.elf', ['/usr/lib/libObj.so'], (),
         (('dlopen-selection', 0xb201, 0x7c),)),
        ('nflasha15_unpacked/lib/libObj.so', ['viewUnified2.so', 'initializeViewConfig', 'getViewConfig'],
         ('Application_System_Init',), ()),
        ('nflasha15_unpacked/lib/libIMDB.so', ['/usr/bin/network.sh', 'gui.so', 'appFw.so'],
         ('IMDB_get_entries', 'IMDB_find_entry'), ()),
    ]
    results = [analyze(base / name, needles, functions, blocks)
               for name, needles, functions, blocks in cases]
    target = PROJECT_ROOT / 'artifacts/inventory/startup-trace.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'artifacts': results,
                                 'imdb': imdb_entries(base / 'nflasha15_unpacked/lib/libIMDB.so'),
                                 'limitations': ['Static observations; branches were not executed.',
                                                 'Pointer matches are candidates and may be non-code data.',
                                                 'Explicit block addresses apply only to recorded artifact hashes.']}, indent=2), encoding='utf-8')
    print(f'Recorded {len(results)} startup artifacts: {target}')


if __name__ == '__main__':
    main()
