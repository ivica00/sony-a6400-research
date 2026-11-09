with open('firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libUsbControl.so', 'rb') as f:
    data = f.read()

import struct

target = 0x1398a
for off in range(0, len(data)-4, 2):
    v = struct.unpack('<I', data[off:off+4])[0]
    if v == target:
        print(f"Ref to MSGID_SETCONFIG_MASSSTORAGE_EVT at 0x{off:x}")
        # print surrounding
        print(data[off-16:off+16].hex())
