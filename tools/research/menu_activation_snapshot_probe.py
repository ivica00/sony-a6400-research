"""Attempt original ListTab activation on captured state; stop at missing evidence.

The caller explicitly supplies the captured selected node. This is offline
execution, not proof of the originating physical input or application thread.
"""
import json
import argparse
import re
import struct
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_INVALID
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC, UC_ARM_REG_C13_C0_3
from tools.research.active_menu_snapshot_probe import ROOT, HW


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--main-thread-control', action='store_true')
    args = parser.parse_args()
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    pages, known, executable = set(), {}, []
    writes, trace = [], []
    boundary = {}
    scoped_writes = set()
    menu, stack, end = 0x10f61008, 0x8300000, 0x8310000
    snapshot = json.loads((HW / 'native-layout-snapshot-pid2491.json').read_text())
    if not snapshot['complete_binary']: raise ValueError('Complete menu required')
    path = json.loads((HW / 'native-setting-node-after-layout-pid2491.json').read_text())['path']
    node_addresses = set()
    def supply(address, data, code=False):
        for i, value in enumerate(data):
            if address + i in known and known[address + i] != value:
                raise ValueError('Conflicting source captures at ' + hex(address + i))
        for page in range(address & ~4095, (address + len(data) + 4095) & ~4095, 4096):
            if page not in pages: uc.mem_map(page, 4096); pages.add(page)
        uc.mem_write(address, data)
        known.update({address + i: value for i, value in enumerate(data)})
        if code: executable.append((address, address + len(data)))
    for record in snapshot['records']: supply(int(record['address'], 16), bytes.fromhex(record['data']))
    for node in path:
        for record in [node, *node['children']]:
            address = int(record['object'], 16); node_addresses.add(address)
            supply(address, bytes.fromhex(record['data']))
        if node['array']: supply(int(node['array_address'], 16), bytes.fromhex(node['array']))
    binding = json.loads((HW / 'native-menu-binding-contracts.json').read_text())
    for table in binding['vtables']: supply(int(table['address'], 16), bytes.fromhex(table['data']))
    supply(0x16925a00, (HW / 'native-setting-node-code.bin').read_bytes(), True)
    supply(0x15b90000, (HW / 'native-listtab-code-component.bin').read_bytes(), True)
    supply(0x6305000, (HW / 'native-widget-geometry-component.bin').read_bytes(), True)
    for record in json.loads((HW / 'native-widget-worldpos-contracts.json').read_text())['additional']:
        supply(int(record['address'], 16), bytes.fromhex(record['data']), record['code'])
    extra = HW / 'native-menu-activation-dependencies.json'
    if extra.exists():
        for record in json.loads(extra.read_text()):
            supply(int(record['address'], 16), bytes.fromhex(record['data']), record['code'])
            for mutation in record.get('original_cache_writes', []) + record.get('original_scoped_writes', []):
                scoped_writes.add((int(mutation['address'], 16), int(mutation['pc'], 16), mutation.get('size', 4)))
    for address in (stack, end): uc.mem_map(address, 4096)
    uc.reg_write(UC_ARM_REG_C1_C0_2, 0xf << 20); uc.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
    if args.main_thread_control:
        context = json.loads((HW / 'native-main-thread-context-v2.json').read_text())
        if context['status'] or context['flags'] or 'END result=0 errno=0' not in context['log']:
            raise ValueError('Complete successful thread capture required')
        match = re.search(r'CONTEXT tid=149 tls=([0-9a-f]{8}).*address=([0-9a-f]{8}) data=([0-9a-f]{32})', context['log'])
        if not match: raise ValueError('Malformed thread capture')
        tls, address = int(match[1], 16), int(match[2], 16)
        data = bytes.fromhex(match[3])
        if address != tls - 0x4c0 + 0x60 or struct.unpack_from('<I', data, 8)[0] != 149:
            raise ValueError('Captured pthread identity differs')
        supply(address, data)
        uc.reg_write(UC_ARM_REG_C13_C0_3, tls)
        supply(0xffff0f60, (HW / 'native-kuser-template.bin').read_bytes(), True)
    def instruction(_uc, address, size, _data):
        if not any(lo <= address < address + size <= hi for lo, hi in executable):
            boundary.update(kind='code', address=hex(address), size=size)
            raise ValueError('Uncaptured original code ' + hex(address))
        trace.append(hex(address))
    def read(_uc, _access, address, size, _value, _data):
        if not all(byte in known for byte in range(address, address + size)):
            boundary.update(kind='data', address=hex(address), size=size)
            raise ValueError('Uncaptured data ' + hex(address) + ' size=' + str(size))
    def write(_uc, _access, address, size, value, _data):
        allowed = (stack <= address < address + size <= stack + 4096 or
                   menu <= address < address + size <= menu + 0x186bc and all(byte in known for byte in range(address, address + size)) or
                   (address, uc.reg_read(UC_ARM_REG_PC), size) in scoped_writes and all(byte in known for byte in range(address, address + size)) or
                   size == 4 and any(address == node + offset for node in node_addresses for offset in (0x18, 0x24)))
        if not allowed:
            boundary.update(kind='write', address=hex(address), size=size, value=hex(value))
            raise ValueError('Unverified original mutation ' + hex(address))
        known.update({address + i: (value >> (8 * i)) & 255 for i in range(size)})
        if not stack <= address < stack + 4096:
            writes.append(dict(address=hex(address), offset=hex(address - menu), size=size, value=hex(value), pc=hex(uc.reg_read(UC_ARM_REG_PC))))
    def invalid(_uc, _access, address, size, _value, _data):
        if boundary.get('kind') != 'write':
            boundary.update(kind='unmapped', access=_access, address=hex(address), size=size)
        raise ValueError('Unmapped original access ' + hex(address) + ' size=' + str(size))
    uc.hook_add(UC_HOOK_CODE, instruction); uc.hook_add(UC_HOOK_MEM_READ, read)
    uc.hook_add(UC_HOOK_MEM_WRITE, write); uc.hook_add(UC_HOOK_MEM_INVALID, invalid)
    uc.reg_write(UC_ARM_REG_R0, menu); uc.reg_write(UC_ARM_REG_R1, int(path[3]['object'], 16))
    uc.reg_write(UC_ARM_REG_SP, stack + 0xff0); uc.reg_write(UC_ARM_REG_LR, end | 1)
    error = None
    try: uc.emu_start(0x15b92045, end, count=50000)
    except Exception as exception: error = str(exception)
    returned = uc.reg_read(UC_ARM_REG_PC) == end and error is None
    if not returned and error is None: error = 'Original instruction bound reached'
    report = dict(scope=__doc__, source_non_atomic=True, returned=returned,
                  explicit_main_thread_control=args.main_thread_control, originating_ui_thread_proven=False,
                  instructions=len(trace), error=error, boundary=boundary, pc=hex(uc.reg_read(UC_ARM_REG_PC)),
                  registers={name: hex(uc.reg_read(reg)) for name, reg in [('r0', UC_ARM_REG_R0), ('r1', UC_ARM_REG_R1), ('r2', UC_ARM_REG_R2), ('r3', UC_ARM_REG_R3), ('lr', UC_ARM_REG_LR)]},
                  writes=writes, trace=trace, activation_success_proven=False)
    destination = ROOT / 'artifacts/analysis' / ('menu-activation-main-thread-snapshot-probe.json' if args.main_thread_control else 'menu-activation-snapshot-probe.json')
    destination.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key not in ('trace', 'writes', 'scope')}, indent=2))
    print(destination)


if __name__ == '__main__': main()
