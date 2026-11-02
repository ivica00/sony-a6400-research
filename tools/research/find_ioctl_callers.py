import struct
from elftools.elf.elffile import ELFFile

def find_ioctl_callers():
    path = "firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libObj.so"
    with open(path, "rb") as f:
        elf = ELFFile(f)
        text = elf.get_section_by_name('.text')
        t_data = text.data()
        t_addr = text['sh_addr']
        symtab = elf.get_section_by_name('.symtab') or elf.get_section_by_name('.dynsym')
        
        target = 0x10420c
        # In Thumb-2:
        # blx label:
        # HW1: 1111 0 S imm10
        # HW2: 11 J1 0 J2 imm11:0
        callers = []
        for offset in range(0, len(t_data) - 4, 2):
            hw1, hw2 = struct.unpack_from('<2H', t_data, offset)
            if (hw1 & 0xf800) == 0xf000 and (hw2 & 0xd000) in (0xd000, 0xc000):
                # bl or blx
                s = (hw1 >> 10) & 1
                imm10 = hw1 & 0x3ff
                j1 = (hw2 >> 13) & 1
                j2 = (hw2 >> 11) & 1
                imm11 = hw2 & 0x7ff
                i1 = ~(j1 ^ s) & 1
                i2 = ~(j2 ^ s) & 1
                imm25 = (s << 24) | (i1 << 23) | (i2 << 22) | (imm10 << 12) | (imm11 << 1)
                if s:
                    imm25 -= (1 << 25)
                pc = t_addr + offset + 4
                dest = pc + imm25
                if (hw2 & 0x1000) == 0:
                    dest &= ~3 # blx to ARM
                if dest == target:
                    caller_va = t_addr + offset
                    callers.append(caller_va)
        print(f"Found {len(callers)} calls to ioctl PLT in libObj.so:")
        for c in callers:
            # find enclosing symbol
            closest = None
            min_d = 999999
            for s in symtab.iter_symbols():
                v = s['st_value'] & ~1
                if 0 <= c - v < min_d:
                    min_d = c - v
                    closest = s
            name = closest.name if closest else "unknown"
            print(f"  {hex(c)} in {name} (+{hex(min_d)})")

if __name__ == "__main__":
    find_ioctl_callers()
