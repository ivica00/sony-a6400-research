"""Bounded ARM module dependency planning with verified static and REA caches.

This tool analyzes original bytes; it never executes firmware or services a guest.
"""
from collections import deque
import argparse
import hashlib
import io
import json
from pathlib import Path

import capstone
import elftools
from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input
from tools.research.rea_evidence_cache import EvidenceCache, bounded_json
from tools.research.storage_trace import module_relocations, decode_arm_range


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def analyze_function(raw, name):
    elf = ELFFile(io.BytesIO(raw))
    if (elf['e_type'], elf['e_machine'], elf.elfclass, elf.little_endian) != ('ET_REL', 'EM_ARM', 32, True):
        raise ValueError('Only ELF32 little-endian ARM relocatable modules are supported')
    symbols = elf.get_section_by_name('.symtab')
    functions = [s for s in symbols.iter_symbols() if s['st_info']['type'] == 'STT_FUNC'
                 and isinstance(s['st_shndx'], int)]
    selected = [s for s in functions if s.name == name]
    if len(selected) != 1:
        raise ValueError('Function name is absent or ambiguous: ' + name)
    function = selected[0]
    section = elf.get_section(function['st_shndx'])
    start, size = function['st_value'], function['st_size']
    if start & 1 or not section['sh_flags'] & 4 or not 0 < size <= 16384:
        raise ValueError('Only bounded section-backed ARM functions are supported')
    relocations = module_relocations(elf)
    relevant = {offset: item for (index, offset), item in relocations.items() if index == function['st_shndx']}
    rows = decode_arm_range(section.data(), start, size, relevant)
    calls, data, unknown = [], [], []
    for row in rows:
        relocation = row.get('relocation', {})
        if row.get('kind') == 'instruction_candidate':
            word = int.from_bytes(bytes.fromhex(row['bytes']), 'little')
            if relocation.get('type') in (28, 29):
                calls.append({'offset': row['offset'], 'name': relocation['symbol'],
                    'kind': 'call' if relocation['type'] == 28 else 'branch_relocation',
                    'local': relocation['symbol_section'] != 'SHN_UNDEF',
                    'basis': 'original relocation', 'target_section': relocation['symbol_section']})
            elif word & 0x0f000000 == 0x0b000000 and word >> 28 != 15:  # ARM BL, not BLX immediate.
                delta = (word & 0xffffff) << 2
                if delta & 0x2000000:
                    delta -= 0x4000000
                target = row['offset'] + 8 + delta
                matches = [s for s in functions if s['st_shndx'] == function['st_shndx'] and s['st_value'] == target]
                if len(matches) == 1:
                    calls.append({'offset': row['offset'], 'name': matches[0].name, 'kind': 'call',
                                  'local': True, 'basis': 'original direct BL and exact symbol entry',
                                  'target_section': section.name})
                else:
                    unknown.append({'offset': row['offset'], 'kind': 'unresolved_direct_call', 'target': target})
            elif row.get('mnemonic', '').startswith('blx'):
                unknown.append({'offset': row['offset'], 'kind': 'unresolved_interworking_or_indirect_call',
                                'operands': row.get('operands')})
        literal = row.get('literal', {}).get('relocation')
        if literal:
            data.append({'instruction_offset': row['offset'], **literal})
    return {'name': name, 'section': section.name, 'offset': start, 'size': size,
            'file_offset': section['sh_offset'] + start, 'calls': calls,
            'data_references': data, 'unresolved': unknown, 'instructions': rows}


class Planner:
    def __init__(self, root, entries, cache_dir):
        self.root = Path(root).resolve()
        self.entries = {e['path']: e for e in entries}
        self.cache_dir = Path(cache_dir).resolve()
        if not self.cache_dir.is_relative_to(self.root / 'artifacts'):
            raise ValueError('Analysis cache must remain under artifacts')
        code = b''.join(Path(__file__).with_name(name).read_bytes()
                        for name in ('dependency_plan.py', 'storage_trace.py', 'mount_evidence.py'))
        self.fingerprint = hashlib.sha256(code + capstone.__version__.encode() + elftools.__version__.encode()).hexdigest()
        self.raw = {}
        self.hits = self.misses = self.rejected = 0

    def load(self, path):
        if path not in self.raw:
            entry = self.entries[path]
            self.raw[path] = checked_input(self.root, path, entry['sha256'])
        return self.raw[path]

    def node(self, path, name):
        raw = self.load(path)  # Always verify the input before looking up cached analysis.
        digest = self.entries[path]['sha256']
        key = digest_json({'function': name})
        cache = self.cache_dir / self.fingerprint / digest / (key + '.json')
        if cache.exists():
            try:
                item = bounded_json(cache)
                if (item['input_sha256'] != digest or item['analyzer'] != self.fingerprint
                        or item['function'] != name or digest_json(item['result']) != item['result_sha256']):
                    raise ValueError('Static cache identity/checksum mismatch')
                self.hits += 1
                return item['result']
            except (OSError, ValueError, KeyError, TypeError):
                self.rejected += 1
        result = analyze_function(raw, name)
        cache.parent.mkdir(parents=True, exist_ok=True)
        item = {'input_sha256': digest, 'analyzer': self.fingerprint, 'function': name,
                'result': result, 'result_sha256': digest_json(result)}
        temporary = cache.with_suffix('.tmp')
        temporary.write_text(json.dumps(item, indent=2), encoding='utf-8')
        temporary.replace(cache)
        self.misses += 1
        return result

    def providers(self):
        result = {}
        for path in sorted(self.entries):
            if not path.endswith('.ko'):
                continue
            elf = ELFFile(io.BytesIO(self.load(path)))
            table = elf.get_section_by_name('.symtab')
            if table is None:
                continue
            for symbol in table.iter_symbols():
                if (symbol.name and symbol['st_info']['type'] == 'STT_FUNC'
                        and symbol['st_info']['bind'] in ('STB_GLOBAL', 'STB_WEAK')
                        and isinstance(symbol['st_shndx'], int)):
                    result.setdefault(symbol.name, []).append(path)
        return result

    def graph(self, target, seeds, depth=1, max_nodes=32, cross_module=False):
        if not 0 <= depth <= 5 or not 1 <= max_nodes <= 128 or not 1 <= len(seeds) <= 32:
            raise ValueError('Dependency limits exceeded')
        providers = self.providers()
        pending = deque((target, seed, 0) for seed in seeds)
        visited, nodes, boundaries = set(), [], []
        while pending and len(nodes) < max_nodes:
            path, name, level = pending.popleft()
            if (path, name) in visited:
                continue
            visited.add((path, name))
            try:
                result = self.node(path, name)
            except ValueError as error:
                boundaries.append({'target': path, 'function': name, 'reason': str(error)})
                continue
            node = {'target': path, 'sha256': self.entries[path]['sha256'], 'depth': level, **result}
            nodes.append(node)
            for call in node['calls']:
                candidates = [path] if call['local'] else providers.get(call['name'], [])
                call['provider_candidates'] = candidates
                call['resolution_limit'] = 'Static symbol candidates do not establish exports, module load state or IPC routing.'
                if level < depth and len(candidates) == 1 and (call['local'] or cross_module):
                    pending.append((candidates[0], call['name'], level + 1))
        return {'nodes': nodes, 'boundaries': boundaries,
                'truncated': any((p, n) not in visited for p, n, _ in pending),
                'limits': {'depth': depth, 'max_nodes': max_nodes, 'cross_module': cross_module}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True)
    parser.add_argument('--function', action='append', default=[])
    parser.add_argument('--pc-offset', type=lambda value: int(value, 0), help='Module .text-relative offset, not a runtime VA')
    parser.add_argument('--depth', type=int, default=1)
    parser.add_argument('--max-nodes', type=int, default=32)
    parser.add_argument('--cross-module', action='store_true')
    parser.add_argument('--report-dir', required=True)
    args = parser.parse_args()
    output = (PROJECT_ROOT / args.report_dir).resolve()
    if not output.is_relative_to(PROJECT_ROOT / 'artifacts'):
        parser.error('Reports must remain under artifacts')
    entries = bounded_json(PROJECT_ROOT / 'artifacts/inventory/elf-inventory.json', 64 * 1024 * 1024)['entries']
    planner = Planner(PROJECT_ROOT, entries, PROJECT_ROOT / 'artifacts/cache/dependency-planner')
    if args.target not in planner.entries:
        parser.error('Target is not inventoried')
    seeds = list(args.function)
    if args.pc_offset is not None:
        elf = ELFFile(io.BytesIO(planner.load(args.target)))
        table = elf.get_section_by_name('.symtab')
        matches = [s.name for s in table.iter_symbols() if s['st_info']['type'] == 'STT_FUNC'
                   and isinstance(s['st_shndx'], int) and elf.get_section(s['st_shndx']).name == '.text'
                   and s['st_value'] <= args.pc_offset < s['st_value'] + s['st_size']]
        if len(matches) != 1:
            parser.error('PC offset does not identify one .text function')
        seeds.append(matches[0])
    if not seeds:
        parser.error('Supply --function or --pc-offset')
    output.mkdir(parents=True, exist_ok=False)
    graph = planner.graph(args.target, seeds, args.depth, args.max_nodes, args.cross_module)
    retained = EvidenceCache(PROJECT_ROOT / 'artifacts/tools/rea')
    queries = []
    groups = {}
    for node in graph['nodes']:
        groups.setdefault(node['target'], []).append(node['name'])
        for operation in ('procedure_pseudo_code', 'read_function_instructions'):
            hit = retained.lookup(node['sha256'], operation, node['name'])
            queries.append({'target': node['target'], 'procedure': node['name'], 'operation': operation,
                            'retained': {k: v for k, v in hit.items() if k != 'data'} if hit else None})
    def quote(value):
        return "'" + value.replace("'", "''") + "'"
    commands = []
    for target, names in groups.items():
        for start in range(0, len(names), 24):
            names_chunk = names[start:start + 24]
            plan_id = hashlib.sha256(output.relative_to(PROJECT_ROOT).as_posix().encode()).hexdigest()[:16]
            batch_dir = 'artifacts/tools/rea/plan-' + plan_id + '-' + str(len(commands))
            args_list = ['--target', target, '--report-dir', batch_dir, '--reuse-evidence']
            for name in names_chunk:
                args_list += ['--procedure', name, '--instructions', name]
            prefix = "wsl.exe --cd " + quote('/mnt/' + PROJECT_ROOT.drive[0].lower() + PROJECT_ROOT.as_posix()[2:])
            commands.append(prefix + ' --exec python3 -u -m tools.research.rea_wsl_batch ' + ' '.join(quote(v) for v in args_list))
    report = {'target': args.target, 'seeds': seeds, 'graph': graph, 'rea_queries': queries,
              'cache': {'static_hits': planner.hits, 'static_misses': planner.misses, 'rejected': planner.rejected,
                        'analyzer_fingerprint': planner.fingerprint},
              'rea_commands': commands, 'retained_batches_rejected': retained.rejected,
              'limitations': ['Static ARM ET_REL references only; no firmware execution or successful device/service claims.',
                  'Indirect calls, IPC destinations, runtime files, raw kernel symbols and Thumb functions may remain unresolved.',
                  'Provider candidates are symbol definitions, not verified module exports/load order.',
                  'Cached REA results retain their original provenance; reuse is not a fresh Ghidra analysis.']}
    (output / 'plan.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    (output / 'rea-commands.ps1').write_text('\n'.join(commands) + '\n', encoding='utf-8')
    lines = ['# Dependency plan', '', 'Static research only; no guest behavior supplied.', '',
             f'Target: `{args.target}`', f'Seeds: {", ".join(seeds)}', '',
             f'Functions: {len(graph["nodes"])}; truncated: {graph["truncated"]}.',
             f'Static cache hits/misses: {planner.hits}/{planner.misses}.',
             f'REA evidence reusable: {sum(q["retained"] is not None for q in queries)}/{len(queries)}.', '',
             '| Function | Calls | Data references | Unresolved calls |', '| --- | --- | --- | --- |']
    for node in graph['nodes']:
        lines.append(f'| {node["name"]} | {len(node["calls"])} | {len(node["data_references"])} | {len(node["unresolved"])} |')
    lines += ['', 'See plan.json for original instruction offsets, provider candidates and evidence references.',
              'rea-commands.ps1 contains bounded shared-session commands; it is prepared, not automatically executed.']
    (output / 'summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(output / 'summary.md')
    print('functions:', len(graph['nodes']), 'static cache:', planner.hits, 'hits,', planner.misses, 'misses')
    print('REA cached:', sum(q['retained'] is not None for q in queries), '/', len(queries))


if __name__ == '__main__':
    main()
