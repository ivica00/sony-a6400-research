"""Execute original two-level layout hash lookups on retained camera memory."""
import json
import struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC

ROOT = Path(__file__).resolve().parents[2]
HW = ROOT / 'artifacts/hardware'


def run(snapshot, code, container, identifier, level, widget_context=None):
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    pages, known, executable, supplied = set(), set(), [], {}
    stack, key, end = 0x8300000, 0x8310000, 0x8320000
    instructions = 0
    def map_range(address, size):
        for page in range(address & ~4095, (address + size + 4095) & ~4095, 4096):
            if page not in pages:
                uc.mem_map(page, 4096)
                pages.add(page)
    def supply(address, data, is_code=False):
        for offset, value in enumerate(data):
            if address + offset in supplied and supplied[address + offset] != value:
                raise ValueError('Conflicting retained bytes ' + hex(address + offset))
        supplied.update({address + offset: value for offset, value in enumerate(data)})
        map_range(address, len(data))
        uc.mem_write(address, data)
        known.update(range(address, address + len(data)))
        if is_code:
            executable.append((address, address + len(data)))
    for name, window in code.items():
        if name.startswith('0x'):
            supply(int(name, 16), bytes.fromhex(window['code']), True)
    if widget_context:
        supply(0x62dc800, (HW / 'native-layout-lookup-component.bin').read_bytes(), True)
        for record in widget_context['records']:
            supply(int(record['address'], 16), bytes.fromhex(record['data']), record.get('code', False))
    supply(int(snapshot['root']['address'], 16), bytes.fromhex(snapshot['root']['data']))
    for entry in snapshot['entries']:
        supply(int(entry['address'], 16), bytes.fromhex(entry['data']))
        for view in entry['views']:
            supply(int(view['address'], 16), bytes.fromhex(view['data']))
    # Explicit constructed key ABI; native hash/equality read only key+8.
    supply(key + 8, struct.pack('<I', identifier))
    map_range(stack, 4096)
    map_range(end, 4096)
    def instruction(_uc, address, size, _data):
        nonlocal instructions
        if not any(lo <= address < address + size <= hi for lo, hi in executable):
            raise ValueError('Unprovided original lookup target ' + hex(address))
        instructions += 1
    def read(_uc, _access, address, size, _value, _data):
        if not all(byte in known for byte in range(address, address + size)):
            raise ValueError('Unprovided original lookup bytes ' + hex(address))
    def write(_uc, _access, address, size, _value, _data):
        if not (stack <= address < address + size <= stack + 4096 or
                widget_context and address == key and size == 4):
            raise ValueError('Original lookup wrote outside stack')
        known.update(range(address, address + size))
    uc.hook_add(UC_HOOK_CODE, instruction)
    uc.hook_add(UC_HOOK_MEM_READ, read)
    uc.hook_add(UC_HOOK_MEM_WRITE, write)
    uc.reg_write(UC_ARM_REG_R0, container)
    uc.reg_write(UC_ARM_REG_R1, identifier if widget_context else key)
    if widget_context:
        uc.reg_write(UC_ARM_REG_R2, widget_context['resource_id'])
        uc.reg_write(UC_ARM_REG_R3, key)
    uc.reg_write(UC_ARM_REG_SP, stack + 0xff0)
    uc.reg_write(UC_ARM_REG_LR, end | 1)
    entry = 0x62e27de if widget_context else (0x62dea7e if level == 'layout' else 0x62de054)
    uc.emu_start(entry | 1, end, count=2000)
    if uc.reg_read(UC_ARM_REG_PC) != end:
        raise ValueError('Original lookup did not return')
    result = dict(level=level, container=hex(container), identifier=hex(identifier),
                  result=hex(uc.reg_read(UC_ARM_REG_R0)), instructions=instructions)
    if widget_context:
        if not all(key + i in known for i in range(4)):
            raise ValueError('Original lookup did not write error output')
        result['error'] = struct.unpack('<I', uc.mem_read(key, 4))[0]
    return result


def main():
    snapshot = json.loads((HW / 'native-layout-registry-usb.json').read_text())
    code = json.loads((HW / 'native-widget-layout-registry-contracts.json').read_text())
    root = int(snapshot['root']['address'], 16)
    controls = []
    for entry in snapshot['entries']:
        address = int(entry['address'], 16)
        identifier = struct.unpack_from('<I', bytes.fromhex(entry['data']), 8)[0]
        result = run(snapshot, code, root, identifier, 'layout')
        if result['result'] != hex(address):
            raise ValueError('Layout lookup disagrees with native registry')
        controls.append(result)
        for view in entry['views']:
            view_id = struct.unpack_from('<I', bytes.fromhex(view['data']), 8)[0]
            result = run(snapshot, code, address + 0x14, view_id, 'view')
            if result['result'] != view['address']:
                raise ValueError('View lookup disagrees with native registry')
            controls.append(result)
    missing = run(snapshot, code, root, 0xffffffff, 'layout')
    if missing['result'] != '0x0':
        raise ValueError('Missing layout returned a candidate')
    controls.append(missing)
    menu_entry = next(entry for entry in snapshot['entries']
                      if struct.unpack_from('<I', bytes.fromhex(entry['data']), 8)[0] == 0xaadca2c7)
    menu_view = run(snapshot, code, int(menu_entry['address'], 16) + 0x14, 0xdfdc8ddd, 'view')
    if menu_view['result'] != '0x0':
        raise ValueError('USB snapshot unexpectedly contains the menu view')
    controls.append(menu_view)
    widgets = json.loads((HW / 'native-layout-usb-widget-map.json').read_text())
    alias = json.loads((HW / 'native-layout-widget-map-alias-contracts.json').read_text())
    view_contract = json.loads((HW / 'native-layout-view-widget-contract.json').read_text())
    view_address = alias['view']['address']
    owner = next(entry for entry in snapshot['entries'] if any(v['address'] == view_address for v in entry['views']))
    view = next(v for v in owner['views'] if v['address'] == view_address)
    singleton = code['singleton']
    records = [*widgets['records'], alias['view'],
               {'address': alias['resource']['address'], 'data': alias['resource']['data']},
               {'address': alias['resource']['vtable'], 'data': alias['resource']['table']},
               {'address': alias['resource']['method'], 'data': alias['resource']['code'], 'code': True},
               {'address': view_contract['vtable'], 'data': view_contract['table']},
               {'address': singleton['slot'], 'data': struct.pack('<I', int(singleton['storage'], 16)).hex()},
               {'address': singleton['storage'], 'data': struct.pack('<I', root).hex()},
               *json.loads((HW / 'native-layout-lookup-got.json').read_text())]
    widget = widgets['widgets'][0]
    context = dict(records=records, resource_id=int(widget['resource_id'], 16))
    native_widget = run(snapshot, code,
                        struct.unpack_from('<I', bytes.fromhex(owner['data']), 8)[0],
                        struct.unpack_from('<I', bytes.fromhex(view['data']), 8)[0],
                        'widget', context)
    if native_widget['result'] != widget['widget'] or native_widget['error'] != 0:
        raise ValueError('Original complete USB widget lookup disagrees with camera map')
    report = dict(scope='Original ARM hash lookups on non-atomic USB registry; constructed search-key ABI only; no camera calls',
                  controls=controls, native_usb_widget_lookup=native_widget,
                  active_menu_lookup_completed=False)
    destination = ROOT / 'artifacts/analysis/layout-registry-snapshot-probe.json'
    destination.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(destination)


if __name__ == '__main__':
    main()
