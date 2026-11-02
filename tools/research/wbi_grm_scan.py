"""Locate references to the candidate GRM node; no virtual mapping is inferred."""
import argparse
import json
import struct

from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input
from tools.research.wbi_memory import IMAGE, decode_section
from tools.research.wbi_logging_trace import PackageMemory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', required=True)
    parser.add_argument('--reference-offset', type=int, choices=(0, 20), default=20,
                        help='Reference to object (0) or embedded list link (20)')
    args = parser.parse_args()
    output = (PROJECT_ROOT / args.report_dir).resolve()
    if not output.is_relative_to(PROJECT_ROOT / 'artifacts'):
        parser.error('Output must remain under artifacts')
    output.mkdir(parents=True, exist_ok=False)
    rows = json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text())['inputs']
    digest = next(r['sha256'] for r in rows if r['path'] == IMAGE)
    memory = PackageMemory(checked_input(PROJECT_ROOT, IMAGE, digest))
    candidate = 0x08a96220
    node = memory.read(candidate, 48)
    if node[28:38] != b'gl_common\0':
        raise ValueError('Candidate name changed')
    needle = struct.pack('<I', candidate + 0x60000000 + args.reference_offset)
    hits = []
    for section in memory.sections:
        data = decode_section(memory.raw, section)[0]
        start = 0
        while (offset := data.find(needle, start)) >= 0:
            if offset % 4 == 0:
                hits.append({'section': section['index'], 'physical': section['physical'] + offset,
                    'declared_virtual': section['virtual'] + offset,
                    'context_offset': max(0, offset - 16),
                    'context_hex': data[max(0, offset - 16):offset + 24].hex()})
            start = offset + 1
    checked_input(PROJECT_ROOT, IMAGE, digest)
    # This is a candidate backing location identified by the reciprocal tail
    # pointer, not a page-table-derived translation of the VMALLOC address.
    head_physical, head_virtual = 0x096ce348, 0x5f3fc348
    first, last = struct.unpack('<2I', memory.read(head_physical, 8))
    nodes, current, previous = [], first, head_virtual
    while current != head_virtual:
        if len(nodes) >= 1024 or any(n['link'] == current for n in nodes):
            raise ValueError('Candidate list cycle/limit')
        if not 0x60000014 <= current < 0xa0000000:
            raise ValueError('Candidate node lacks verified cached conversion')
        address = current - 0x60000000 - 20
        data = memory.read(address, 48)
        words = struct.unpack('<12I', data)
        if words[6] != previous:
            raise ValueError('Candidate reciprocal link mismatch')
        nodes.append({'link': current, 'physical': address, 'words': list(words),
                      'name_hex': data[28:44].hex()})
        previous, current = current, words[5]
    if previous != last or sum(n['physical'] == candidate for n in nodes) != 1:
        raise ValueError('Candidate head/tail membership mismatch')
    checked_input(PROJECT_ROOT, IMAGE, digest)
    report = {'input': {'path': IMAGE, 'sha256': digest}, 'candidate_physical': candidate,
        'candidate_words': list(struct.unpack('<12I', node)), 'references': hits,
        'head_pointer': struct.unpack_from('<I', node, 20)[0],
        'head_declared_mappings': [s for s in memory.sections
            if s['virtual'] <= 0x5f3fc348 < s['virtual'] + s['size']],
        'candidate_head_physical': head_physical, 'reciprocal_list': nodes,
        'reciprocal_list_count': len(nodes),
        'limitations': ['Aligned byte references alone do not validate allocator ownership.',
            'Reciprocal structure supports a candidate head backing location; no page-table translation is proven.',
            'No original lookup execution, allocator response or current-camera state supplied.']}
    if args.reference_offset != 20:
        report['reference_offset'] = args.reference_offset
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    print(output / 'report.json', 'references', len(hits), 'reciprocal nodes', len(nodes))


if __name__ == '__main__':
    main()
