"""Hash-checked bounded scan for logging configuration memory tags in preserved inputs."""
import hashlib
import json
import struct

from project_paths import PROJECT_ROOT


def scan_file(path, expected, length):
    digest = hashlib.sha256()
    found, tail, position = [], b'', 0
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            data = tail + chunk
            base = position - len(tail)
            start = 0
            while (index := data.find(b'LOGB', start)) >= 0:
                start = index + 1
                if index < 4 or index + 12 > len(data):
                    continue
                size = struct.unpack_from('<I', data, index - 4)[0]
                offset = base + index - 4
                if 16 <= size <= 4096 and offset + size <= length:
                    candidate = {'offset': offset, 'record_size': size,
                                 'physical_base': struct.unpack_from('<I', data, index + 4)[0],
                                 'memory_size': struct.unpack_from('<I', data, index + 8)[0]}
                    if candidate not in found:
                        found.append(candidate)
            tail = data[-24:]
            position += len(chunk)
    if position != length or digest.hexdigest() != expected:
        raise ValueError('Preserved scan input length/hash mismatch: ' + str(path))
    return found


def main():
    inventory = json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text(encoding='utf-8'))
    matches, count, size = [], 0, 0
    for row in inventory['inputs']:
        path = (PROJECT_ROOT / row['path']).resolve()
        if not path.is_relative_to((PROJECT_ROOT / 'firmware').resolve()):
            raise ValueError('Scan input escapes preserved firmware')
        candidates = scan_file(path, row['sha256'], row['bytes'])
        count += 1
        size += row['bytes']
        if candidates:
            matches.append({'path': row['path'], 'sha256': row['sha256'], 'candidates': candidates})
    report = {'inventory_sha256': hashlib.sha256((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_bytes()).hexdigest(),
              'files_checked': count, 'bytes_checked': size, 'matches': matches,
              'limits': ['Only raw LOGB records with plausible declared length are candidates, not validated configurations.',
                         'Compressed/encrypted representations and unpreserved runtime files are not ruled out.',
                         'No camera operations, decompression, input modification or metadata updates performed.']}
    output = PROJECT_ROOT / 'artifacts/execution/ulogio-input-scan.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output, count, size, 'candidate files:', len(matches))


if __name__ == '__main__':
    main()
