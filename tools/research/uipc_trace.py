"""Research tool for tracing and analyzing osal_uipc.ko and libosal_uipc.so contracts."""

import struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from project_paths import PROJECT_ROOT

def analyze_uipc():
    ko_path = PROJECT_ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/osal_uipc.ko'
    so_path = PROJECT_ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libosal_uipc.so'

    print("=== Analyzing osal_uipc.ko ===")
    with open(ko_path, 'rb') as f:
        elf = ELFFile(f)
        symtab = elf.get_section_by_name('.symtab')
        sec_text = elf.get_section_by_name('.text')
        sec_rodata = elf.get_section_by_name('.rodata')
        
        symbols = {}
        for sym in symtab.iter_symbols():
            symbols[sym.name] = (sym['st_value'], sym['st_size'], sym['st_shndx'])

        import capstone
        md_arm = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
        
        # Disassemble __k_uipc_cdev_ioctl
        ioctl_val, ioctl_sz, _ = symbols['__k_uipc_cdev_ioctl']
        raw = sec_text.data()[ioctl_val:ioctl_val+ioctl_sz]
        print("\n--- __k_uipc_cdev_ioctl disassembly ---")
        for ins in md_arm.disasm(raw, ioctl_val):
            print(f"  {hex(ins.address)}: {ins.mnemonic} {ins.op_str}")

        # Disassemble __k_4u_snd_sync_direct
        dir_val, dir_sz, _ = symbols['__k_4u_snd_sync_direct']
        raw_dir = sec_text.data()[dir_val:dir_val+dir_sz]
        print("\n--- __k_4u_snd_sync_direct disassembly ---")
        for ins in md_arm.disasm(raw_dir, dir_val):
            print(f"  {hex(ins.address)}: {ins.mnemonic} {ins.op_str}")
        
        # Also look for relocations in rodata if table is there
        rel_rodata = elf.get_section_by_name('.rel.rodata')
        if rel_rodata:
            print("\nRelocations in .rel.rodata:")
            for r in rel_rodata.iter_relocations():
                sym = symtab.get_symbol(r['r_info_sym'])
                print(f"  {hex(r['r_offset'])}: {sym.name}")

    print("\n=== PLT Relocations in libosal_uipc.so ===")
    with open(so_path, 'rb') as f:
        elf = ELFFile(f)
        rel = elf.get_section_by_name('.rel.plt')
        dynsym = elf.get_section_by_name('.dynsym')
        for r in rel.iter_relocations():
            sym = dynsym.get_symbol(r['r_info_sym'])
            print(f"  {hex(r['r_offset'])}: {sym.name}")

if __name__ == '__main__':
    analyze_uipc()
