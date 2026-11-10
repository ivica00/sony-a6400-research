"""Bounded original ARM callback completion controls; no device access.

Only queue lookup, locks and re-dispatch are fixture boundaries. All stores
inside finish_callback execute original hash-checked kernel-module bytes.
"""
import hashlib
import json
import struct
from pathlib import Path

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn import arm_const as arm

from project_paths import PROJECT_ROOT


def run_controls():
    path = PROJECT_ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/osal_uipc.ko'
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != '3743275bc964a2804b80cde4f589f60876b795fbeeccd3cbf2c18a0da2dc8567':
        raise ValueError('Module identity changed')
    with path.open('rb') as stream:
        elf = ELFFile(stream)
        code = elf.get_section_by_name('.text').data()
        symbols = elf.get_section_by_name('.symtab')
        finish = next(s for s in symbols.iter_symbols() if s.name == 'finish_callback')
        relocs = {r['r_offset']: symbols.get_symbol(r['r_info_sym']).name
                  for r in elf.get_section_by_name('.rel.text').iter_relocations()}
    rows = []
    for queue_flags in (0, 2, 8, 10):
        mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        base, data, stop = 0x100000, 0x200000, 0x300000
        mu.mem_map(base, (len(code) + 4095) & ~4095)
        mu.mem_write(base, code)
        mu.mem_map(data, 0x4000)
        mu.mem_map(stop, 0x1000)
        cb, queue, raw_message = data, data + 0x100, data + 0x200
        mu.mem_write(cb + 0xc, struct.pack('<BBH', 1, 8, 0x2da))
        mu.mem_write(queue + 4, bytes([queue_flags]))
        mu.mem_write(raw_message, struct.pack('<IBBHI', 0, 0, 1, 1, 0xa5a5a5a5))
        writes, calls = [], []

        def on_code(uc, address, size, _):
            offset = address - base
            # Original local lookup and re-dispatch entry offsets, verified
            # by BL instructions at .text+0x4170 and +0x42b8 respectively.
            if offset == 0x2330:
                calls.append('fixture_queue_lookup')
                uc.reg_write(arm.UC_ARM_REG_R0, queue)
                uc.reg_write(arm.UC_ARM_REG_PC, uc.reg_read(arm.UC_ARM_REG_LR))
            elif offset == 0x2d10:
                calls.append('fixture_redispatch_boundary')
                uc.reg_write(arm.UC_ARM_REG_PC, uc.reg_read(arm.UC_ARM_REG_LR))
            elif offset in relocs:
                name = relocs[offset]
                if name not in ('osal_lock', 'osal_unlock'):
                    raise RuntimeError('Unsupported original call: ' + name)
                calls.append('fixture_' + name)
                # Skip only the relocation's call instruction, not its caller.
                uc.reg_write(arm.UC_ARM_REG_PC, address + 4)

        def on_write(uc, access, address, size, value, _):
            if data <= address < data + 0x300:
                writes.append({'address': address, 'size': size, 'value': value})

        mu.hook_add(UC_HOOK_CODE, on_code)
        mu.hook_add(UC_HOOK_MEM_WRITE, on_write)
        mu.reg_write(arm.UC_ARM_REG_SP, data + 0x3800)
        mu.reg_write(arm.UC_ARM_REG_LR, stop)
        mu.reg_write(arm.UC_ARM_REG_R0, cb)
        mu.reg_write(arm.UC_ARM_REG_R1, raw_message)
        mu.emu_start(base + finish['st_value'], stop, count=256)
        if mu.reg_read(arm.UC_ARM_REG_PC) != stop:
            raise RuntimeError('Original function did not return within bound')
        expected = [{'address': cb + 0xc, 'size': 1, 'value': 0},
                    {'address': queue + 4, 'size': 1, 'value': queue_flags & ~2}]
        if writes != expected or bytes(mu.mem_read(raw_message + 6, 2)) != b'\x01\x00':
            raise AssertionError('Unexpected original ownership side effect')
        rows.append({'queue_flags': queue_flags, 'writes': writes, 'calls': calls,
                     'message_refcount_after': 1, 'returned': True})
    return {'input': str(path.relative_to(PROJECT_ROOT)), 'sha256': digest,
            'scope': 'original finish_callback with explicit helper fixtures; non-broadcast only',
            'cases': rows}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error('Use a new report path')
    result = run_controls()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(f"{len(result['cases'])} original ARM completion controls passed")
