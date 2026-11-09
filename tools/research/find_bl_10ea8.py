import struct

lib = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libInfraStreamingServer.so'
with open(lib, 'rb') as f:
    data = f.read()

target = 0x10ea8
for i in range(0, len(data) - 4, 2):
    w1, w2 = struct.unpack_from('<HH', data, i)
    if (w1 & 0xf800) == 0xf000 and (w2 & 0xd000) == 0xd000:
        s = (w1 >> 10) & 1
        imm10 = w1 & 0x3ff
        j1 = (w2 >> 13) & 1
        j2 = (w2 >> 11) & 1
        imm11 = w2 & 0x7ff
        i1 = ~(j1 ^ s) & 1
        i2 = ~(j2 ^ s) & 1
        imm32 = (s << 24) | (i1 << 23) | (i2 << 22) | (imm10 << 12) | (imm11 << 1)
        if imm32 & (1 << 24):
            imm32 -= (1 << 25)
        pc = i + 4
        dest = (pc + imm32) & 0xffffffff
        if dest == target:
            print(f"BL to 0x10ea8 from addr 0x{i:x}")
