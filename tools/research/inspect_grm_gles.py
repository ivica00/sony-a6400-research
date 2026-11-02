from elftools.elf.elffile import ELFFile

ko_path = r"firmware\extracted_a6400\firmware.tar_unpacked\0700_part_image\dev\nflasha15_unpacked\kmod\grm_gles.ko"

with open(ko_path, "rb") as f:
    elf = ELFFile(f)
    rel_text = elf.get_section_by_name('.rel.text')
    symtab = elf.get_section_by_name('.symtab')
    for rel in rel_text.iter_relocations():
        if 0xad0 <= rel['r_offset'] < 0xc00:
            sym = symtab.get_symbol(rel['r_info_sym'])
            print(f"0x{rel['r_offset']:x} -> {sym.name}")
