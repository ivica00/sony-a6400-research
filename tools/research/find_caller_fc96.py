import struct

with open('artifacts/hardware/av-cam-camera-original.bin', 'rb') as f:
    data = f.read()

base_addr = 0x635c6000
target = 0x63a8fc96

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
        pc = base_addr + i + 4
        dest = (pc + imm32) & 0xffffffff
        if dest in (target, target - 2, target - 4, target - 6):
            print(f"BL to {hex(dest)} from addr 0x{base_addr + i:x}")
