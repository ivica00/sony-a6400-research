with open('firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libSysDef.so', 'rb') as f:
    elf = f.read()

import struct

tbl_off = 0x0188b8

factor_85a = 2138
factor_85b = 2139

w_85a = factor_85a // 32
bit_85a = factor_85a % 32

w_85b = factor_85b // 32
bit_85b = factor_85b % 32

print(f"Factor 0x85a ({factor_85a}): word {w_85a}, bit {bit_85a}")
print(f"Factor 0x85b ({factor_85b}): word {w_85b}, bit {bit_85b}")

features_85a = []
features_85b = []

for feat_id in range(2190):
    row_off = tbl_off + feat_id * 640
    val_85a = struct.unpack('<I', elf[row_off + w_85a*4 : row_off + (w_85a+1)*4])[0]
    if (val_85a >> bit_85a) & 1:
        features_85a.append(feat_id)
    val_85b = struct.unpack('<I', elf[row_off + w_85b*4 : row_off + (w_85b+1)*4])[0]
    if (val_85b >> bit_85b) & 1:
        features_85b.append(feat_id)

print(f"Features inhibited when Factor 0x85a=1: count={len(features_85a)} -> {features_85a[:20]}")
print(f"Features inhibited when Factor 0x85b=1: count={len(features_85b)} -> {features_85b[:20]}")
