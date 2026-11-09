import struct

with open('artifacts/hardware/av-cam-camera-original.bin', 'rb') as f:
    data = f.read()

base_addr = 0x635c6000

targets = [0x01670464, 0x0167046a, 0x01670468, 0x01670469, 0x0167046b, 0x0167046c]

for t in targets:
    needle = struct.pack('<I', t)
    pos = 0
    print(f"=== Needle {hex(t)} ===")
    while True:
        pos = data.find(needle, pos)
        if pos == -1:
            break
        addr = base_addr + pos
        print(f"  Found at offset 0x{pos:x} (addr 0x{addr:x})")
        pos += 4
