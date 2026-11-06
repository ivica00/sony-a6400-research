"""Execute original list-tab model binding on retained camera data."""
import json
import argparse
import struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_INVALID
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC

ROOT = Path(__file__).resolve().parents[2]
HW = ROOT / 'artifacts/hardware'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--active-layout', action='store_true', help='Check the complete E0106 menu against the separately captured retained USB model')
    args = parser.parse_args()
    if args.active_layout:
        path = json.loads((HW / 'native-setting-node-after-layout-pid2491.json').read_text())['path']
        leaf = {}
    else:
        path = json.loads((HW / 'native-setting-node-selected-path-usb.json').read_text())['path']
        leaf = json.loads((HW / 'native-setting-node-selected-leaf-children.json').read_text())
    binding = json.loads((HW / 'native-menu-binding-contracts.json').read_text())
    if args.active_layout:
        capture = json.loads((HW / 'native-layout-snapshot-pid2491.json').read_text())
        if not capture['complete_binary']:
            raise ValueError('Complete layout capture required')
        record = next(r for r in capture['records'] if int(r['address'], 16) == 0x10f61008)
        state = dict(header='E0106 MENU capture plus later retained USB model; non-atomic',
                     menus=[dict(object=record['address'], offset='0x0', data=record['data'])])
    else:
        states = json.loads((HW / 'native-menu-state-probe-pid2176-decoded.json').read_text())
        state = next(s for s in states if 'sample=842 ' in s['header'])
    menu = int(state['menus'][0]['object'], 16)
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    pages, known, executable, model_addresses = set(), {}, [], set()
    writes, instructions = [], []
    stack, end = 0x8300000, 0x8310000
    def map_range(address, size):
        for page in range(address & ~4095, (address + size + 4095) & ~4095, 4096):
            if page not in pages:
                uc.mem_map(page, 4096)
                pages.add(page)
    def supply(address, data, code=False):
        for offset, value in enumerate(data):
            if address + offset in known and known[address + offset] != value:
                raise ValueError('Conflicting retained snapshots at ' + hex(address + offset))
        map_range(address, len(data))
        uc.mem_write(address, data)
        known.update({address + offset: value for offset, value in enumerate(data)})
        if code:
            executable.append((address, address + len(data)))
    supply(0x16925a00, (HW / 'native-setting-node-code.bin').read_bytes(), True)
    for window in binding['windows']:
        supply(int(window['address'], 16), bytes.fromhex(window['data']), True)
    for table in binding['vtables']:
        supply(int(table['address'], 16), bytes.fromhex(table['data']))
    for record in [*path, leaf]:
        if 'object' in record:
            address = int(record['object'], 16)
            supply(address, bytes.fromhex(record['data']))
            model_addresses.add(address)
        if 'array' in record:
            supply(int(record['array_address'], 16), bytes.fromhex(record['array']))
        for child in record.get('children', []):
            address = int(child['object'], 16)
            supply(address, bytes.fromhex(child['data']))
            model_addresses.add(address)
    for record in state['menus']:
        supply(menu + int(record['offset'], 16), bytes.fromhex(record['data']))
    map_range(stack, 4096)
    map_range(end, 4096)
    def instruction(_uc, address, size, _data):
        if not any(lo <= address < address + size <= hi for lo, hi in executable):
            raise ValueError('Unprovided original execution target ' + hex(address))
        instructions.append(hex(address))
    def read(_uc, _access, address, size, _value, _data):
        if not all(byte in known for byte in range(address, address + size)):
            raise ValueError('Unprovided snapshot read at ' + hex(address))
    def write(_uc, _access, address, size, value, _data):
        allowed = (stack <= address < address + size <= stack + 4096 or
                   size == 4 and address in {menu + x for x in range(0x1e4, 0x200, 4)} or
                   size == 4 and address in {node + 0x18 for node in model_addresses})
        if not allowed:
            raise ValueError('Write outside binding contract at ' + hex(address))
        known.update({address + offset: (value >> (8 * offset)) & 255 for offset in range(size)})
        if not stack <= address < stack + 4096:
            writes.append(dict(address=hex(address), size=size, value=hex(value)))
    uc.hook_add(UC_HOOK_CODE, instruction)
    uc.hook_add(UC_HOOK_MEM_READ, read)
    uc.hook_add(UC_HOOK_MEM_WRITE, write)
    def invalid(_uc, _access, address, size, _value, _data):
        raise ValueError('Unmapped snapshot access at ' + hex(address) + ' PC=' + hex(uc.reg_read(UC_ARM_REG_PC)))
    uc.hook_add(UC_HOOK_MEM_INVALID, invalid)
    uc.reg_write(UC_ARM_REG_R0, menu)
    uc.reg_write(UC_ARM_REG_SP, stack + 0xff0)
    uc.reg_write(UC_ARM_REG_LR, end | 1)
    try:
        uc.emu_start((0x155e6000 + 0x5ab430) | 1, end, count=10000)
    except Exception as error:
        raise ValueError('Binding stopped at PC=' + hex(uc.reg_read(UC_ARM_REG_PC)) +
                         ' recent=' + repr(instructions[-8:])) from error
    if uc.reg_read(UC_ARM_REG_PC) != end:
        raise ValueError('Binding did not return within instruction bound')
    fields = {hex(offset): struct.unpack('<i', uc.mem_read(menu + offset, 4))[0]
              for offset in range(0x1e4, 0x200, 4)}
    expected = {'0x1e4': 6, '0x1e8': 7, '0x1ec': 6, '0x1f0': 5,
                '0x1f4': 1, '0x1f8': 0, '0x1fc': 0}
    if args.active_layout:
        raw = bytes.fromhex(state['menus'][0]['data'])
        expected = {hex(offset): struct.unpack_from('<i', raw, offset)[0]
                    for offset in range(0x1e4, 0x200, 4)}
    if fields != expected:
        raise ValueError('Original binding fields differ: ' + repr(fields))
    report = dict(scope='Original list-tab binding on merged retained non-atomic camera snapshots; emulator writes only',
                  menu=hex(menu), provider=path[0]['object'], fields=fields,
                  instructions=len(instructions), writes=writes, trace=instructions,
                  source_state=state['header'])
    destination = ROOT / 'artifacts/analysis' / ('active-menu-binding-snapshot-probe.json' if args.active_layout else 'menu-binding-snapshot-probe.json')
    destination.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(destination)


if __name__ == '__main__':
    main()
