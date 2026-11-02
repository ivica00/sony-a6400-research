"""Original interpreter produces its page-size field from declared process auxv."""
import argparse
import io
import json
import struct

import unicorn
from unicorn import arm_const as arm
from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input
from tools.research.guest_layout import resolve_guest
from src.a6400.images.process_elf import inspect_image
from src.a6400.execution.interpreter_probe import InterpreterProbe


def produce():
    folder = PROJECT_ROOT / 'artifacts/inventory'
    namespace = json.loads((folder / 'guest-filesystem.json').read_text())
    hashes = {r['path']: r['sha256'] for r in json.loads((folder / 'baseline.json').read_text())['inputs']}
    inputs = {}

    def image(path):
        resolution = resolve_guest(namespace['nodes'], path)
        if resolution['status'] != 'resolved':
            raise ValueError('Unresolved original image')
        node = namespace['nodes'][resolution['path']]
        if node['kind'] != 'file':
            raise ValueError('Selected original image is not a file')
        relative = node['extracted_path']
        checked_input(PROJECT_ROOT, relative, hashes[relative])
        inputs[relative] = hashes[relative]
        return inspect_image(PROJECT_ROOT / relative, hashes[relative])

    application = image('/usr/bin/im.elf')
    interpreter = image(application['interpreter'])
    elf = ELFFile(io.BytesIO(interpreter['data']))
    app_elf = ELFFile(io.BytesIO(application['data']))
    needed = [tag.needed for tag in app_elf.get_section_by_name('.dynamic').iter_tags() if tag.entry.d_tag == 'DT_NEEDED']
    matches = [s for s in elf.get_section_by_name('.dynsym').iter_symbols() if s.name == '_rtld_global_ro']
    if len(matches) != 1 or matches[0]['st_shndx'] == 'SHN_UNDEF' or matches[0]['st_size'] < 20:
        raise ValueError('Undefined/ambiguous loader global')
    symbol = matches[0]
    probe = InterpreterProbe(syscall_policy='stop')
    probe.prepare(application, interpreter, ['/usr/bin/im.elf', 'i'])
    address = 0x40000000 + symbol['st_value']
    field = address + 16
    before = bytes(probe.mu.mem_read(field, 4))
    writes = []
    auxv = probe.report['stack']['auxv']
    auxv_base = (probe.report['stack']['sp'] + 4 +
                 (probe.report['stack']['argc'] + 1) * 4 +
                 (len(probe.report['stack']['environment']) + 1) * 4)
    entries = [index for index, (kind, value) in enumerate(auxv) if kind == 6]
    if len(entries) != 1:
        raise ValueError('Page-size auxiliary-vector entry is ambiguous')
    auxv_entry = auxv_base + entries[0] * 8
    if bytes(probe.mu.mem_read(auxv_entry, 8)) != struct.pack('<2I', *auxv[entries[0]]):
        raise ValueError('Auxiliary-vector stack layout mismatch')
    reads = []

    def write(uc, access, target, size, value, _):
        if target < field + 4 and field < target + size:
            pc = uc.reg_read(arm.UC_ARM_REG_PC)
            writes.append({'pc': pc, 'address': target, 'size': size, 'value': value,
                           'instruction_bytes': bytes(uc.mem_read(pc, 4)).hex(),
                           'thumb': bool(uc.reg_read(arm.UC_ARM_REG_CPSR) & 0x20)})

    def read(uc, access, target, size, value, _):
        if target < auxv_entry + 8 and auxv_entry < target + size:
            reads.append({'pc': uc.reg_read(arm.UC_ARM_REG_PC), 'address': target, 'size': size,
                          'bytes': bytes(uc.mem_read(target, size)).hex()})

    probe.mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, write)
    probe.mu.hook_add(unicorn.UC_HOOK_MEM_READ, read)
    report = probe.run(instruction_budget=100000, timeout_us=2000000)
    after = bytes(probe.mu.mem_read(field, 4))
    if report['status'] != 'syscall_boundary' or report['syscall_responses_supplied'] != 0:
        raise ValueError('Original no-response loader baseline changed')
    if len(writes) != 1 or writes[0]['address'] != field or writes[0]['size'] != 4 or after != struct.pack('<I', writes[0]['value']):
        raise ValueError('Page-size field lacks one complete original producer store')
    for path, digest in inputs.items():
        checked_input(PROJECT_ROOT, path, digest)
    return {'inputs': inputs, 'symbol': '_rtld_global_ro', 'symbol_address': address,
        'application_needed': needed,
        'field_address': field, 'before': before.hex(), 'after': after.hex(), 'writes': writes,
        'auxv_page_entry': {'address': auxv_entry, 'type': 6, 'value': auxv[entries[0]][1], 'reads': reads},
        'probe': report, 'limitations': ['Original loader under existing declared process-entry assumptions.',
            'AT_PAGESZ4096 and other entry inputs are experimental; no physical-camera measurement or full boot.',
            'Only this written field is offered to a consumer, not other loader runtime fields.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', required=True)
    args = parser.parse_args()
    output = (PROJECT_ROOT / args.report_dir).resolve()
    if not output.is_relative_to(PROJECT_ROOT / 'artifacts'):
        parser.error('Output must remain under artifacts')
    output.mkdir(parents=True, exist_ok=False)
    report = produce()
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    print(output, report['probe']['instructions_executed'], report['after'], report['writes'])


if __name__ == '__main__':
    main()
