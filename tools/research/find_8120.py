import struct

with open('artifacts/hardware/av-cam-camera-original.bin', 'rb') as f:
    data = f.read()

base_addr = 0x635c6000

# Search for 0x8120 in code (movw rX, #0x8120: f248 1X20)
# or data: 0x8120 as 16-bit little endian: \x20\x81
needle = b'\x20\x81'
pos = 0
found = []
while True:
    pos = data.find(needle, pos)
    if pos == -1: break
    addr = base_addr + pos
    found.append((pos, addr))
    pos += 2

print(f"Total occurrences of 0x8120: {len(found)}")
for pos, addr in found[:25]:
    print(f"  Offset 0x{pos:x} (addr 0x{addr:x})")
