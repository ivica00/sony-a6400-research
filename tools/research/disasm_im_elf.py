import capstone
from elftools.elf.elffile import ELFFile

libobj_path = r"firmware\extracted_a6400\firmware.tar_unpacked\0700_part_image\dev\nflasha15_unpacked\lib\libObj.so"

with open(libobj_path, "rb") as f:
    elffile = ELFFile(f)
    text_sec = elffile.get_section_by_name(".text")
    text_addr = text_sec["sh_addr"]
    text_data = text_sec.data()

md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)

offset = 0x72baf0 - 0x60 - text_addr
data = text_data[offset : offset + 0x80]

for insn in md.disasm(data, 0x72baf0 - 0x60):
    print(f"0x{insn.address:08x}:  {insn.mnemonic:10s} {insn.op_str}")
