"""Offline original-ARM checks of stillimage START endpoint request tags.

The three slices execute before their virtual allocator calls. Explicit
scratch-register fixtures prove only the bytes stored by original code.
No fabricated allocator returns, physical camera calls, or USB activation.
"""
import argparse
import hashlib
import io
import json
import struct
from pathlib import Path

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R4, UC_ARM_REG_R6, UC_ARM_REG_R8

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/usbg_stillimage.ko'


def probe():
    raw = MODULE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != 'd4843c6abac908881ef5a96fd570fb345f766fff9ee562413f5f63e9cc7e0ff9':
        raise ValueError('Original stillimage module identity mismatch')
    elf = ELFFile(io.BytesIO(raw))
    symbol = next(s for s in elf.get_section_by_name('.symtab').iter_symbols()
                  if s.name == 'core_cb_start')
    if (symbol['st_value'], symbol['st_size']) != (0xb70, 400):
        raise ValueError('Unexpected original core_cb_start layout')
    code = elf.get_section_by_name('.text').data()
    results = []
    for name, start, stop, field, expected in [
        ('bulk-in', 0xbe4, 0xbf8, 0x14, 0x81),
        ('bulk-out', 0xc24, 0xc38, 0x1c, 0x02),
        ('interrupt-in', 0xc64, 0xc78, 0x24, 0x83),
    ]:
        cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        cpu.mem_map(0x100000, 0x4000)
        cpu.mem_write(0x100000, code)
        cpu.mem_map(0x200000, 0x1000)
        cpu.mem_write(0x200000, b'\xa5' * 0x1000)
        cpu.reg_write(UC_ARM_REG_R4, 0x200000)
        cpu.reg_write(UC_ARM_REG_R6, 0)
        cpu.reg_write(UC_ARM_REG_R8, 0x300000)
        cpu.emu_start(0x100000 + start, 0x100000 + stop, count=16)
        stored = bytes(cpu.mem_read(0x200000 + field, 3))
        if stored != bytes([expected, 0, 0]):
            raise AssertionError((name, stored.hex()))
        results.append(dict(name=name, source_offset=hex(start),
            stop_before_indirect_call_setup=hex(stop), request_field=hex(field),
            endpoint=hex(expected), bytes=stored.hex(), passed=True))
    kernel_path = ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
    kernel = kernel_path.read_bytes()
    kernel_sha = '12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707'
    if hashlib.sha256(kernel).hexdigest() != kernel_sha:
        raise ValueError('Original kernel identity mismatch')
    lookup = 0x602b23ec  # straight-line body of dwc3_wIndex_to_dep
    mapping = []
    for address, offset in [(0x81, 0xdc), (0x02, 0xe0), (0x83, 0xec), (0x84, 0xf4)]:
        for enabled in (False, True):
            cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
            cpu.mem_map(0x602b2000, 0x1000)
            cpu.mem_write(lookup, kernel[lookup-0x60108000:0x602b2410-0x60108000])
            cpu.mem_map(0x200000, 0x2000)
            cpu.mem_write(0x200000 + offset, struct.pack('<I', 0x201000))
            cpu.mem_write(0x20104c, struct.pack('<I', int(enabled)))
            cpu.reg_write(UC_ARM_REG_R0, 0x200000)
            cpu.reg_write(UC_ARM_REG_R1, address)
            cpu.emu_start(lookup, 0x602b2410, count=16)
            expected = 0x201000 if enabled else 0
            if cpu.reg_read(UC_ARM_REG_R0) != expected:
                raise AssertionError('Original DWC endpoint lookup')
            mapping.append(dict(address=hex(address), dwc_slot_offset=hex(offset),
                fixture_enabled=enabled, passed=True))
    return dict(source=str(MODULE.relative_to(ROOT)),
        source_sha256=hashlib.sha256(raw).hexdigest(), controls=results,
        kernel_sha256=kernel_sha, original_dwc_lookup_controls=mapping,
        camera_access=False, deployed=False,
        limitations=['Explicit scratch-register fixtures; only original straight-line stores are executed.',
                    'Does not prove complete START, allocator success, live module byte equality, or combined UVC/PTP operation.',
                    'DWC endpoint slots/enabled flags are explicit fixtures. EP 0x84 lookup does not prove that hardware has allocated or supports that endpoint.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = probe()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
