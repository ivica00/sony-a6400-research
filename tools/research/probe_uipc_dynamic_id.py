"""Original ARM dynamic-ID controls with explicit lookup/lock/bit-scan fixtures."""
import hashlib
import json
import struct
from pathlib import Path

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import arm_const as arm

from project_paths import PROJECT_ROOT


def run_controls():
    path = PROJECT_ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/osal_uipc.ko'
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if sha != '3743275bc964a2804b80cde4f589f60876b795fbeeccd3cbf2c18a0da2dc8567':
        raise ValueError('Module identity changed')
    with path.open('rb') as stream:
        elf = ELFFile(stream)
        text = elf.get_section_by_name('.text').data()
        data = elf.get_section_by_name('.data').data()
        syms = elf.get_section_by_name('.symtab')
        relocations = {r['r_offset']: syms.get_symbol(r['r_info_sym']).name
                       for r in elf.get_section_by_name('.rel.text').iter_relocations()}
    mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    code_base, data_base, bitmap_base, fixture, stop = 0x100000, 0x200000, 0x300000, 0x400000, 0x500000
    for address in (code_base, data_base, bitmap_base, fixture, stop):
        mu.mem_map(address, 0x10000)
    mu.mem_write(code_base, text)
    mu.mem_write(data_base, data)
    # Apply the original ABS32 section relocations used by this function.
    for literal in (0x46a8, 0x46ac):
        addend = struct.unpack_from('<I', text, literal)[0]
        mu.mem_write(code_base + literal, struct.pack('<I', data_base + addend))
    for descriptor in (0x16c, 0x17c, 0x18c):
        addend = struct.unpack_from('<I', data, descriptor + 12)[0]
        mu.mem_write(data_base + descriptor + 12, struct.pack('<I', bitmap_base + addend))
    queue, sem, output = fixture, fixture + 0x100, fixture + 0x200
    mu.mem_write(queue + 4, b'\x08')
    calls = []

    def on_code(uc, address, size, _):
        offset = address - code_base
        if offset in (0x2330, 0x24c8):
            calls.append('fixture_queue_lookup')
            uc.reg_write(arm.UC_ARM_REG_R0, queue)
            uc.reg_write(arm.UC_ARM_REG_PC, uc.reg_read(arm.UC_ARM_REG_LR))
        elif offset in relocations:
            name = relocations[offset]
            if name == '_find_first_zero_bit_le':
                word = struct.unpack('<I', uc.mem_read(uc.reg_read(arm.UC_ARM_REG_R0), 4))[0]
                zero = next(i for i in range(32) if not word & (1 << i))
                uc.reg_write(arm.UC_ARM_REG_R0, zero)
            elif name == 'get_bsem':
                uc.reg_write(arm.UC_ARM_REG_R0, sem)
            elif name == 'osal_set_msgq_broadcast_mode':
                uc.mem_write(queue + 4, b'\x09')
                uc.reg_write(arm.UC_ARM_REG_R0, 0)
            elif name not in ('osal_lock', 'osal_unlock'):
                raise RuntimeError('Unsupported original helper: ' + name)
            calls.append('fixture_' + name)
            uc.reg_write(arm.UC_ARM_REG_PC, address + 4)

    mu.hook_add(UC_HOOK_CODE, on_code)
    rows = []
    cases = [(0x2a, 0x3f, output, 0, 0x3f6000),
             (2, 0x3f, output, 0, 0x3f6001),
             (0x42, 0, 0x3f6000, 0, None),
             (2, 0x77, output, 0, 0x776000),
             (0x12, 0x88, output, 0, 0x886000),
             (6, 0x55, output, 0, 0x557000),
             (0, 1, output, 0xfffffc00, None),
             (2, 1, 0, 0xfffffc00, None)]
    for kind, key, arg, expected_result, expected_id in cases:
        mu.reg_write(arm.UC_ARM_REG_SP, fixture + 0xf000)
        mu.reg_write(arm.UC_ARM_REG_LR, stop)
        mu.reg_write(arm.UC_ARM_REG_R0, kind)
        mu.reg_write(arm.UC_ARM_REG_R1, key)
        mu.reg_write(arm.UC_ARM_REG_R2, arg)
        mu.emu_start(code_base + 0x4440, stop, count=512)
        result = mu.reg_read(arm.UC_ARM_REG_R0)
        value = struct.unpack('<I', mu.mem_read(output, 4))[0]
        if (mu.reg_read(arm.UC_ARM_REG_PC) != stop or result != expected_result
                or expected_id is not None and value != expected_id):
            raise AssertionError('Original dynamic-ID control failed')
        rows.append({'type': kind, 'key': key, 'argument': arg, 'result': result,
                     'allocated_id': value if expected_id is not None else None})
    return {'source': str(path.relative_to(PROJECT_ROOT)), 'sha256': sha,
            'scope': 'original arithmetic/bitmap stores; lookup, locks and bit-scan are explicit fixtures',
            'cases': rows, 'fixture_calls': calls}


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
    print(f"{len(result['cases'])} original ARM dynamic-ID controls passed")
