"""Capture the list requested by the original activation replay, never its reply.

Native source proves root+0/head, root+4/tail and node+0/next,+4/prev,+8/payload.
Original code still performs its own search after these observed bytes are added.
"""
import json
import struct
from tools.camera_debugger import connect
from tools.research.remote_elf import RemoteElf32, debugger_reader
from tools.research.active_menu_snapshot_probe import ROOT, HW


def main():
    probe = json.loads((ROOT / 'artifacts/analysis/menu-activation-main-thread-snapshot-probe.json').read_text())
    query = probe['resource_list_observations'][-1]
    root = int(query['root'], 16)
    captured = []
    def check(address):
        if address & 3 or not 0x14000 <= address <= 0x5efffff4:
            raise ValueError('List address outside verified camera user range')
    with connect() as debugger:
        elf = RemoteElf32(debugger_reader(debugger, '/usr/lib/libObj.so'))
        # Read-only capture logic is based on these actual original accessors.
        for address in (0x64c8208, 0x64c8210, 0x64c83f4, 0x64c8510):
            code = debugger.memory(149, address, 8)
            if code != elf.virtual(address - 0x5d18000, 8):
                raise ValueError('Original list accessor source mismatch')
        check(root)
        before = debugger.memory(149, root, 8)
        head, tail = struct.unpack('<2I', before)
        address, previous, seen = head, 0, set()
        while address:
            check(address)
            if address in seen or len(seen) >= 1024: raise ValueError('List cycle/limit')
            seen.add(address)
            data = debugger.memory(149, address, 12)
            next_address, prior_address, _payload = struct.unpack('<3I', data)
            if prior_address != previous: raise ValueError('Nonreciprocal observed list links')
            captured.append(dict(address=hex(address), data=data.hex(), code=False,
                                 source='Bounded later USB native resource list; non-atomic MENU state'))
            previous, address = address, next_address
        if previous != tail: raise ValueError('Observed tail differs')
        if debugger.memory(149, root, 8) != before: raise ValueError('List root changed during capture')
    result = dict(read_only=True, atomic=False, complete_bounded_chain=True, query=query,
                  root=dict(address=hex(root), data=before.hex(), code=False,
                            source='Later USB list root, equal before/after traversal'), nodes=captured)
    archive = HW / 'native-resource-list-e0111.json'
    archive.write_text(json.dumps(result, indent=2), encoding='utf-8')
    destination = HW / 'native-menu-activation-dependencies.json'
    records = json.loads(destination.read_text())
    known = {}
    for record in records:
        base = int(record['address'], 16)
        for i, value in enumerate(bytes.fromhex(record['data'])):
            if base + i in known and known[base + i] != value: raise ValueError('Conflicting existing sources')
            known[base + i] = value
    for record in [result['root'], *captured]:
        base = int(record['address'], 16)
        for i, value in enumerate(bytes.fromhex(record['data'])):
            if base + i in known and known[base + i] != value:
                raise ValueError('Later list conflicts with retained state at ' + hex(base + i))
    # No selected node, service return, allocation or navigation result is added.
    destination.write_text(json.dumps([*records, result['root'], *captured], indent=2), encoding='utf-8')
    print('Captured actual list nodes:', len(captured), 'root', hex(root))
    print(archive)


if __name__ == '__main__': main()
