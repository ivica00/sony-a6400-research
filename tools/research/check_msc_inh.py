with open('firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libSysDef.so', 'rb') as f:
    elf = f.read()

import struct

tbl_off = 0x0188b8 # file offset of sm_refTbl

# Active factors from dump_inh_factors.py
active_factors = [
  0, 4, 10, 23, 29, 170, 174, 176, 178, 422, 425, 461, 1278, 1289, 1290, 1291,
  1357, 1368, 1369, 1370, 1371, 1375, 1377, 1474, 1575, 1626, 1639, 1812,
  2270, 2271, 2272, 2282, 2937, 3046, 3054, 3347, 3452, 3508, 3510, 3732,
  3902, 3914, 4432, 4433
]

# For each factor, see how many features it inhibits
for fid in [1357, 1368, 1369, 1370, 1371, 1375, 1377, 2270, 2271, 2272, 2282, 4432, 4433]:
    w = fid // 32
    b = fid % 32
    inhibited_feats = []
    for feat in range(2190):
        row = tbl_off + feat * 640
        val = struct.unpack('<I', elf[row + w*4 : row + (w+1)*4])[0]
        if (val >> b) & 1:
            inhibited_feats.append(feat)
    print(f"Factor 0x{fid:04x} ({fid}) inhibits {len(inhibited_feats)} features: {inhibited_feats[:10]}")
