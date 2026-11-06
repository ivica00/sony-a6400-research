"""Run original selection code on retained camera state, never on the camera."""
import hashlib
import json
import struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC

ROOT = Path(__file__).resolve().parents[2]
HARDWARE = ROOT / 'artifacts/hardware'


def run(method, argument=None, snapshot=None):
    if snapshot is None:
        snapshot = json.loads((HARDWARE / 'native-setting-node-selected-path-usb.json').read_text())['path'][0]
    table = bytes.fromhex(json.loads((HARDWARE / 'native-setting-node-hierarchy-usb.json').read_text())['vtable'])
    code = (HARDWARE / 'native-setting-node-code.bin').read_bytes()
    contracts = json.loads((HARDWARE / 'native-setting-node-contracts.json').read_text())
    entry = next(int(value['address'], 16) for name, value in contracts.items() if method in name)
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    mapped, known = set(), set()
    reads, writes = [], []
    start, stack, end, output = 0x16925a00, 0x8300000, 0x8310000, 0x8320000
    root = int(snapshot['object'], 16)
    nodes = [snapshot, *snapshot['children']]
    node_addresses = {int(node['object'], 16) for node in nodes}
    def map_range(address, size):
        for page in range(address & ~4095, (address + size + 4095) & ~4095, 4096):
            if page not in mapped:
                uc.mem_map(page, 4096)
                mapped.add(page)
    def supply(address, data):
        map_range(address, len(data))
        uc.mem_write(address, data)
        known.update(range(address, address + len(data)))
    supply(start, code)
    supply(0x16c183e8, table)
    for node in nodes:
        supply(int(node['object'], 16), bytes.fromhex(node['data']))
    supply(int(snapshot['array_address'], 16), bytes.fromhex(snapshot['array']))
    for address in (stack, end, output):
        map_range(address, 4096)
    def instruction(_uc, address, _size, _data):
        if not start <= address < start + len(code):
            raise ValueError('Original code reached uncaptured target ' + hex(address))
    def read(_uc, _access, address, size, _value, _data):
        if not all(byte in known for byte in range(address, address + size)):
            raise ValueError('Original code read uncaptured memory ' + hex(address))
        reads.append(dict(address=hex(address), size=size))
    def write(_uc, _access, address, size, value, _data):
        allowed = (stack <= address < address + size <= stack + 4096 or
                   output <= address < address + size <= output + 4 or
                   size == 4 and any(address == node + offset for node in node_addresses for offset in (0x18, 0x24)))
        if not allowed:
            raise ValueError('Original code wrote outside selection/stack/output contract ' + hex(address))
        known.update(range(address, address + size))
        if not stack <= address < stack + 4096:
            writes.append(dict(address=hex(address), size=size, value=hex(value)))
    uc.hook_add(UC_HOOK_CODE, instruction)
    uc.hook_add(UC_HOOK_MEM_READ, read)
    uc.hook_add(UC_HOOK_MEM_WRITE, write)
    uc.reg_write(UC_ARM_REG_R0, root)
    uc.reg_write(UC_ARM_REG_R1, output if argument is None else argument)
    uc.reg_write(UC_ARM_REG_SP, stack + 0xff0)
    uc.reg_write(UC_ARM_REG_LR, end | 1)
    uc.emu_start(entry | 1, end, count=2000)
    if uc.reg_read(UC_ARM_REG_PC) != end:
        raise ValueError('Instruction bound reached without return')
    result = dict(method=method, argument=argument, status=uc.reg_read(UC_ARM_REG_R0),
                  selected_before=snapshot['selected'],
                  selected_after=struct.unpack('<i', uc.mem_read(root + 0x18, 4))[0],
                  output=hex(struct.unpack('<I', uc.mem_read(output, 4))[0]) if argument is None else None,
                  writes=writes, reads=reads)
    return result


def main():
    controls = [run('20getIndexSelectedItem'), run('15getSelectedItem'),
                run('22setItemSelectedByIndex', 4), run('22setItemSelectedByIndex', 5),
                run('22setItemSelectedByIndex', 0), run('22setItemSelectedByIndex', 7)]
    if controls[0]['output'] != '0x5' or controls[1]['output'] != '0x160efcc4':
        raise ValueError('Original getters disagree with captured selection')
    if controls[2]['status'] != 1 or controls[2]['selected_after'] != 4:
        raise ValueError('Original selection did not update the captured copy')
    if controls[3]['status'] != 1 or controls[3]['writes']:
        raise ValueError('Selecting the existing item was not a no-op')
    if any(c['status'] != 0 or c['selected_after'] != 5 or c['writes'] for c in controls[4:]):
        raise ValueError('Invalid selection changed captured state')
    report = dict(scope='Original ARM code on a retained non-atomic USB camera snapshot; all mutations confined to emulator copies',
                  code_sha256=hashlib.sha256((HARDWARE / 'native-setting-node-code.bin').read_bytes()).hexdigest(),
                  controls=controls)
    destination = ROOT / 'artifacts/analysis/setting-node-snapshot-probe.json'
    destination.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(destination)


if __name__ == '__main__':
    main()
