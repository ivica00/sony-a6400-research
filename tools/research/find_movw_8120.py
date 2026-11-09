import struct

with open('artifacts/hardware/av-cam-camera-original.bin', 'rb') as f:
    data = f.read()

base_addr = 0x635c6000

for i in range(0, len(data) - 4, 2):
    w1, w2 = struct.unpack_from('<HH', data, i)
    if (w1 & 0xfff0) == 0xf240 and (w1 & 0x000f) == 8: # movw rX, #0x8...
        imm4 = (w1 >> 0) & 0xf
        imm3 = (w2 >> 12) & 0x7
        imm8 = w2 & 0xff
        val = (imm4 << 12) | (imm3 << 8) | imm8
        if val == 0x8120:
            reg = (w2 >> 8) & 0xf
            addr = base_addr + i
            print(f"movw r{reg}, #0x8120 at offset 0x{i:x} (addr 0x{addr:x})")
