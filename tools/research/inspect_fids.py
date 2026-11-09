with open('artifacts/hardware/av-cam-camera-original.bin', 'rb') as f:
    d = f.read()

import struct

for fid in [0x0558, 0x08de, 0x08ea, 0x00aa, 0x085a, 0x085b]:
    print(f"Searching factor 0x{fid:04x} in av-cam-camera-original.bin...")
    count = 0
    for off in range(0, len(d)-4, 2):
        hw1, hw2 = struct.unpack('<HH', d[off:off+4])
        if (hw1 & 0xfbf0) == 0xf240 and (hw2 & 0x7000) == 0:
            imm = ((hw1 & 0xf) << 12) | (((hw1 >> 10) & 1) << 11) | (((hw2 >> 12) & 7) << 8) | (hw2 & 0xff)
            if imm == fid:
                rd = (hw2 >> 8) & 0xf
                print(f"  movw r{rd}, #0x{fid:04x} at file offset 0x{off:x}")
                count += 1
                if count >= 5: break
