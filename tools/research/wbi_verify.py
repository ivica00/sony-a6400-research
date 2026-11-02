"""Cross-check bounded WBI decoding against the preserved fwtool decoder."""
import hashlib
import importlib.util
import io
import json

from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input
from tools.research.wbi_memory import IMAGE, parse_sections, decode_section
from tools.research.wbi_logging_trace import PackageMemory

KERNEL = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'


def main():
    rows = json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text(encoding='utf-8'))['inputs']
    hashes = {r['path']: r['sha256'] for r in rows}
    raw = checked_input(PROJECT_ROOT, IMAGE, hashes[IMAGE])
    kernel = checked_input(PROJECT_ROOT, KERNEL, hashes[KERNEL])
    source = PROJECT_ROOT / 'fwtool.py/fwtool/lz77/__init__.py'
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location('preserved_fwtool_lz77', source)
    decoder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(decoder)
    header, sections = parse_sections(raw)
    checks = []
    for section in sections:
        # First bound/validate independently before invoking the reference.
        bounded, count, used = decode_section(raw, section)
        offset = section['compressed_offset']
        stream = io.BytesIO(raw[offset:offset + section['compressed_size']])
        reference = bytearray()
        for _ in range(count):
            reference.extend(decoder.inflateLz77(stream))
        if bytes(reference) != bounded or stream.tell() != used:
            raise ValueError('WBI decoder disagreement in section ' + str(section['index']))
        checks.append({'index': section['index'], 'size': len(bounded), 'blocks': count,
                       'sha256': hashlib.sha256(bounded).hexdigest(), 'reference_equal': True})
    memory = PackageMemory(raw)
    matches = []
    for address, size in ((0x60108000, 256), (0x6011fdec, 56), (0x6012534c, 52), (0x601256ec, 60)):
        observed = memory.read(address - 0x60000000, size)
        expected = kernel[address - 0x60108000:address - 0x60108000 + size]
        matches.append({'virtual': address, 'size': size, 'matches': observed == expected,
                        'snapshot_sha256': hashlib.sha256(observed).hexdigest()})
    if source_hash != hashlib.sha256(source.read_bytes()).hexdigest():
        raise ValueError('Reference decoder changed during verification')
    report = {'inputs': {IMAGE: hashes[IMAGE], KERNEL: hashes[KERNEL]},
        'reference_source': str(source.relative_to(PROJECT_ROOT)), 'reference_sha256': source_hash,
        'section_count': len(checks), 'expanded_size': header['expanded_size'], 'sections': checks,
        'kernel_window_comparisons': matches,
        'limitations': ['Byte agreement validates this decoding comparison, not boot or hardware equivalence.',
            'Selected kernel windows do not establish complete live-module identity or current-camera state.',
            'WBI checksum fields remain distinct from SHA-256 identity and this decoder comparison.']}
    output = PROJECT_ROOT / 'artifacts/execution/wbi-decoder-verification.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output, len(checks), 'reference matches; kernel windows:', [m['matches'] for m in matches])


if __name__ == '__main__':
    main()
