with open('firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libSysDef.so', 'rb') as f:
    data = f.read()

# find "ObjRemote\0"
idx = data.find(b'ObjRemote\x00')
print("ObjRemote at:", hex(idx))

# find all references to idx
import struct
for off in range(0, len(data)-4, 4):
    val = struct.unpack('<I', data[off:off+4])[0]
    if val == idx:
        print(f"Ref to ObjRemote at 0x{off:x}: surrounding {data[off-8:off+12].hex()}")
        # print preceding uint
        prev_val = struct.unpack('<I', data[off-4:off])[0]
        print(f"  Preceding uint: 0x{prev_val:08x}")
