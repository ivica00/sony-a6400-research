"""Resolve Sony ARM PLT stubs through instruction bytes and ELF relocations."""
import struct


def resolve_arm_plt(elf):
    section = elf.get_section_by_name('.plt')
    relocations = elf.get_section_by_name('.rel.plt')
    if section is None or relocations is None:
        return {}
    symbols = elf.get_section(relocations['sh_link'])
    names = {r['r_offset']: symbols.get_symbol(r['r_info_sym']).name
             for r in relocations.iter_relocations()}
    def immediate(word):
        value, rotate = word & 255, ((word >> 8) & 15) * 2
        return ((value >> rotate) | (value << (32-rotate))) & 0xffffffff if rotate else value
    data, base, result = section.data(), section['sh_addr'], {}
    for offset in range(0, len(data)-11, 4):
        a,b,c = struct.unpack_from('<III', data, offset)
        if (a & 0xfffff000, b & 0xfffff000, c & 0xfffff000) != (0xe28fc000,0xe28cc000,0xe5bcf000):
            continue
        address = base + offset
        got = (address + 8 + immediate(a) + immediate(b) + (c & 4095)) & 0xffffffff
        if got in names:
            result[address] = dict(got=got, name=names[got])
            # Exact Thumb interworking veneer: bx pc; nop (mov r8,r8).
            if offset >= 4 and data[offset-4:offset] == b'\x78\x47\xc0\x46':
                result[address-4] = dict(got=got, name=names[got], arm_stub=address)
    return result
