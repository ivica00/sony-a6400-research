"""Execute original SD/MMCP read bounds with explicit constructed controls.

No driver lock, host controller, card response or SD content is supplied.
"""
import argparse
import io
import json
import struct

import unicorn
from unicorn import arm_const as arm
from elftools.elf.elffile import ELFFile
from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input

TARGET = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/mmc_drv.ko'
CODE, STACK, STATE, RETURN = 0x01000000, 0x08000000, 0x08200000, 0x09000000


def execute(code, sector, count, capacity, relocation_offsets=(), extra_windows=(), card_reference=False):
    if any(not isinstance(v, int) or not 0 <= v <= 0xffffffff for v in (sector, count, capacity)):
        raise ValueError('Controls must be unsigned ARM32 words')
    if not code or len(code) > 4096:
        raise ValueError('Expected bounded original ARM window')
    if any(not isinstance(o, int) or o < 0 or o + 4 > len(code) for o in relocation_offsets):
        raise ValueError('Relocation escapes selected window')
    windows = [(CODE, code, relocation_offsets)]
    for offset, data, relocations in extra_windows:
        address = CODE + offset
        if not data or len(data) > 4096 or not 0x00100000 <= address < 0x02000000 or address + len(data) > 0x02000000:
            raise ValueError('Extra code window escapes isolated region')
        if any(address < a + len(d) and a < address + len(data) for a, d, _ in windows):
            raise ValueError('Overlapping code windows')
        if any(not isinstance(o, int) or o < 0 or o + 4 > len(data) for o in relocations):
            raise ValueError('Extra relocation escapes source window')
        windows.append((address, data, relocations))
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
    mapped_regions = [(CODE, 4096), (STACK, 0x4000), (STATE, 4096), (RETURN, 4096)]
    host_hw = 0x08400000
    if card_reference:
        mapped_regions.append((host_hw, 4096))
    for address, size in mapped_regions:
        mu.mem_map(address, size)
    mapped = {CODE}
    for address, data, _ in windows:
        for page in range(address & ~4095, (address + len(data) + 4095) & ~4095, 4096):
            if page not in mapped:
                mu.mem_map(page, 4096)
                mapped.add(page)
        mu.mem_write(address, data)
    mu.mem_write(STATE, b'\xa5' * 4096)
    mu.mem_write(STATE + 0x2dc, struct.pack('<I', capacity))
    mu.mem_write(STACK + 0x3000, struct.pack('<I', 3))
    known = set(range(STATE + 0x2dc, STATE + 0x2e0)) | set(range(STACK + 0x3000, STACK + 0x3004))
    if card_reference:
        mu.mem_write(STATE, struct.pack('<I', host_hw))
        mu.mem_write(host_hw, struct.pack('<I', 0))
        known.update(range(STATE, STATE + 4))
        known.update(range(host_hw, host_hw + 4))
    for address, data, _ in windows:
        known.update(range(address, address + len(data)))
    unresolved = {a + o + n for a, _, relocs in windows for o in relocs for n in range(4)}
    known.difference_update(unresolved)
    assumption = ('Constructed call frame, capacity and host controller reference, not observed card state.'
                  if card_reference else
                  'Constructed call frame and capacity, not observed card state.')
    report = {'status': 'running', 'sector': sector, 'count': count, 'capacity_control': capacity,
              'trace_offsets': [], 'writes': [], 'assumption': assumption}
    def stop(reason, **details):
        report.update(status=reason, boundary={'pc': mu.reg_read(arm.UC_ARM_REG_PC), **details})
        mu.emu_stop()
    def instruction(uc, address, size, user):
        if address == RETURN:
            stop('isolated_return', result=mu.reg_read(arm.UC_ARM_REG_R0))
        elif not any(a <= address and address + size <= a + len(d) for a, d, _ in windows):
            stop('unsupported_code', address=address)
        elif any(a in unresolved for a in range(address, address + size)):
            stop('unresolved_relocation', address=address)
        else:
            report['trace_offsets'].append(address - CODE)
    def memory(uc, access, address, size, value, user):
        if access == unicorn.UC_MEM_WRITE:
            if not STACK <= address or address + size > STACK + 0x4000:
                stop('unsupported_write', address=address, size=size)
            else:
                known.update(range(address, address + size))
                report['writes'].append({'address': address, 'size': size, 'value': value})
        elif not all(a in known for a in range(address, address + size)):
            stop('unsupplied_runtime_read', address=address, size=size)
    mu.hook_add(unicorn.UC_HOOK_CODE, instruction)
    mu.hook_add(unicorn.UC_HOOK_MEM_READ | unicorn.UC_HOOK_MEM_WRITE, memory)
    def unmapped(uc, access, address, size, value, user):
        stop('unsupported_unmapped_access', address=address, size=size, access=access)
        return False
    mu.hook_add(unicorn.UC_HOOK_MEM_INVALID, unmapped)
    for reg, value in ((arm.UC_ARM_REG_R0, STATE), (arm.UC_ARM_REG_R1, sector),
                       (arm.UC_ARM_REG_R2, count), (arm.UC_ARM_REG_R3, 0x08300000),
                       (arm.UC_ARM_REG_SP, STACK + 0x3000), (arm.UC_ARM_REG_LR, RETURN)):
        mu.reg_write(reg, value)
    try:
        mu.emu_start(CODE, 0, count=200, timeout=100000)
    except unicorn.UcError as error:
        if report['status'] == 'running':
            report.update(status='execution_fault', error=str(error))
    if report['status'] == 'running':
        report['status'] = 'timeout' if mu.query(unicorn.UC_QUERY_TIMEOUT) else 'instruction_limit'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', required=True)
    parser.add_argument('--preparation-prefix', action='store_true', help='Execute original preparation to its first unsupplied state/import')
    parser.add_argument('--card-reference-prefix', action='store_true', help='Execute original preparation with initialized card reference up to lock_sem relocation')
    args = parser.parse_args()
    output = (PROJECT_ROOT / args.report_dir).resolve()
    if not output.is_relative_to(PROJECT_ROOT / 'artifacts'):
        parser.error('Output must remain under artifacts')
    output.mkdir(parents=True, exist_ok=False)
    digest = next(r['sha256'] for r in json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text())['inputs'] if r['path'] == TARGET)
    raw = checked_input(PROJECT_ROOT, TARGET, digest)
    elf = ELFFile(io.BytesIO(raw))
    symbols = {s.name: s for s in elf.get_section_by_name('.symtab').iter_symbols()}
    if (elf['e_type'], elf['e_machine'], elf.elfclass, elf.little_endian) != ('ET_REL', 'EM_ARM', 32, True):
        raise ValueError('Expected original ARM32 module')
    if symbols['mmc_mmcp_read']['st_value'] != 0x17070 or symbols['mmc_mmcp_write']['st_value'] != 0x16fe0:
        raise ValueError('Original read wrapper coordinates changed')
    start, end = 0x16e94, 0x16fe0
    text = elf.get_section_by_name('.text').data()
    # Wrapper's original relative BL must still reach this helper.
    branch = struct.unpack_from('<I', text, 0x17088)[0]
    displacement = (branch & 0xffffff) << 2
    if displacement & 0x2000000:
        displacement -= 0x4000000
    if branch >> 24 != 0xeb or 0x17090 + displacement != start:
        raise ValueError('Original read helper edge changed')
    # Do not execute a relocated word from an unlinked module.
    text_index = next(i for i, s in enumerate(elf.iter_sections()) if s.name == '.text')
    all_relocations = []
    for section in elf.iter_sections():
        if section['sh_type'] == 'SHT_REL' and section['sh_info'] == text_index:
            all_relocations.extend(r['r_offset'] for r in section.iter_relocations())
    relocation_offsets = [a - start for a in all_relocations if start <= a < end]
    extra = []
    if args.preparation_prefix or args.card_reference_prefix:
        lower, upper = 0x16328, 0x163d8
        extra.append((lower - start, text[lower:upper], [a - lower for a in all_relocations if lower <= a < upper]))
    card_ref = bool(args.card_reference_prefix)
    results = [execute(text[start:end], *control, relocation_offsets=relocation_offsets, extra_windows=extra, card_reference=card_ref) for control in ((0, 0, 1024), (0xffffffff, 2, 1024), (1023, 2, 1024), (0, 1, 1024))]
    report = {'input': {'path': TARGET, 'sha256': digest}, 'text_start': start, 'text_end': end,
              'isolated_mapping': CODE, 'unresolved_relocation_offsets': relocation_offsets, 'results': results,
              'limitations': ['Only bounds/prefix execution; constructed capacity1024 does not describe the physical card.',
                              'Calls outside helper stop; no lock, DMA, controller or card response supplied.']}
    if args.preparation_prefix or args.card_reference_prefix:
        report['preparation_window'] = {'text_start': lower, 'text_end': upper, 'unresolved_relocation_offsets': extra[0][2]}
    if args.card_reference_prefix:
        report['card_reference'] = {'host_controller_pointer': 0x08400000, 'host_controller_hw_id': 0}
    checked_input(PROJECT_ROOT, TARGET, digest)
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    print(output, [(r['status'], r.get('boundary')) for r in results])


if __name__ == '__main__':
    main()
