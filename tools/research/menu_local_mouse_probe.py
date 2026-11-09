"""Original framebuffer-to-local transform on retained rows, explicit mouse fixture.

The singleton relocation/storage come from live USB reads. Mouse positions are
explicit offline inputs; this is not a contemporaneous physical menu capture.
"""
import json
from tools.research.active_menu_snapshot_probe import HW, ROOT, geometry


def main():
    capture = json.loads((HW / 'native-layout-resource-snapshot-pid1175.json').read_text())
    menu = next(int(r['address'], 16) for r in capture['records'] if r['size'] == 0x186bc)
    got = json.loads((HW / 'native-local-mouse-got-e0129.json').read_text())
    if got['data'] != '58801007' or got['storage_data'] != 'f0560900':
        raise ValueError('Unexpected singleton relocation/storage')
    records = list(capture['records'])
    records += [dict(address=got['address'], data=got['data']),
                dict(address=got['storage'], data=got['storage_data'])]
    known = {}
    for r in records:
        for i, value in enumerate(bytes.fromhex(r['data'])):
            address = int(r['address'], 16)+i
            if address in known and known[address] != value:
                raise ValueError('Conflicting retained inputs')
            known[address] = value
    world = json.loads((HW / 'native-widget-worldpos-contracts.json').read_text())
    for r in world['additional']:
        for i, value in enumerate(bytes.fromhex(r['data'])):
            address = int(r['address'], 16)+i
            if address in known and known[address] != value:
                raise ValueError('Conflicting geometry dependency')
    trace = json.loads((HW / 'menu-touch-trace-read-20261106-195941.json').read_text())
    points = [e['framebuffer_xy'] for e in trace['committed_events']]
    points += [[320, 150+50*i] for i in range(6)]
    results, writes, fixes = geometry(records,
        [menu+0x9350+i*0x1118 for i in range(6)], points, mouse_fixture=(0, 0x956f0))
    report = dict(scope=__doc__, capture_sha256=capture['sha256'], results=results,
        emulator_cache_writes=writes, stale_it_workarounds=fixes,
        physical_current_geometry_proven=False)
    destination = ROOT / 'artifacts/analysis/menu-local-mouse-e0129.json'
    destination.write_text(json.dumps(report, indent=2), encoding='utf-8')
    for r in results:
        if not r['returned']:
            raise ValueError(r)
        for result in r['hit_results']:
            if result['native_world_roundtrip'] != result['point']:
                raise ValueError('Original world/local roundtrip differs')
    print('72 original local/world mouse roundtrips match explicit framebuffer points')
    print('Local-input NEGATIVE/control hits (not native hit routing):',
          [[i+1 for i, r in enumerate(results) if r['hit_results'][j]['local_input_control_hit']]
           for j in range(6)])


if __name__ == '__main__':
    main()
