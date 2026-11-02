"""Audit retained REA trial outputs against the preserved ARM module."""
import io
import json
import re
import hashlib

from elftools.elf.elffile import ELFFile
from project_paths import PROJECT_ROOT
from tools.research.mount_evidence import checked_input


def main():
    folder = PROJECT_ROOT / 'artifacts/tools/rea'
    source = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/backup.ko'
    inventory = json.loads((PROJECT_ROOT / 'artifacts/inventory/elf-inventory.json').read_text(encoding='utf-8'))
    expected = next(entry['sha256'] for entry in inventory['entries'] if entry['path'] == source)
    raw = checked_input(PROJECT_ROOT, source, expected)
    elf = ELFFile(io.BytesIO(raw))
    outputs = {name: json.loads((folder / name).read_text(encoding='utf-8')) for name in
               ('backup-symbols.json', 'backup-relocations.json', 'backup-disassembly.json', 'backup-ghidra.json')}
    results = {}
    for name, result in outputs.items():
        if 'raw_result' in result:
            observation = result['raw_result']
            if result['subject']['digest']['sha256'] != expected or observation['artifact_sha256_after'] != expected:
                raise ValueError('REA evidence identity does not match the preserved module')
            results[name] = {key: observation.get(key) for key in
                             ('exit_code', 'artifact_changed', 'output_truncated', 'stderr')}
        else:
            results[name] = {'code': result.get('code'), 'category': result.get('category'),
                             'rejections': result.get('details', {}).get('rejections')}
    symbols = outputs['backup-symbols.json']['raw_result']['stdout']
    functions = []
    for line in symbols.splitlines():
        match = re.fullmatch(r'([0-9a-fA-F]+)\s+[lg]\s+F\s+(\S+)\s+([0-9a-fA-F]+)\s+(\S+)', line.strip())
        if match:
            value, section, size, name = match.groups()
            functions.append({'name': name, 'section': section, 'offset': int(value, 16), 'size': int(size, 16)})
    original = {(symbol.name, elf.get_section(symbol['st_shndx']).name, symbol['st_value'], symbol['st_size'])
                for symbol in elf.get_section_by_name('.symtab').iter_symbols()
                if symbol['st_info']['type'] == 'STT_FUNC' and isinstance(symbol['st_shndx'], int)}
    observed = {(item['name'], item['section'], item['offset'], item['size']) for item in functions}
    if not observed or observed != original:
        raise ValueError('REA/objdump function inventory differs from the independent ELF parser')
    package = json.loads((folder / 'runtime/node_modules/rea-agents/package.json').read_text(encoding='utf-8'))
    report = {'tool': 'REA', 'version': package['version'], 'host': 'Windows x64',
              'target': {'path': source, 'sha256': expected, 'format': 'ELF32 ARM ET_REL'},
              'results': results, 'functions_independently_matched': len(functions),
              'selected_functions': [item for item in functions if item['name'] in
                                     ('backup_osal_call_func', 'Backup_reg_cb', 'func_cb_sync')],
              'unknown_relocation_type_rows': len(re.findall(r'\bUNKNOWN\b', outputs['backup-relocations.json']['raw_result']['stdout'])),
              'source_unchanged': hashlib.sha256((PROJECT_ROOT / source).read_bytes()).hexdigest() == expected,
              'conclusion': 'Symbol inventory verified; installed objdump lacks ARM disassembly/relocation-type decoding; REA Windows Ghidra rejects this ELF target. No decompiler speedup measured.'}
    output = folder / 'trial-audit.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output)
    print(report['conclusion'])
    print('matched functions:', len(functions))


if __name__ == '__main__':
    main()
