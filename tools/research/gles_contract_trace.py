"""Bounded original GLES open/setup windows; no driver or GPU success replies."""
import io
import json
import struct

import unicorn
from unicorn import arm_const as arm
from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.liro_startup_trace import STATE, run_slice
from tools.research.mount_evidence import checked_input, symbol
from tools.research.storage_trace import module_relocations

MODULE = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/grm_gles.ko'
DEVNO = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/kmod/devno.ko'


def run():
    entries = json.loads((PROJECT_ROOT / 'artifacts/inventory/elf-inventory.json').read_text())['entries']
    expected = {entry['path']: entry['sha256'] for entry in entries}
    raw = checked_input(PROJECT_ROOT, MODULE, expected[MODULE])
    elf = ELFFile(io.BytesIO(raw))
    section_index = next(i for i, section in enumerate(elf.iter_sections()) if section.name == '.text')
    code = bytearray(elf.get_section(section_index).data())
    relocs = module_relocations(elf)
    if symbol(elf, 'sugilite_open')['st_value'] != 0x43c:
        raise ValueError('Original open entry differs')
    first_call = relocs[(section_index, 0x450)]
    if first_call['type'] != 28 or first_call['symbol'] != '__migrate_disable':
        raise ValueError('Original first open prerequisite differs')
    context = bytearray(4096)
    struct.pack_into('<I', context, 0x190, STATE + 0x800)
    opened, mu = run_slice(bytes(code), 0x43c, [(0x43c, 0x450)],
        {0x450: 'kernel_migrate_disable_boundary'},
        {arm.UC_ARM_REG_R0: STATE, arm.UC_ARM_REG_R1: STATE + 0x400},
        [(STATE, bytes(context), unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)])
    after = bytes(mu.mem_read(STATE, len(context)))
    expected_context = bytearray(context)
    struct.pack_into('<I', expected_context, 0x4a8, STATE + 0x800)
    if opened['status'] != 'kernel_migrate_disable_boundary' or after != expected_context:
        raise ValueError('Original open prefix effects differ')

    selected_relocations = []
    for (index, offset), relocation in relocs.items():
        if index != section_index or not 0x54 <= offset < 0x1a8 or relocation['type'] != 28:
            continue
        if relocation['symbol_section'] != '.text' or relocation['symbol'] != 'sugilite_iowrite32':
            raise ValueError('Unexpected setup call')
        word = struct.unpack_from('<I', code, offset)[0]
        addend = (word & 0xffffff) << 2
        if addend & 0x2000000:
            addend -= 0x4000000
        delta = relocation['symbol_value'] + addend - offset
        struct.pack_into('<I', code, offset, (word & 0xff000000) | ((delta >> 2) & 0xffffff))
        selected_relocations.append({'offset': offset, 'relocation': relocation})
    outer = relocs[(section_index, 0x1414)]
    if outer['type'] != 2 or outer['symbol'] != 'outer_cache':
        raise ValueError('Original cache table relocation differs')
    # Explicit unresolved-import address for this isolated control only. No bytes
    # or callback are supplied at that address, and execution stops before use.
    unresolved_cache = 0x09000000
    struct.pack_into('<I', code, 0x1414, unresolved_cache)
    context = bytearray(4096)
    struct.pack_into('<I', context, 0xf8, 0xf1000000)
    setup, _ = run_slice(bytes(code), 0x54, [(0x54, 0x1a8), (0x13e0, 0x1414)],
        {0x13fc: 'outer_cache_runtime_callback_boundary'}, {arm.UC_ARM_REG_R0: STATE},
        [(STATE, bytes(context), unicorn.UC_PROT_READ)], budget=100)
    if (setup['status'] != 'outer_cache_runtime_callback_boundary'
            or setup['registers']['r4'] != 0xffffffff or setup['registers']['r1'] != 0xf10010c0):
        raise ValueError('Original setup did not reach expected first register prerequisite')

    devno = ELFFile(io.BytesIO(checked_input(PROJECT_ROOT, DEVNO, expected[DEVNO])))
    table = devno.get_section_by_name('.data').data()
    names = devno.get_section_by_name('.rodata.str1.1').data()
    identities = []
    for offset in range(0, len(table) - 11, 12):
        pointer, kind, numbers = struct.unpack_from('<3I', table, offset)
        if pointer >= len(names):
            continue
        end = names.find(b'\0', pointer)
        if end >= 0 and names[pointer:end] == b'dmpgles2':
            identities.append({'table_offset': offset, 'major': kind >> 16,
                               'minor': numbers & 0xffff, 'count': numbers >> 16, 'kind': kind & 0xffff})
    if len(identities) != 1:
        raise ValueError('Original device table does not uniquely identify dmpgles2')
    return {'status': 'original_gles_prerequisites_bounded', 'module_sha256': expected[MODULE],
            'devno_sha256': expected[DEVNO], 'device_identity': identities[0],
            'open_prefix': opened, 'register_setup_prefix': setup,
            'selected_call_relocations': selected_relocations, 'register_writes_executed': 0,
            'limitations': ['Constructed inode/file/device and stack mappings, not a loaded kernel driver.',
                            'Physical base 0xf1000000 is a compiled initialization assignment, not observed runtime state.',
                            'No migrate/lock/task/cache callback, IRQ, DMA, GPU command or rendering result supplied.',
                            'Open does not return; no file descriptor or GPU MMIO success is claimed.']}


def main():
    report = run()
    output = PROJECT_ROOT / 'artifacts/execution/gles-contract-trace.json'
    if output.exists():
        raise FileExistsError('Preserve the existing trace before rerunning')
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output)
    print(report['status'], report['device_identity'])


if __name__ == '__main__':
    main()
