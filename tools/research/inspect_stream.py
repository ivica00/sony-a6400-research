with open('firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libInfraStreamingServer.so', 'rb') as f:
    elf = f.read()

import struct

dynsym_off = 0x0e68
dynsym_sz = 0x2700
dynstr_off = 0x3568

for i in range(dynsym_sz // 16):
    sym = elf[dynsym_off + i*16 : dynsym_off + (i+1)*16]
    st_name, st_value, st_size, st_info, st_other, st_shndx = struct.unpack('<IIIBBH', sym)
    name = elf[dynstr_off + st_name : elf.find(b'\x00', dynstr_off + st_name)].decode(errors='ignore')
    if any(k in name for k in ['_Scalar', 'FromStreamingServer', 'ScalarIf']):
        print(f"0x{st_value:08x} (sz={st_size}): {name}")
