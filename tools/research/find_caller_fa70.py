import struct

with open('artifacts/hardware/av-cam-camera-original.bin', 'rb') as f:
    data = f.read()

base_addr = 0x635c6000

for target in [0x63a8fa71, 0x63a8fa70]:
    needle = struct.pack('<I', target)
    pos = 0
    while True:
        pos = data.find(needle, pos)
        if pos == -1: break
        addr = base_addr + pos
        print(f"Target {hex(target)} found at offset 0x{pos:x} (addr 0x{addr:x})")
        pos += 4
