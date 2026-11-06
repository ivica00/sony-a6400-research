"""Associate captured row geometry with original indexed-node lookup results.

The refresh loop association is static source evidence; only indexed lookup is
executed here. The model was captured later in USB, so matching binding fields
do not establish atomicity or complete refresh/activation.
"""
import json
import hashlib
import struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC

ROOT = Path(__file__).resolve().parents[2]
HW = ROOT / 'artifacts/hardware'


def indexed_lookup(path, index):
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    known, pages = set(), set()
    stack, output, end = 0x8300000, 0x8310000, 0x8320000
    start = 0x16925a00
    code = (HW / 'native-setting-node-code.bin').read_bytes()
    table = bytes.fromhex(json.loads((HW / 'native-setting-node-hierarchy-usb.json').read_text())['vtable'])
    def supply(address, data):
        for page in range(address & ~4095, (address + len(data) + 4095) & ~4095, 4096):
            if page not in pages:
                uc.mem_map(page, 4096); pages.add(page)
        uc.mem_write(address, data); known.update(range(address, address + len(data)))
    supply(start, code); supply(0x16c183e8, table)
    for node in path:
        supply(int(node['object'], 16), bytes.fromhex(node['data']))
        if node['array']:
            supply(int(node['array_address'], 16), bytes.fromhex(node['array']))
        for child in node['children']:
            supply(int(child['object'], 16), bytes.fromhex(child['data']))
    for address in (stack, output, end): uc.mem_map(address, 4096)
    count = 0
    def instruction(_uc, address, size, _data):
        nonlocal count
        if not start <= address < address + size <= start + len(code):
            raise ValueError('Uncaptured indexed-lookup code ' + hex(address))
        count += 1
    def read(_uc, _access, address, size, _value, _data):
        if not all(byte in known for byte in range(address, address + size)):
            raise ValueError('Uncaptured indexed-lookup read ' + hex(address))
    def write(_uc, _access, address, size, _value, _data):
        if not (stack <= address < address + size <= stack + 4096 or output <= address < address + size <= output + 4):
            raise ValueError('Unexpected indexed-lookup mutation ' + hex(address))
        known.update(range(address, address + size))
    uc.hook_add(UC_HOOK_CODE, instruction); uc.hook_add(UC_HOOK_MEM_READ, read); uc.hook_add(UC_HOOK_MEM_WRITE, write)
    uc.reg_write(UC_ARM_REG_R0, int(path[2]['object'], 16))
    uc.reg_write(UC_ARM_REG_R1, index); uc.reg_write(UC_ARM_REG_R2, output)
    uc.reg_write(UC_ARM_REG_SP, stack + 0xff0); uc.reg_write(UC_ARM_REG_LR, end | 1)
    uc.emu_start(struct.unpack_from('<I', table, 0x24)[0], end, count=2000)
    if uc.reg_read(UC_ARM_REG_PC) != end: raise ValueError('Indexed lookup instruction limit')
    if not all(output + i in known for i in range(4)): raise ValueError('Output not written by original method')
    return dict(index=index, success=uc.reg_read(UC_ARM_REG_R0), node=hex(struct.unpack('<I', uc.mem_read(output, 4))[0]), instructions=count)


def main():
    component = (HW / 'native-listtab-code-component.bin').read_bytes()
    source = json.loads((HW / 'native-listtab-code-component.json').read_text())
    if not source['source_equal'] or hashlib.sha256(component).hexdigest() != source['sha256']:
        raise ValueError('Original refresh component identity differs')
    path = json.loads((HW / 'native-setting-node-after-layout-pid2491.json').read_text())['path']
    binding = json.loads((ROOT / 'artifacts/analysis/active-menu-binding-snapshot-probe.json').read_text())
    if binding['fields']['0x1ec'] != path[2]['count'] or path[2]['count'] != 6:
        raise ValueError('Captured page/row count differs')
    geo = json.loads((ROOT / 'artifacts/analysis/active-menu-snapshot-probe.json').read_text())
    by = {int(row['widget'], 16): row for row in geo['geometry']}
    rows = []
    for index in range(1, 7):
        lookup = indexed_lookup(path, index)
        if lookup['success'] != 1 or lookup['node'] != path[2]['children'][index - 1]['object']:
            raise ValueError('Original indexed lookup differs from captured child')
        # Original refresh 0x15b91b2c passes index+1 to node virtual+0x24;
        # 0x15b91c2c passes zero-based row to 0x15b91890, which addresses
        # menu+0x9350+row*0x1118. This is not a host hit-test rule.
        widget = int(geo['menu'], 16) + 0x9350 + (index - 1) * 0x1118
        rows.append(dict(**lookup, widget=hex(widget), geometry=by[widget]))
    invalid = [indexed_lookup(path, index) for index in (0, 7)]
    if any(row['success'] or row['node'] != '0x0' for row in invalid):
        raise ValueError('Invalid index control accepted')
    report = dict(scope=__doc__, page=path[2]['object'], rows=rows, invalid_controls=invalid,
                  static_refresh_source=source,
                  full_refresh_executed=False, hit_testing_proven=False)
    destination = ROOT / 'artifacts/analysis/menu-row-snapshot-probe.json'
    destination.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(destination)
    print('Original indexed lookup: six rows, two rejected invalid controls')


if __name__ == '__main__': main()
