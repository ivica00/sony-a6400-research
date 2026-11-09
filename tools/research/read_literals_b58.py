import struct

with open('artifacts/hardware/av-cam-camera-original.bin', 'rb') as f:
    data = f.read()

base_addr = 0x635c6000
start = 0x63a90b58
offset = start - base_addr

for i in range(0, 32, 4):
    val = struct.unpack_from('<I', data, offset + i)[0]
    addr = start + i
    print(f"Literal at {hex(addr)}: {hex(val)}")
