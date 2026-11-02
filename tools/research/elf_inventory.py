"""Static ELF/dependency inventory. Candidate providers are not runtime bindings."""
from collections import Counter, defaultdict
import json
from pathlib import Path

from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection
from project_paths import PROJECT_ROOT
from tools.research.inventory import digest


def inspect_elf(path):
    with path.open('rb') as stream:
        if stream.read(4) != b'\x7fELF':
            return None
        stream.seek(0)
        elf = ELFFile(stream)
        dynamic = elf.get_section_by_name('.dynamic')
        needed, soname, runtime_paths, init = [], None, [], []
        if dynamic:
            for tag in dynamic.iter_tags():
                kind = tag.entry.d_tag
                if kind == 'DT_NEEDED':
                    needed.append(tag.needed)
                elif kind == 'DT_SONAME':
                    soname = tag.soname
                elif kind in ('DT_RPATH', 'DT_RUNPATH'):
                    runtime_paths.append(getattr(tag, 'rpath', getattr(tag, 'runpath', None)))
                elif kind in ('DT_INIT', 'DT_INIT_ARRAY', 'DT_INIT_ARRAYSZ'):
                    init.append({'tag': kind, 'value': tag.entry.d_val})
        imports, exports = [], []
        symbols = elf.get_section_by_name('.dynsym')
        if symbols:
            for symbol in symbols.iter_symbols():
                if not symbol.name:
                    continue
                binding = symbol['st_info']['bind']
                record = {'name': symbol.name, 'binding': binding,
                          'type': symbol['st_info']['type'], 'value': symbol['st_value'],
                          'visibility': symbol['st_other']['visibility']}
                if symbol['st_shndx'] == 'SHN_UNDEF':
                    imports.append(record)
                elif binding in ('STB_GLOBAL', 'STB_WEAK'):
                    exports.append(record)
        relocations = Counter()
        for section in elf.iter_sections():
            if isinstance(section, RelocationSection):
                for rel in section.iter_relocations():
                    relocations[f'{section.name}:{rel["r_info_type"]}'] += 1
        segments, interpreter = [], None
        for segment in elf.iter_segments():
            if segment['p_type'] == 'PT_LOAD':
                segments.append({key: segment[key] for key in
                                 ('p_vaddr', 'p_memsz', 'p_filesz', 'p_offset', 'p_flags', 'p_align')})
            elif segment['p_type'] == 'PT_INTERP':
                interpreter = segment.get_interp_name()
        return {'path': path.relative_to(PROJECT_ROOT).as_posix(), 'sha256': digest(path),
                'class': elf.elfclass, 'little_endian': elf.little_endian,
                'machine': elf['e_machine'], 'type': elf['e_type'], 'entry': elf['e_entry'],
                'flags': elf['e_flags'], 'soname': soname, 'needed': needed,
                'runtime_paths': runtime_paths, 'interpreter': interpreter,
                'initializers': init, 'segments': segments,
                'tls': any(s['p_type'] == 'PT_TLS' for s in elf.iter_segments()),
                'relocations': dict(sorted(relocations.items())), 'imports': imports, 'exports': exports}


def summarize(entries):
    names, providers = defaultdict(list), defaultdict(list)
    for entry in entries:
        for name in {Path(entry['path']).name, entry['soname']} - {None}:
            names[name].append(entry['path'])
        for symbol in entry['exports']:
            if symbol['visibility'] in ('STV_DEFAULT', 'STV_PROTECTED'):
                providers[symbol['name']].append(entry['path'])
    focus = []
    for entry in entries:
        if Path(entry['path']).name in ('libObj.so', 'viewUnified2.so', 'WS_SubProcess.elf', 'im.elf'):
            focus.append({'path': entry['path'], 'needed': entry['needed'],
                          'dependency_candidates': {n: names.get(n, []) for n in entry['needed']},
                          'unlocated_imports': [s['name'] for s in entry['imports'] if s['name'] not in providers],
                          'imports': [{'name': s['name'], 'binding': s['binding'],
                                       'candidate_providers': providers.get(s['name'], [])}
                                      for s in entry['imports']]})
    target = '_ZTVN10__cxxabiv120__si_class_type_infoE'
    return {'elf_count': len(entries), 'architectures': dict(Counter(e['machine'] for e in entries)),
            'types': dict(Counter(e['type'] for e in entries)),
            'first_blocker_symbol': target, 'first_blocker_providers': providers.get(target, []),
            'focus': focus,
            'missing_needed': [{'path': e['path'], 'needed': n} for e in entries for n in e['needed'] if n not in names],
            'limitations': ['Candidates are static name matches, not verified loader search order or symbol-version bindings.',
                            'Only extracted local ELF files are included; missing providers may be external or absent from this update.',
                            'Architecture fields do not establish CPU model, core count, memory map, or boot behavior.']}


def main():
    entries, errors = [], []
    root = PROJECT_ROOT / 'firmware/extracted_a6400'
    for path in sorted(root.rglob('*')):
        if not path.is_file():
            continue
        try:
            entry = inspect_elf(path)
            if entry:
                entries.append(entry)
        except Exception as error:
            errors.append({'path': path.relative_to(PROJECT_ROOT).as_posix(), 'error': str(error)})
    output = PROJECT_ROOT / 'artifacts/inventory'
    output.mkdir(parents=True, exist_ok=True)
    summary = summarize(entries)
    (output / 'elf-inventory.json').write_text(json.dumps({'entries': entries, 'errors': errors}, indent=2), encoding='utf-8')
    (output / 'elf-summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps({key: summary[key] for key in ('elf_count', 'architectures', 'types', 'first_blocker_providers')}, indent=2))
    print(f'Parse errors: {len(errors)}; reports: {output}')


if __name__ == '__main__':
    main()
