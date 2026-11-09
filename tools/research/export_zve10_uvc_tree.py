"""Extract and generate exact byte-for-byte ZV-E10 UVC descriptor tree in C.
Extracts every node and writes tools/native_camera/zve10_uvc_tree.h
"""

import struct
from pathlib import Path
from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parents[2]
SO_PATH = ROOT / 'firmware/extracted_zve10_v203_linuxnames/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libInfraUsbCmn.so'

elf = ELFFile(SO_PATH.open('rb'))

def get_bytes(va, sz):
    for sec in elf.iter_sections():
        if sec['sh_addr'] <= va < sec['sh_addr'] + sec['sh_size']:
            off = va - sec['sh_addr']
            return sec.data()[off:off+sz]
    return b'\x00' * sz

def c_hex(byte_data):
    lines = []
    for i in range(0, len(byte_data), 16):
        chunk = byte_data[i:i+16]
        hex_bytes = ', '.join(f"0x{b:02x}" for b in chunk)
        lines.append(f"    {hex_bytes},")
    return '\n'.join(lines)

# All nodes to extract:
nodes = {
    'tbl_88': (0x1ccfc, 88),
    'fs_cfg': (0x1d4a4, 24),
    'hs_cfg': (0x1d4bc, 24),
    'ss_cfg': (0x1d4d4, 24),
    'ntsc_iface': (0x1cc60, 96),
    'sub_1cd90': (0x1cd90, 20),
    'sub_1cda4': (0x1cda4, 20),
    'sub_1cbac': (0x1cbac, 20),
    'sub_1cbc0': (0x1cbc0, 40),
    'sub_1cdcc': (0x1cdcc, 20),
    'sub_1cde0': (0x1cde0, 20),
    'sub_1cbe8': (0x1cbe8, 20),
    'sub_1cbfc': (0x1cbfc, 40),
    'sub_1ce08': (0x1ce08, 20),
    'sub_1ce1c': (0x1ce1c, 20),
    'sub_1cc24': (0x1cc24, 20),
    'sub_1cc38': (0x1cc38, 40),
    'ep_fs': (0x1ccc0, 20),
    'ep_hs': (0x1ccd4, 20),
    'ep_ss': (0x1cce8, 20),
    'ep_1cd54': (0x1cd54, 20),
    'ep_1cd68': (0x1cd68, 20),
    'ep_1cd7c': (0x1cd7c, 20),
    'ca90': (0x1ca90, 80),
    'desc_12530': (0x12530, 8),
    'desc_12537': (0x12537, 61),
    'desc_12574': (0x12574, 20),
    'desc_12588': (0x12588, 4),
    'desc_1258c': (0x1258c, 12),
    'desc_12598': (0x12598, 40),
    'desc_125c0': (0x125c0, 30),
    'desc_125de': (0x125de, 4),
    'desc_125e2': (0x125e2, 4),
    'desc_12625': (0x12625, 61),
    'strings_1e3d4': (0x1e3d4, 128),
    'str1': (0x125e6, 8),
    'str2': (0x125ee, 40),
    'str3': (0x12616, 16),
}

header_lines = [
    "/* Auto-generated ZV-E10 UVC Descriptor Tree. */",
    "#ifndef ZVE10_UVC_TREE_H",
    "#define ZVE10_UVC_TREE_H",
    "",
]

for name, (va, sz) in nodes.items():
    data = get_bytes(va, sz)
    header_lines.append(f"static const unsigned char s_{name}_template[{sz}] = {{")
    header_lines.append(c_hex(data))
    header_lines.append("};\n")

header_lines.append("#endif /* ZVE10_UVC_TREE_H */\n")

out_path = ROOT / 'tools/native_camera/zve10_uvc_tree.h'
out_path.write_text('\n'.join(header_lines), encoding='utf-8')
print(f"Generated {out_path} ({len(nodes)} descriptor nodes)")
