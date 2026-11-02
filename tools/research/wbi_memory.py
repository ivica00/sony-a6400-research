"""Bounded preserved WBI1 memory extraction; not a live camera snapshot or boot."""
import argparse
import hashlib
import json
import struct

from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input

IMAGE = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha5'
LENGTHS = tuple(range(3, 17)) + (32, 64)


def inflate_block(data, position, maximum):
    if not 0 <= position < len(data) or not 0 < maximum <= 4 * 1024 * 1024:
        raise ValueError('Invalid bounded LZ77 source/output range')
    out = bytearray()

    def take(count):
        nonlocal position
        if count < 0 or position + count > len(data):
            raise ValueError('Compressed block exceeds supplied bytes')
        result = data[position:position + count]
        position += count
        return result

    def append(value):
        if len(out) + len(value) > maximum:
            raise ValueError('Decompressed block exceeds declared extent')
        out.extend(value)

    kind = take(1)[0]
    if kind == 0x0f:
        take(1)
        count = int.from_bytes(take(2), 'little')
        append(take(count))
    elif kind == 0xf0:
        while True:
            flags = take(1)[0]
            if flags == 0:
                append(take(8))
                continue
            for bit in range(8):
                if flags >> bit & 1:
                    a, b = take(2)
                    distance = (a & 15) << 8 | b
                    if distance == 0:
                        return bytes(out), position
                    length = LENGTHS[a >> 4]
                    if distance > len(out):
                        raise ValueError('LZ77 reference precedes block output')
                    pattern = out[-distance:]
                    append((pattern * ((length + distance - 1) // distance))[:length])
                else:
                    append(take(1))
    else:
        raise ValueError('Unsupported LZ77 block type')
    return bytes(out), position


def parse_sections(raw):
    if len(raw) < 44:
        raise ValueError('Truncated WBI header')
    h = struct.unpack_from('<11I', raw)
    if raw[:4] != b'WBI1' or h[4] != 0x20060224 or not h[2] & 1:
        raise ValueError('Unsupported WBI identity/version/compression')
    if not 0 < h[1] <= 4096 or h[5] not in (512, 1024, 2048, 4096):
        raise ValueError('Unsupported WBI header bounds')
    start = h[5]
    while start + h[5] <= len(raw) and raw[start:start + h[5]] in (bytes(h[5]), b'\xff' * h[5]):
        start += h[5]
    table = start + h[6]
    if table + h[1] * 32 > len(raw) or not 0 < h[10] <= 256 * 1024 * 1024:
        raise ValueError('WBI section table/output exceeds bounds')
    sections, offset = [], start
    for index in range(h[1]):
        addr, size, checksum, flag, expanded, virt, pad, meta = struct.unpack_from('<8I', raw, table + index * 32)
        if (not 0 < size or not 0 < expanded <= 4 * 1024 * 1024 or offset + size > table
                or addr + expanded > 1 << 32 or virt + expanded > 1 << 32):
            raise ValueError('WBI section escapes declared ranges')
        sections.append({'index': index, 'physical': addr, 'virtual': virt, 'size': expanded,
            'compressed_offset': offset, 'compressed_size': size, 'checksum_field': checksum,
            'flag': flag, 'pad': pad, 'metadata_field': meta,
            'metadata_xor_matches': meta == addr ^ size ^ flag ^ expanded ^ virt ^ pad})
        offset += size
    if offset != table or sum(s['size'] for s in sections) != h[10]:
        raise ValueError('WBI aggregate lengths disagree')
    return {'magic': 'WBI1', 'sections': h[1], 'flag': h[2], 'resume_vector': h[3],
            'version': h[4], 'sector_size': h[5], 'data_offset': start, 'data_size': h[6],
            'kernel_start': h[7], 'kernel_size': h[8], 'kernel_checksum_field': h[9],
            'expanded_size': h[10]}, sections


def decode_section(raw, section):
    begin = section['compressed_offset']
    if (begin < 0 or section['compressed_size'] <= 0 or begin + section['compressed_size'] > len(raw)
            or not 0 < section['size'] <= 4 * 1024 * 1024):
        raise ValueError('Section input/output range exceeds bounds')
    data = raw[begin:begin + section['compressed_size']]
    output, position, blocks = bytearray(), 0, 0
    while len(output) < section['size']:
        value, position = inflate_block(data, position, section['size'] - len(output))
        if not value:
            raise ValueError('Empty block before section completion')
        output.extend(value)
        blocks += 1
    return bytes(output), blocks, position


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', required=True)
    args = parser.parse_args()
    output = (PROJECT_ROOT / args.report_dir).resolve()
    if not output.is_relative_to(PROJECT_ROOT / 'artifacts'):
        parser.error('Output must remain under artifacts')
    inventory = json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text(encoding='utf-8'))['inputs']
    digest = next(r['sha256'] for r in inventory if r['path'] == IMAGE)
    raw = checked_input(PROJECT_ROOT, IMAGE, digest)
    header, sections = parse_sections(raw)
    output.mkdir(parents=True, exist_ok=False)
    results = []
    report = {'input': {'path': IMAGE, 'sha256': digest}, 'header': header, 'status': 'extracting', 'sections': results,
        'format_basis': 'Preserved fwtool.py/fwtool/sony/wbi.py and fwtool/lz77/__init__.py; bounded independent decoder.',
        'limitations': ['Package warm-boot image, not a capture from the user camera or proof of active runtime state.',
            'Checksum fields are retained; XOR matches are observations, not a verified kernel checksum contract.',
            'No memory/MMIO injected into the application; no device operations or firmware writes.']}
    try:
        for section in sections:
            data, blocks, used = decode_section(raw, section)
            filename = f'{section["index"]:04d}-pa{section["physical"]:08x}-va{section["virtual"]:08x}.bin'
            (output / filename).write_bytes(data)
            hits = {}
            for needle in (b'LOGB', b'ULOG', b'ulogio.bin', b'DmmConfig.bin'):
                positions, start = [], 0
                while (index := data.find(needle, start)) >= 0:
                    if len(positions) >= 256:
                        break
                    positions.append(index)
                    start = index + 1
                if positions:
                    hits[needle.decode()] = positions
            results.append({**section, 'file': filename, 'sha256': hashlib.sha256(data).hexdigest(),
                            'blocks': blocks, 'compressed_bytes_consumed': used, 'string_candidates': hits})
            if hits:
                print(section['index'], hex(section['physical']), hits, flush=True)
        checked_input(PROJECT_ROOT, IMAGE, digest)
        report['status'] = 'completed'
    except Exception as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        (output / 'manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output / 'manifest.json', header['sections'], header['expanded_size'])


if __name__ == '__main__':
    main()
