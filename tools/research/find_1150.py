import struct, glob

for p in ['artifacts/hardware/av-cam-camera-original.bin'] + glob.glob('firmware/extracted_a6400/**/*.so', recursive=True):
    with open(p, 'rb') as f:
        d = f.read()
    for fid in [0x1150, 0x1151]:
        for off in range(0, len(d)-4, 2):
            hw1, hw2 = struct.unpack('<HH', d[off:off+4])
            if (hw1 & 0xfbf0) == 0xf240 and (hw2 & 0x7000) == 0:
                imm = ((hw1 & 0xf) << 12) | (((hw1 >> 10) & 1) << 11) | (((hw2 >> 12) & 7) << 8) | (hw2 & 0xff)
                if imm == fid:
                    rd = (hw2 >> 8) & 0xf
                    print(f"Found factor 0x{fid:04x} in {p} at 0x{off:x} (r{rd})")
