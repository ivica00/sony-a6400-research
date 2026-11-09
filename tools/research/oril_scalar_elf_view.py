"""Create a byte-preserving, bounded ELF analysis view of retained ORIL code.

Not a runnable/bootable camera payload. Selected regions retain original VAs;
omitted code, kernel imports and mutable runtime data are not synthesized.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'artifacts/hardware/av-cam-camera-original.bin'
SHA = 'dd8f8d0cc74ad4b70100e5728cf8b159b5155e7fb50eaf1147b99c9054740209'
BASE = 0x635c6000


def build(destination):
    blob = SOURCE.read_bytes()
    if hashlib.sha256(blob).hexdigest() != SHA or blob[4:8] != b'ORIL':
        raise ValueError('Retained current-camera image identity mismatch')
    if struct.unpack_from('<I', blob, 12)[0] - 0x44 != BASE:
        raise ValueError('ORIL linked-base contract mismatch')
    regions = [('.text.scalar', 0x4c6000, 0x4e1000, 6),
               ('.text.helpers', 0x7ce000, 0x7d4000, 6),
               ('.tables', 0x87d000, 0x87e000, 2),
               ('.rodata.scalar', 0x9b0000, 0x9b8000, 2),
               ('.data.image', 0xb00000, len(blob), 3)]
    names = b'\0'; name_offsets = {}
    for name in [r[0] for r in regions] + ['.strtab', '.symtab', '.shstrtab']:
        name_offsets[name] = len(names); names += name.encode() + b'\0'
    entries = [('ScalarInfraAsyncMain_candidate', 0x4cac38, 1),
               ('ScalarGetJpeg_candidate', 0x4cba3c, 1),
               ('ScalarGetReady_candidate', 0x4cb61c, 1),
               ('ScalarFreeReady_candidate', 0x4cb5a8, 1),
               ('ScalarSyncFactory_candidate', 0x4cf4d0, 1),
               ('ScalarSyncManagerCtor_candidate', 0x4c99ec, 1),
               ('ScalarReply_candidate', 0x4ce948, 1),
               ('ScalarPathJpegPredicate_candidate', 0x7cf12a, 2),
               ('ScalarGetJpegPredicate_candidate', 0x7cf21e, 2),
               ('ScalarGetInfoPredicate_candidate', 0x7cf204, 2)]
    entries += [('ScalarJpegOpen_candidate', 0x4cb8c0, 1),
                ('ScalarJpegClose_candidate', 0x4cb4c4, 1),
                ('ScalarBufferFind_candidate', 0x7ce8ca, 2),
                ('ScalarBufferDetach_candidate', 0x7ce8b0, 2),
                ('ScalarJpegPrepare_candidate', 0x4cb6c4, 1),
                ('ScalarPayload_candidate', 0x7cf0cc, 2),
                ('ScalarBufferClear_candidate', 0x7ce894, 2)]
    symbol_name = b'\0'; symbols = bytes(16)
    # Metadata annotations from direct branch targets/prologues, not source names.
    for name, address, section in entries:
        index = len(symbol_name); symbol_name += name.encode()+b'\0'
        symbols += struct.pack('<IIIBBH', index, BASE+address+1, 0, 0x12, 0, section)
    phnum = len(regions)
    output = bytearray(bytes(52 + 32 * phnum))
    sections = [(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)]
    segments = []; lineage = []
    for name, start, end, flags in regions:
        output.extend(bytes((-len(output)) % 4096)); offset = len(output)
        output.extend(blob[start:end])
        sections.append((name_offsets[name], 1, flags, BASE+start, offset,
                         end-start, 0, 0, 4, 0))
        pf = 4 | (1 if flags & 4 else 0) | (2 if flags & 1 else 0)
        segments.append((1, offset, BASE+start, BASE+start, end-start, end-start, pf, 4096))
        lineage.append({'section': name, 'source_offset': start, 'length': end-start,
                        'vaddr': BASE+start,
                        'sha256': hashlib.sha256(blob[start:end]).hexdigest()})
    stridx = len(sections); offset = len(output); output.extend(symbol_name)
    sections.append((name_offsets['.strtab'], 3, 0, 0, offset, len(symbol_name), 0, 0, 1, 0))
    output.extend(bytes((-len(output)) % 4)); offset = len(output); output.extend(symbols)
    sections.append((name_offsets['.symtab'], 2, 0, 0, offset, len(symbols), stridx, 1, 4, 16))
    shstridx = len(sections); offset = len(output); output.extend(names)
    sections.append((name_offsets['.shstrtab'], 3, 0, 0, offset, len(names), 0, 0, 1, 0))
    output.extend(bytes((-len(output)) % 4)); shoff = len(output)
    for section in sections: output.extend(struct.pack('<10I', *section))
    ident = b'\x7fELF\x01\x01\x01' + bytes(9)
    output[:52] = struct.pack('<16sHHIIIIIHHHHHH', ident, 2, 40, 1,
                             BASE+0x4cac39, 52, shoff, 0x05000200,
                             52, 32, phnum, 40, len(sections), shstridx)
    for i, segment in enumerate(segments):
        struct.pack_into('<8I', output, 52+32*i, *segment)
    destination.write_bytes(output)
    return {'source': str(SOURCE.relative_to(ROOT)), 'source_sha256': SHA,
            'view_sha256': hashlib.sha256(output).hexdigest(), 'regions': lineage,
            'candidate_entry_annotations': entries,
            'limitations': ['Derived static analysis view only, not target firmware.',
                            'Unmapped callees and uncaptured runtime state remain unknown.',
                            'Candidate function name inferred from original diagnostic xrefs.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(); out = args.output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):
        parser.error('Output must stay under artifacts')
    out.mkdir(parents=True, exist_ok=False)
    report = build(out/'scalar-view.elf')
    (out/'manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Created byte-preserving ORIL scalar analysis view:', report['view_sha256'])


if __name__ == '__main__': main()
