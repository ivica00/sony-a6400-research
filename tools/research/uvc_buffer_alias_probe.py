"""Execute original UVC header stores to check source/destination aliasing."""
import hashlib
import json
from pathlib import Path

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM
from unicorn.arm_const import UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R8

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / 'firmware/extracted_zve10_v203_linuxnames/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/usbg_video.ko'
SHA = 'd385a051bf01b0e5ea37412623ae85cfe3cda76ab0d11e61d111994ca9fbf4fb'


def main():
    if hashlib.sha256(REFERENCE.read_bytes()).hexdigest() != SHA:
        raise ValueError('Reference module identity mismatch')
    with REFERENCE.open('rb') as stream:
        code = ELFFile(stream).get_section_by_name('.text').data()[0xf40:0xf50]
    results = []
    for source in (0x20000000, 0x20120000):
        cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        cpu.mem_map(0x100000, 4096)
        cpu.mem_write(0x100000, code)
        cpu.mem_map(0x20000000, 0x144000)
        cpu.mem_write(source, b'\xff\xd8')
        cpu.reg_write(UC_ARM_REG_R5, 0x20000000)
        cpu.reg_write(UC_ARM_REG_R6, 12)
        cpu.reg_write(UC_ARM_REG_R8, 0)
        cpu.emu_start(0x100000, 0x100010, count=4)
        prefix = bytes(cpu.mem_read(source, 2))
        preserved = prefix == b'\xff\xd8'
        assert preserved == (source != 0x20000000)
        results.append({'jpeg_source': hex(source), 'destination': '0x20000000',
                        'source_prefix_after_header': prefix.hex(),
                        'jpeg_soi_preserved': preserved})
    # The 29,452-byte test image fits outside both destination payloads.
    length, half, source_offset = 29452, 1294 * 1024 // 2, 0x120000
    assert half + length + 12 <= source_offset
    assert source_offset + length <= 1294 * 1024
    out = ROOT / 'artifacts/analysis/uvc-buffer-alias-e0143.json'
    out.write_text(json.dumps({'reference_sha256': SHA, 'original_text_range':
                              '0xf40..0xf50', 'controls': results,
                              'camera_access': False}, indent=2), encoding='utf-8')
    print('Original header-store controls passed: alias corrupts SOI; disjoint source preserves SOI')


if __name__ == '__main__':
    main()
