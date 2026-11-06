"""Audit original touch patch sites without accessing the camera."""
import hashlib
import io
import json
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UcError
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP, UC_ARM_REG_LR

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib'


def run_menu_window(code, requested):
    """Execute original instructions against an explicit fixture vtable only."""
    cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    for base in [0x10000, 0x20000, 0x30000, 0x40000]:
        cpu.mem_map(base, 0x1000)
    cpu.mem_write(0x10000, code)
    cpu.mem_write(0x20000, (0x20100).to_bytes(4, 'little'))
    cpu.mem_write(0x20208, (0x40001).to_bytes(4, 'little'))
    cpu.reg_write(UC_ARM_REG_R0, 0x20000)
    cpu.reg_write(UC_ARM_REG_R1, requested)
    cpu.reg_write(UC_ARM_REG_SP, 0x30f00)
    cpu.reg_write(UC_ARM_REG_LR, 0x10f01)
    result = {'requested': requested, 'scope': 'constructed vtable; stop before virtual method'}
    def stop(uc, address, size, context):
        if address == 0x40000:
            result['virtual_method_argument'] = uc.reg_read(UC_ARM_REG_R1)
            uc.emu_stop()
    cpu.hook_add(UC_HOOK_CODE, stop)
    try:
        cpu.emu_start(0x10001, 0x10f00, count=32)
    except UcError as error:
        result['execution_error'] = str(error)
    return result


def audit(filename, symbol, patch_offset, replacement):
    data = (LIB / filename).read_bytes()
    elf = ELFFile(io.BytesIO(data))
    matches = [s for s in elf.get_section_by_name('.dynsym').iter_symbols() if s.name == symbol]
    if len(matches) != 1:
        raise ValueError('Expected one exact symbol: ' + symbol)
    address = int(matches[0]['st_value']) & ~1
    segments = [p for p in elf.iter_segments() if p['p_type'] == 'PT_LOAD'
                and p['p_vaddr'] <= address < p['p_vaddr'] + p['p_filesz']]
    if len(segments) != 1:
        raise ValueError('Expected one file-backed segment')
    segment = segments[0]
    offset = segment['p_offset'] + address - segment['p_vaddr']
    original = data[offset:offset+32]
    modified = original[:patch_offset] + replacement + original[patch_offset+len(replacement):]
    decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    def decode(code):
        return [{'address': hex(i.address), 'size': i.size, 'bytes': i.bytes.hex(),
                 'instruction': i.mnemonic + ' ' + i.op_str}
                for i in decoder.disasm(code, address)]
    instructions = decode(original)
    patch_start = address + patch_offset
    patch_end = patch_start + len(replacement)
    starts = {int(i['address'], 16) for i in instructions}
    return {'file': str((LIB / filename).relative_to(ROOT)), 'sha256': hashlib.sha256(data).hexdigest(),
            'symbol': symbol, 'linked_address': hex(address), 'patch_address': hex(patch_start),
            'original': original.hex(), 'replacement': replacement.hex(),
            'patch_starts_on_instruction': patch_start in starts,
            'patch_ends_on_instruction': patch_end in starts,
            'original_instructions': instructions, 'modified_instructions': decode(modified)}


def main():
    raw = (LIB / 'libObj.so').read_bytes()
    elf = ELFFile(io.BytesIO(raw))
    pattern = bytes.fromhex('98 b5 00 af 04 46')
    counts = [p.data().count(pattern) for p in elf.iter_segments()
              if p['p_type'] == 'PT_LOAD' and p['p_flags'] & 1]
    result = {'scope': 'Static preserved firmware only; no live address identity or compatibility proven.',
              'short_prologue_executable_matches': sum(counts),
              'sites': [audit('libObj.so', '_ZN12InputService12setTpEventSwEb', 4, bytes.fromhex('01 24')),
                        audit('viewUnified2.so', '_ZN18PAS_MenuSelectMode12setTouchableEb', 6,
                              bytes.fromhex('00 bf 00 bf')),
                        audit('viewUnified2.so', '_ZN18PAS_MenuSelectMode12setTouchableEb', 6,
                              bytes.fromhex('00 bf'))]}
    original = bytes.fromhex(result['sites'][1]['original'])[:26]
    old = original[:6] + bytes.fromhex('00 bf 00 bf') + original[10:]
    corrected = original[:6] + bytes.fromhex('00 bf') + original[8:]
    result['bounded_execution'] = {name: [run_menu_window(code, requested) for requested in (0, 1)]
                                   for name, code in [('original', original), ('old_four_byte_patch', old),
                                                      ('candidate_two_byte_patch', corrected)]}
    assert [x.get('virtual_method_argument') for x in result['bounded_execution']['original']] == [2, 0]
    assert [x.get('virtual_method_argument') for x in result['bounded_execution']['candidate_two_byte_patch']] == [0, 0]
    destination = ROOT / 'artifacts/analysis/touch-patch-audit-20261105.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(destination)
    print('Short-prologue matches:', result['short_prologue_executable_matches'])
    for site in result['sites']:
        print(site['symbol'], 'patch ends at instruction boundary:', site['patch_ends_on_instruction'])


if __name__ == '__main__':
    main()
