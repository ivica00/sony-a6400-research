"""Prepare a separately labelled replay with an observed coherent heap subset.

Never merge contradictory observations silently. Original captures are retained;
only byte ranges completely covered by the explicit native snapshot are refreshed.
The rest of the combined MENU/USB input remains non-atomic.
"""
import hashlib
import json
from tools.research.active_menu_snapshot_probe import HW


def refresh_records(source, regions, allow_identical_code=False):
    refreshed, conflicts = [], []
    observed = {}
    for base, chunk in regions:
        for i, value in enumerate(chunk):
            address = base + i
            if address in observed and observed[address] != value:
                raise ValueError('Contradictory replacement regions')
            observed[address] = value
    for record in source:
        address = int(record['address'], 16); data = bytes.fromhex(record['data'])
        keep = []
        for i, value in enumerate(data):
            at = address + i
            if at in observed:
                if record['code']:
                    if not allow_identical_code or observed[at] != value:
                        raise ValueError('Refusing to refresh executable bytes')
                    keep.append(i)
                elif observed[at] != value:
                    conflicts.append(dict(address=hex(at), retained=value, refreshed=observed[at]))
            else: keep.append(i)
        # Preserve any explicit write contracts even if all their source bytes
        # are replaced by the newer complete region.
        contracts = {key: record[key] for key in ('original_scoped_writes', 'original_cache_writes') if key in record}
        if contracts:
            refreshed.append(dict(address=record['address'], data='', code=False, source='Retained exact-PC mutation contracts; data supplied by separately qualified records', **contracts))
        index = 0
        while index < len(keep):
            start = keep[index]; end = start + 1; index += 1
            while index < len(keep) and keep[index] == end: end += 1; index += 1
            fragment = data[start:end]
            metadata = {key: value for key, value in record.items() if key not in ('address', 'data', 'sha256', *contracts)}
            refreshed.append(dict(**metadata, address=hex(address + start), data=fragment.hex(), sha256=hashlib.sha256(fragment).hexdigest()))
    return refreshed, conflicts


def main():
    run = json.loads((HW / 'native-resource-snapshot-e0111-v2-run.json').read_text())
    raw = (HW / 'native-resource-snapshot-e0111.bin').read_bytes()
    if run['status'] or run['flags'] or len(raw) != 0x4a8 or 'SNAPSHOT result=0 threads=175 confirmed=175 resumed=175' not in run['log'] or 'END result=0 bytes=1192' not in run['log']:
        raise ValueError('Complete successful native capture required')
    source = json.loads((HW / 'native-menu-activation-dependencies.json').read_text())
    regions = [(0x27800000, raw[:0x450]), (0x27837c70, raw[0x450:0x4a0]), (0x6c8cc, raw[0x4a0:])]
    chain = json.loads((HW / 'native-resource-list-e0111.json').read_text())
    if bytes.fromhex(chain['root']['data']) != regions[2][1]: raise ValueError('Resource list root changed')
    node = next(row for row in chain['nodes'] if row['address'] == '0x27837c80')
    if bytes.fromhex(node['data']) != raw[0x460:0x46c]: raise ValueError('Selected resource node changed')
    refreshed, conflicts = refresh_records(source, regions)
    for address, data in regions:
        record = dict(address=hex(address), data=data.hex(), code=False,
                      source='E0111 coherent native subset with 175 process threads stopped; whole MENU/USB input is NOT atomic')
        if address == 0x27800000:
            record['original_scoped_writes'] = [dict(address='0x27800010', pc='0xffff0fcc')]
        refreshed.append(record)
    destination = HW / 'native-menu-activation-dependencies-e0111.json'
    destination.write_text(json.dumps(refreshed, indent=2), encoding='utf-8')
    manifest = dict(source_unchanged=True, whole_input_atomic=False, snapshot_sha256=hashlib.sha256(raw).hexdigest(),
                    refreshed_regions=[dict(address=hex(a), size=len(b)) for a, b in regions], conflicts=conflicts)
    (HW / 'native-resource-snapshot-e0111-refresh-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Separate resource control prepared; explicitly refreshed differences:', len(conflicts))
    print(destination)


if __name__ == '__main__': main()
