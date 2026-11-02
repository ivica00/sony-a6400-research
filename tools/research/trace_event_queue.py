import struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
import capstone

def main():
    im_path = Path('firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/bin/im.elf')
    raw = im_path.read_bytes()
    target = struct.pack('<I', 0x0094016a)
    idx = 0
    while True:
        idx = raw.find(target, idx)
        if idx == -1:
            break
        print(f"Found 0x0094016a at file offset {hex(idx)} (addr ~ {hex(0x8000 + idx)})")
        idx += 4

    with open(im_path, 'rb') as f:
        elf = ELFFile(f)
        rel = elf.get_section_by_name('.rel.plt')
        dyn = elf.get_section_by_name('.dynsym')
        print("\n--- PLT Relocations ---")
        plt_syms = []
        for r in rel.iter_relocations():
            sym = dyn.get_symbol(r['r_info_sym'])
            plt_syms.append((r['r_offset'], sym.name))
        
        # In ARM ELF, PLT entries start at .plt section sh_addr + 20, 12 bytes each
        plt_sec = elf.get_section_by_name('.plt')
        plt_base = plt_sec['sh_addr']
        for i, (got_offset, name) in enumerate(plt_syms):
            call_addr = plt_base + 20 + i * 12
            print(f"  PLT {hex(call_addr)} (GOT {hex(got_offset)}): {name}")
        elf = ELFFile(f)
        text_sec = elf.get_section_by_name('.text')
        text_data = text_sec.data()
        text_base = text_sec['sh_addr']
        
        md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
        addr = (0xa2fa + 4 + 0xc4) & ~3
        val = struct.unpack('<I', text_data[addr - text_base : addr - text_base + 4])[0]
        print(f"\nLiteral loaded at 0xa2fa (addr {hex(addr)}) = {hex(val)}")
        
        # Check literals in handler at 0x9360
        # In Thumb mode at 0x9362, PC is 0x9366. (0x9366 + 0x60) & ~3 = 0x93c4
        c1_addr = (0x9362 + 4 + 0x60) & ~3
        c1 = struct.unpack('<I', text_data[c1_addr - text_base : c1_addr - text_base + 4])[0]
        # At 0x9388, PC is 0x938c. (0x938c + 0x40) & ~3 = 0x93cc
        c2_addr = (0x9388 + 4 + 0x40) & ~3
        c2 = struct.unpack('<I', text_data[c2_addr - text_base : c2_addr - text_base + 4])[0]
        print("\n--- Disassembling 0xac18 ---")
        ac_bytes = text_data[0xac18 - text_base : 0xad50 - text_base]
        for ins in md.disasm(ac_bytes, 0xac18):
            print(f"  {hex(ins.address)}: {ins.mnemonic} {ins.op_str}")

if __name__ == '__main__':
    main()
