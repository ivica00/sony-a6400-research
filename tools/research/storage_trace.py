"""Bounded static evidence from original ARM storage module instructions.

Offsets are section-relative. No relocations are applied and no kernel is run.
"""
import io
import json
import re
import struct

from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
from elftools.elf.elffile import ELFFile
import unicorn
from unicorn import arm_const as arm

from project_paths import PROJECT_ROOT
from tools.research.mount_evidence import checked_input, symbol, terminated_ascii


def decode_arm_range(data, start, size, relocations):
    if start < 0 or size <= 0 or start % 4 or size % 4 or start + size > len(data):
        raise ValueError('ARM evidence range must be aligned and section-backed')
    decoder = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    rows, literals = [], set()
    for offset in range(start, start + size, 4):
        raw = data[offset:offset + 4]
        row = {'offset': offset, 'bytes': raw.hex()}
        relocation = relocations.get(offset)
        if relocation:
            row['relocation'] = relocation
        if relocation and relocation['type'] == 2:
            row.update(kind='relocated_data', value=int.from_bytes(raw, 'little'))
            rows.append(row)
            continue
        instruction = next(decoder.disasm(raw, offset), None)
        if instruction is None:
            row['kind'] = 'undecoded'
        else:
            row.update(kind='instruction_candidate', mnemonic=instruction.mnemonic,
                       operands=instruction.op_str)
            # Relocated branches have unresolved immediates. The relocation's
            # symbol is the evidence; never present the placeholder as a call.
            if instruction.mnemonic in ('bl', 'blx') and relocation:
                row['call_symbol'] = relocation['symbol']
            literal = re.fullmatch(r'(\w+), \[pc(?:, #(-?0x[0-9a-f]+|-?[0-9]+))?\]', instruction.op_str)
            if instruction.mnemonic.startswith('ldr') and literal:
                address = offset + 8 + (int(literal[2], 0) if literal[2] else 0)
                if 0 <= address <= len(data) - 4 and address % 4 == 0:
                    literals.add(address)
                    row['literal'] = {'section_offset': address,
                                      'value': struct.unpack_from('<I', data, address)[0]}
                    if address in relocations:
                        row['literal']['relocation'] = relocations[address]
        rows.append(row)
    # PC-referenced data must not masquerade as an executed instruction.
    for row in rows:
        if row['offset'] in literals:
            row.update(kind='literal_data', value=int.from_bytes(bytes.fromhex(row['bytes']), 'little'))
            for key in ('mnemonic', 'operands', 'call_symbol', 'literal'):
                row.pop(key, None)
    return rows


def module_relocations(elf):
    result = {}
    for section in elf.iter_sections():
        if section['sh_type'] != 'SHT_REL':
            continue
        target_index = section['sh_info']
        target = elf.get_section(target_index)
        symbols = elf.get_section(section['sh_link'])
        for relocation in section.iter_relocations():
            offset = relocation['r_offset']
            if offset < 0 or offset + 4 > target['sh_size']:
                raise ValueError('Relocation outside module section')
            key = (target_index, offset)
            if key in result:
                raise ValueError('Duplicate module relocation')
            entry = symbols.get_symbol(relocation['r_info_sym'])
            index = entry['st_shndx']
            backing = elf.get_section(index) if isinstance(index, int) else None
            item = {'type': relocation['r_info_type'], 'symbol': entry.name,
                    'symbol_value': entry['st_value'],
                    'symbol_section': backing.name if backing else str(index)}
            if relocation['r_info_type'] == 2:
                addend = struct.unpack_from('<I', target.data(), offset)[0]
                item['addend'] = addend
                item['target_offset'] = entry['st_value'] + addend
                if backing and not backing['sh_flags'] & 4:  # non-executable data only
                    try:
                        text = terminated_ascii(backing.data(), item['target_offset'])
                        if text and all(32 <= ord(char) < 127 or char in '\n\r\t' for char in text):
                            item['string_candidate'] = text
                    except ValueError:
                        pass
            result[key] = item
    return result


def inspect_module(data, names):
    elf = ELFFile(io.BytesIO(data))
    if elf.elfclass != 32 or not elf.little_endian or elf['e_machine'] != 'EM_ARM' or elf['e_type'] != 'ET_REL':
        raise ValueError('Expected little-endian ELF32 ARM relocatable storage module')
    relocations = module_relocations(elf)
    result = []
    for name in names:
        entry = symbol(elf, name)
        index = entry['st_shndx']
        if not isinstance(index, int) or entry['st_info']['type'] != 'STT_FUNC':
            raise ValueError('Storage evidence requires a section-backed function')
        section = elf.get_section(index)
        if not section['sh_flags'] & 4 or entry['st_value'] & 1:
            raise ValueError('Expected ARM executable section')
        if entry['st_size'] > 16384:
            raise ValueError('Function exceeds static evidence bound')
        relevant = {offset: item for (section_index, offset), item in relocations.items()
                    if section_index == index}
        result.append({'name': name, 'section': section.name, 'offset': entry['st_value'],
                       'size': entry['st_size'], 'file_offset': section['sh_offset'] + entry['st_value'],
                       'rows': decode_arm_range(section.data(), entry['st_value'], entry['st_size'], relevant)})
    return result


def execute_parameter_copy(code, record):
    """Isolated instruction window with explicit inputs, no kernel responses."""
    if len(code) != 36 or len(record) != 12:
        raise ValueError('Parameter-copy experiment requires nine ARM words and one device record')
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
    code_base, source, output = 0x1000000, 0x2000000, 0x3000000
    mu.mem_map(code_base, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    mu.mem_write(code_base, code)
    mu.mem_map(source, 4096, unicorn.UC_PROT_READ)
    mu.mem_write(source, record)
    mu.mem_map(output, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
    mu.mem_write(output, b'\xa5' * 256)
    mu.reg_write(arm.UC_ARM_REG_CPSR, 0x10)
    mu.reg_write(arm.UC_ARM_REG_R4, output)
    mu.reg_write(arm.UC_ARM_REG_R5, source)
    executed = []
    mu.hook_add(unicorn.UC_HOOK_CODE, lambda uc, address, size, _: executed.append(address))
    # No syscall, MMIO, invalid-memory or function-call interception is supplied.
    mu.emu_start(code_base, code_base + len(code), timeout=500000, count=10)
    if (mu.reg_read(arm.UC_ARM_REG_PC) != code_base + len(code) or len(executed) != 9
            or mu.query(unicorn.UC_QUERY_TIMEOUT)):
        raise ValueError('Parameter-copy window did not complete exactly')
    raw = bytes(mu.mem_read(output, 256))
    return {'status': 'isolated_window_completed', 'instructions_executed': len(executed),
            'kernel_responses_supplied': 0, 'record_hex': record.hex(),
            'output_words': {hex(offset): struct.unpack_from('<I', raw, offset)[0]
                             for offset in (0x28, 0x2c, 0x30)},
            'output_hex': raw.hex(),
            'assumptions': ['Isolated window only; caller setup is supplied explicitly.',
                            'Provisional Cortex-A9, ARM user mode, fixed mapped addresses; not camera CPU validation.']}


FUNCTIONS = ('init_blk_params.clone.7', 'emmc_blk_plat_init', 'init_emmc_and_blkdev',
             'emmc_blk_probe', 'emmc_blk_plat_probe_post', 'uz_emmc_lzp_part_size')


def main():
    folder = PROJECT_ROOT / 'artifacts/inventory'
    expected = {row['path']: row['sha256'] for row in
                json.loads((folder / 'baseline.json').read_text(encoding='utf-8'))['inputs']}
    path = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/initrd.img_unpacked/kmod/emmc.ko'
    data = checked_input(PROJECT_ROOT, path, expected[path])
    table_path = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/initrd.img_unpacked/kmod/devno.ko'
    table_data = checked_input(PROJECT_ROOT, table_path, expected[table_path])
    module = ELFFile(io.BytesIO(data))
    table_module = ELFFile(io.BytesIO(table_data))
    table_symbol = symbol(table_module, 'udif_devnodes')
    table_raw = table_module.get_section(table_symbol['st_shndx']).data()
    # Offsets refer only to these identified binaries, not a general ABI promise.
    code = module.get_section_by_name('.init.text').data()[0x39c:0x3c0]
    copies = {}
    for name, offset in (('nflasha', 0), ('dnflasha', 36)):
        start = table_symbol['st_value'] + offset
        copies[name] = execute_parameter_copy(code, table_raw[start:start + 12])
    report = {'schema_version': 1, 'status': 'static_and_isolated_instruction_evidence',
              'camera_fidelity_validated': False, 'runtime_device_identity_selected': False,
              'source': {'path': path, 'sha256': expected[path]},
              'device_table_source': {'path': table_path, 'sha256': expected[table_path]},
              'isolated_parameter_copy': {'source_section': '.init.text', 'start_offset': 0x39c,
                                          'end_offset': 0x3c0, 'runs': copies},
              'functions': inspect_module(data, FUNCTIONS),
              'limitations': ['Section offsets are not runtime virtual addresses.',
                              'Linear instruction candidates are not an executed control-flow trace.',
                              'PC literals and ABS32 data are separated; other inline data may remain.',
                              'Relocations are annotated, never applied; external kernel behavior is not supplied.',
                              'This report does not establish boot mode, mount success, /etc contents or st_dev.']}
    output = folder / 'storage-trace.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'Recorded {len(report["functions"])} original storage functions; runtime identity remains unselected.')
    print(f'Report: {output}')


if __name__ == '__main__':
    main()
