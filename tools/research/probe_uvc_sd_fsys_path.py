"""Offline execution of the original Fsys path resolver and 8.3 normalizer."""
import hashlib, io, json, struct
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from tools.research.arm_plt import resolve_arm_plt
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT

LIB = ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libInfraFsys.so'
SHA = '75f24fd03f4a187563622d6320f0690108fa6e231ac6e84cbda9303b8dc9af2c'
RETURN = 0x300000
STACK = 0x20f000
DRIVE = 0x210000
PATHBUF = 0x220000
OUTBUF = 0x230000
G_FSYS = 0xa9998


def build_uc():
    raw = LIB.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SHA
    elf = ELFFile(io.BytesIO(raw))
    symbols = {s.name: s['st_value'] for s in elf.get_section_by_name('.dynsym').iter_symbols() if s.name}
    plt = resolve_arm_plt(elf)
    c = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    c.mem_map(0, 0xc0000)
    c.mem_map(0x200000, 0x40000)
    c.mem_map(RETURN, 0x1000)
    for segment in elf.iter_segments():
        if segment['p_type'] == 'PT_LOAD':
            c.mem_write(segment['p_vaddr'], segment.data())
    dynsym = elf.get_section_by_name('.dynsym')
    for name in ('.rel.dyn', '.rel.plt'):
        for relocation in elf.get_section_by_name(name).iter_relocations():
            if relocation['r_info_type'] in (21, 22):
                symbol = dynsym.get_symbol(relocation['r_info_sym'])
                c.mem_write(relocation['r_offset'], struct.pack('<I', symbol['st_value']))
    return c, elf, symbols, plt


def drive_fixture(c):
    c.mem_write(DRIVE, bytes(0x1000))
    c.mem_write(DRIVE + 10, b'A')
    c.mem_write(DRIVE + 0x973, bytes([10]))
    c.mem_write(DRIVE + 0x9c0, struct.pack('<H', 10))
    c.mem_write(DRIVE + 0x974, b'/dev/mmca\0')


def run_normalizer(path):
    c, elf, symbols, plt = build_uc()
    drive_fixture(c)
    c.mem_write(0x200000, bytes(0x20000))
    c.mem_write(PATHBUF, path.encode() + b'\0')
    c.mem_write(OUTBUF, b'\xee' * 256)
    start = symbols['fsys_CreatePathInfo'] & ~1
    end = start + next(s for s in elf.get_section_by_name('.dynsym').iter_symbols() if s.name == 'fsys_CreatePathInfo')['st_size']
    returned = []; bad = []; last = []
    from unicorn import UC_HOOK_MEM_WRITE_UNMAPPED
    def memhook(uc, access, address, size, value, user):
        bad.append((address, size)); return False
    c.hook_add(UC_HOOK_MEM_WRITE_UNMAPPED, memhook)
    def hook(cpu, address, size, unused):
        last.append(address)
        if len(last) > 8: last.pop(0)
        if address == RETURN:
            returned.append(cpu.reg_read(UC_ARM_REG_R0)); cpu.emu_stop(); return
        if address in plt:
            name = plt[address]['name']
            if name == 'memcpy':
                dst = cpu.reg_read(UC_ARM_REG_R0); src = cpu.reg_read(UC_ARM_REG_R1); count = cpu.reg_read(UC_ARM_REG_R2)
                c.mem_write(dst, bytes(c.mem_read(src, count)))
                cpu.reg_write(UC_ARM_REG_R0, dst); cpu.reg_write(UC_ARM_REG_PC, cpu.reg_read(UC_ARM_REG_LR)); return
            if name == 'memset':
                dst = cpu.reg_read(UC_ARM_REG_R0); value = cpu.reg_read(UC_ARM_REG_R1) & 0xff; count = cpu.reg_read(UC_ARM_REG_R2)
                c.mem_write(dst, bytes([value]) * count)
                cpu.reg_write(UC_ARM_REG_R0, dst); cpu.reg_write(UC_ARM_REG_PC, cpu.reg_read(UC_ARM_REG_LR)); return
            raise RuntimeError('unexpected service ' + name)
        if not start <= address < end:
            raise RuntimeError(f'unexpected normalizer body {address:08x}')
    c.hook_add(UC_HOOK_CODE, hook)
    for reg, value in ((UC_ARM_REG_R0, DRIVE), (UC_ARM_REG_R1, PATHBUF), (UC_ARM_REG_R2, OUTBUF), (UC_ARM_REG_SP, STACK), (UC_ARM_REG_LR, RETURN)):
        c.reg_write(reg, value)
    try:
        c.emu_start(start | 1, 0xffffffff, count=20000)
    except Exception:
        print('normalizer fault pc', hex(c.reg_read(UC_ARM_REG_PC)), 'sp', hex(c.reg_read(UC_ARM_REG_SP)), 'bad', bad, 'last', [hex(x) for x in last])
        raise
    out = bytes(c.mem_read(OUTBUF, 48))
    return returned[0] if returned else None, out


def run_resolver(path, letter_record, device_record, device_id):
    c, elf, symbols, plt = build_uc()
    drive_fixture(c)
    table = [0] * 52
    if letter_record: table[0] = DRIVE
    if device_record: table[26] = DRIVE
    c.mem_write(G_FSYS, struct.pack('<52I', *table))
    c.mem_write(PATHBUF, path.encode() + b'\0')
    c.mem_write(OUTBUF, struct.pack('<I', 0xdeadbeef))
    start = symbols['fsys_GetDriveInfoFromPath'] & ~1
    end = start + next(s for s in elf.get_section_by_name('.dynsym').iter_symbols() if s.name == 'fsys_GetDriveInfoFromPath')['st_size']
    returned = []; calls = []
    def hook(cpu, address, size, unused):
        if address == RETURN:
            returned.append(cpu.reg_read(UC_ARM_REG_R0)); cpu.emu_stop(); return
        if address in plt:
            name = plt[address]['name']; calls.append(name)
            if name.startswith('fsysDepTrace_') or name.startswith('fsysDepLog_'):
                result = 0
            elif name == 'fsys_GetDeviceMutexId':
                result = 5
            elif name == 'fsysDep_LockDevice' or name == 'fsysDep_UnlockDevice':
                result = 0
            elif name == 'fsys_GetDeviceId':
                result = device_id
            else:
                raise RuntimeError('unexpected service ' + name)
            cpu.reg_write(UC_ARM_REG_R0, result); cpu.reg_write(UC_ARM_REG_PC, cpu.reg_read(UC_ARM_REG_LR)); return
        if not start <= address < end:
            raise RuntimeError(f'unexpected resolver body {address:08x}')
    c.hook_add(UC_HOOK_CODE, hook)
    for reg, value in ((UC_ARM_REG_R0, PATHBUF), (UC_ARM_REG_R1, OUTBUF), (UC_ARM_REG_SP, STACK), (UC_ARM_REG_LR, RETURN)):
        c.reg_write(reg, value)
    c.emu_start(start | 1, 0xffffffff, count=20000)
    out = struct.unpack('<I', bytes(c.mem_read(OUTBUF, 4)))[0]
    return returned[0] if returned else None, out, calls


def main():
    cases = []
    for name, path, expected in [
        ('letter-8.3', 'A:/A6400J.DAT', 1),
        ('letter-long-underscore', 'A:/a6400_journal_e0235.dat', 0),
        ('letter-8.3-underscore', 'A:/A6400_J.DAT', None),
        ('letter-8.3-lower', 'A:/a6400j.dat', None),
        ('letter-no-separator', 'A:A6400J.DAT', None),
        ('device-8.3', '/dev/mmca/A6400J.DAT', 1),
        ('device-long-underscore', '/dev/mmca/a6400_journal_e0235.dat', 0),
    ]:
        result, out = run_normalizer(path)
        ok = expected is None or result == expected
        cases.append(dict(kind='CreatePathInfo', name=name, path=path, result=result, expected=expected, ok=ok, out=out.hex()))
    resolver_cases = [
        ('letter-present', 'A:/A6400J.DAT', True, False, 0, 0, DRIVE),
        ('letter-empty', 'A:/A6400J.DAT', False, False, 0, 0x80000031, 0xdeadbeef),
        ('device-present', '/dev/mmca/A6400J.DAT', False, True, 0, 0, DRIVE),
        ('device-empty', '/dev/mmca/A6400J.DAT', False, False, 0, 0x80000041, 0xdeadbeef),
        ('device-unknown', '/dev/mmca/A6400J.DAT', False, True, -1, 0xffffffff, 0xdeadbeef),
        ('no-colon', 'A', True, False, 0, 0x80000041, 0xdeadbeef),
    ]
    for name, path, letter, device, device_id, expected, expected_out in resolver_cases:
        result, out, calls = run_resolver(path, letter, device, device_id)
        ok = result == expected and out == expected_out
        cases.append(dict(kind='GetDriveInfoFromPath', name=name, path=path, result=None if result is None else hex(result), expected=hex(expected), out=hex(out), expected_out=hex(expected_out), services=calls, ok=ok))
    outdir = ROOT / 'artifacts/analysis/uvc-sd-fsys-path-e0237'
    outdir.mkdir(parents=True, exist_ok=True)
    report = dict(status='offline_original_path_functions_passed' if all(x['ok'] for x in cases) else 'offline_path_cases_failed', source_sha256=SHA, cases=cases,
                  limitations=['Original ARM bodies execute with fixture drive record, device-id/mutex/lock service doubles and the library static character tables.', 'This is not a live volume, mount, file creation or write proof; the 0x80000041 physical failure is explained by path normalization, not by an executed journal.'])
    (outdir / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    for case in cases:
        print(f"{case['kind']:22s} {case['name']:28s} result={case['result']} expected={case['expected']} ok={case['ok']}")


if __name__ == '__main__':
    main()
