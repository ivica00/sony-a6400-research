"""Use a complete actual active-MENU resource header in a separate control.

Only the observed 64-byte header is refreshed. The retained menu, model, arena
and later USB records are still explicitly a non-atomic combined input.
"""
import json
import struct
from tools.research.active_menu_snapshot_probe import HW
from tools.research.prepare_resource_snapshot_control import refresh_records


def main():
    capture = json.loads((HW / 'native-layout-resource-snapshot-pid2896.json').read_text())
    old = json.loads((HW / 'native-layout-snapshot-pid2491.json').read_text())
    log = (HW / 'native-layout-resource-snapshot-pid2896.log').read_text()
    if not capture['complete_binary'] or 'FREEZE threads=176 attached=176 resumed=176 result=0' not in log or 'END result=0' not in log:
        raise ValueError('Complete, successfully resumed active capture required')
    current = next(row for row in capture['records'] if row['size'] == 0x186bc)
    prior = next(row for row in old['records'] if row['size'] == 0x186bc)
    current_raw, prior_raw = bytes.fromhex(current['data']), bytes.fromhex(prior['data'])
    if current_raw[0x1e4:0x200] != prior_raw[0x1e4:0x200]: raise ValueError('Menu binding state differs')
    resource = struct.unpack_from('<I', current_raw, 0x127b4)[0]
    if resource != struct.unpack_from('<I', prior_raw, 0x127b4)[0]: raise ValueError('Menu resource identity differs')
    header = next(row for row in capture['records'] if int(row['address'], 16) == resource and row['size'] == 64)
    raw = bytes.fromhex(header['data'])
    if not struct.unpack_from('<H', raw, 0xc)[0]: raise ValueError('Active capture still has zero references; no positive release control is justified')
    source = json.loads((HW / 'native-menu-activation-dependencies-e0111.json').read_text())
    records, differences = refresh_records(source, [(resource, raw)])
    records.append(dict(address=hex(resource), data=raw.hex(), code=False,
                        source='Actual active MENU header, PID2896 complete capture; other control input remains non-atomic',
                        original_scoped_writes=[dict(address=hex(resource + 0xc), pc='0x64be08c', size=2)]))
    destination = HW / 'native-menu-activation-dependencies-e0113.json'
    destination.write_text(json.dumps(records, indent=2), encoding='utf-8')
    manifest = dict(source_capture_sha256=capture['sha256'], retained_menu=prior['address'], active_menu=current['address'],
                    matching_binding=list(struct.unpack_from('<7i', current_raw, 0x1e4)), resource=hex(resource),
                    actual_header_count=struct.unpack_from('<H', raw, 0xc)[0], differences=differences,
                    whole_input_atomic=False, scope=__doc__)
    (HW / 'native-menu-resource-header-e0113-control.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Observed active header control:', hex(resource), 'actual count', manifest['actual_header_count'], 'overlapping byte differences', len(differences))


if __name__ == '__main__': main()
