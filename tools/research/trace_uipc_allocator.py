"""Bounded original trace allocator prefix; never supplies UIPC runtime state."""
import argparse
import io
import json
import struct

import unicorn
from unicorn import arm_const as arm
from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input
from tools.research.startup_trace import read_va, plt_symbols, arm_rotated_immediate, decode_block

LIBRARY = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libosal_uipc.so'
STACK = 0x08000000


def execute(raw):
    elf = ELFFile(io.BytesIO(raw))
    if (elf.elfclass, elf.little_endian, elf['e_machine'], elf['e_type']) != (32, True, 'EM_ARM', 'ET_DYN'):
        raise ValueError('Expected ARM32 dynamic library')
    symbols = {s.name: s for s in elf.get_section_by_name('.dynsym').iter_symbols()}
    if [(symbols[n]['st_value'], symbols[n]['st_size']) for n in ('osal_valloc_msg_wait', 'u_osal_valloc_msg_wait', 'uconf')] != [(0x3fed, 156), (0x2871, 88), (0xef80, 36)]:
        raise ValueError('Original allocator coordinates changed')
    plts = plt_symbols(elf)
    if plts.get(0x1984) != 'u_osal_valloc_msg_wait' or plts.get(0x17f8) != 'ioctl' or read_va(elf, raw, 0x1980, 2) != bytes.fromhex('7847'):
        raise ValueError('Original allocator veneer/import changed')
    first, second, third = struct.unpack('<3I', read_va(elf, raw, 0x1984, 12))
    jump = (0x198c + arm_rotated_immediate(first) + arm_rotated_immediate(second) + (third & 4095)) & 0xffffffff
    word = lambda a: struct.unpack('<I', read_va(elf, raw, a, 4))[0]
    slot = (word(0x28c0) + 0x2884 + word(0x28c4)) & 0xffffffff
    expected = {jump: (22, 'u_osal_valloc_msg_wait'), slot: (21, 'uconf')}
    found = {}
    for section in elf.iter_sections():
        if section['sh_type'] == 'SHT_REL':
            for relocation in section.iter_relocations():
                if relocation['r_offset'] in expected:
                    name = elf.get_section(section['sh_link']).get_symbol(relocation['r_info_sym']).name
                    address = relocation['r_offset']
                    if address in found:
                        raise ValueError('Ambiguous selected relocation')
                    found[address] = (relocation['r_info_type'], name)
    if found != expected:
        raise ValueError('Selected original relocations changed')
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_THUMB)
    mapped, known, written = set(), set(), set()
    def map_range(address, size):
        for page in range(address & ~4095, (address + size + 4095) & ~4095, 4096):
            if page not in mapped:
                mu.mem_map(page, 4096)
                mapped.add(page)
    for section in elf.iter_sections():
        if section['sh_flags'] & 2 and section['sh_type'] != 'SHT_NOBITS' and section['sh_size']:
            address, data = section['sh_addr'], section.data()
            map_range(address, len(data))
            mu.mem_write(address, data)
            if not section['sh_flags'] & 1:
                known.update(range(address, address + len(data)))
    for address, value in ((jump, 0x2871), (slot, 0xef80)):
        map_range(address, 4)
        mu.mem_write(address, struct.pack('<I', value))
        known.update(range(address, address + 4))
    map_range(STACK, 0x4000)
    report = {'status': 'running', 'trace': [], 'stack_writes': [],
              'bindings': {hex(jump): 'same-image u_osal_valloc_msg_wait', hex(slot): 'same-image uconf address only'},
              'input_arguments': [0x008f013a, STACK + 0x2fac, 42, 0],
              'assumptions': ['Isolated same-image symbol bindings and constructed call stack; no process transport execution.',
                              'Writable library state, including uconf, is unknown even if source bytes exist.']}
    def stop(reason, **details):
        report.update(status=reason, boundary={'pc': mu.reg_read(arm.UC_ARM_REG_PC), **details})
        mu.emu_stop()
    def code(uc, address, size, user):
        if not (0x3fec <= address < 0x4008 or 0x1980 <= address < 0x1990 or 0x2870 <= address <= 0x2898):
            stop('unsupported_code', address=address)
        elif not all(a in known for a in range(address, address + size)):
            stop('unknown_instruction_bytes', address=address)
        else:
            report['trace'].append(address)
    def memory(uc, access, address, size, value, user):
        if access == unicorn.UC_MEM_WRITE:
            if not STACK <= address or address + size > STACK + 0x4000:
                stop('unsupported_write', address=address, size=size)
            else:
                written.update(range(address, address + size))
                report['stack_writes'].append({'address': address, 'size': size, 'value': value})
        elif not all(a in known or a in written for a in range(address, address + size)):
            stop('unsupplied_runtime_read', address=address, size=size)
    mu.hook_add(unicorn.UC_HOOK_CODE, code)
    mu.hook_add(unicorn.UC_HOOK_MEM_READ | unicorn.UC_HOOK_MEM_WRITE, memory)
    mu.reg_write(arm.UC_ARM_REG_SP, STACK + 0x3000)
    mu.reg_write(arm.UC_ARM_REG_LR, 0x09000001)
    for register, value in zip((arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2, arm.UC_ARM_REG_R3), report['input_arguments']):
        mu.reg_write(register, value)
    try:
        mu.emu_start(0x3fed, 0, count=100, timeout=100000)
    except unicorn.UcError as error:
        if report['status'] == 'running':
            report.update(status='execution_fault', error=str(error))
    if report['status'] == 'running':
        report['status'] = 'timeout' if mu.query(unicorn.UC_QUERY_TIMEOUT) else 'instruction_limit'
    frame = mu.reg_read(arm.UC_ARM_REG_R7)
    if all(a in written for a in range(frame + 4, frame + 24)):
        report['original_ioctl_arguments'] = list(struct.unpack('<5I', mu.mem_read(frame + 4, 20)))
        report['ioctl_command_register'] = mu.reg_read(arm.UC_ARM_REG_R1)
        report['ioctl_frame_address'] = frame
    report['static_initialization_prefix'] = decode_block(elf, raw, 0x210d, 116)
    report['initialization_imports'] = {hex(a): plts.get(a) for a in (0x1614, 0x17f8, 0x1620)}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', required=True)
    args = parser.parse_args()
    output = (PROJECT_ROOT / args.report_dir).resolve()
    if not output.is_relative_to(PROJECT_ROOT / 'artifacts'):
        parser.error('Output must remain under artifacts')
    output.mkdir(parents=True, exist_ok=False)
    digest = next(r['sha256'] for r in json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text())['inputs'] if r['path'] == LIBRARY)
    raw = checked_input(PROJECT_ROOT, LIBRARY, digest)
    report = execute(raw)
    report['input'] = {'path': LIBRARY, 'sha256': digest}
    checked_input(PROJECT_ROOT, LIBRARY, digest)
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    print(output, report['status'], len(report['trace']), report.get('boundary'))


if __name__ == '__main__':
    main()
