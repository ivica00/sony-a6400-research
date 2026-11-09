import capstone

with open('firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libInfraRemote.so', 'rb') as f:
    elf = f.read()

# Let's find UsbCtrl_ConfigureFunc and UsbCtrl_StartFunc addresses
import struct

dynsym_off = 0x0ae0
e_shoff, e_flags, e_ehsize, e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx = struct.unpack('<IIHHHHHH', elf[32:52])
shdr = []
for i in range(e_shnum):
    sh = elf[e_shoff + i*e_shentsize : e_shoff + (i+1)*e_shentsize]
    sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size, sh_link, sh_info, sh_addralign, sh_entsize = struct.unpack('<IIIIIIIIII', sh)
    shdr.append({'name_idx': sh_name, 'link': sh_link, 'entsize': sh_entsize, 'offset': sh_offset, 'size': sh_size})

shstrtab = elf[shdr[e_shstrndx]['offset'] : shdr[e_shstrndx]['offset'] + shdr[e_shstrndx]['size']]
for s in shdr:
    s['name'] = shstrtab[s['name_idx'] : shstrtab.find(b'\x00', s['name_idx'])].decode()

dynsym = next(s for s in shdr if s['name'] == '.dynsym')
dynstr = elf[shdr[dynsym['link']]['offset'] : shdr[dynsym['link']]['offset'] + shdr[dynsym['link']]['size']]

md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)

for i in range(dynsym['size'] // dynsym['entsize']):
    sym = elf[dynsym['offset'] + i*dynsym['entsize'] : dynsym['offset'] + (i+1)*dynsym['entsize']]
    st_name, st_value, st_size, st_info, st_other, st_shndx = struct.unpack('<IIIBBH', sym)
    name = dynstr[st_name : dynstr.find(b'\x00', st_name)].decode()
    if 'UsbCtrl_' in name:
        print(f"=== {name} at 0x{st_value:08x} (sz={st_size}) ===")
        code = elf[st_value & ~1 : (st_value & ~1) + st_size]
        for insn in md.disasm(code, st_value & ~1):
            print(f"  0x{insn.address:08x}: {insn.mnemonic} {insn.op_str}")
