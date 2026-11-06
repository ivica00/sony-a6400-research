"""Execute native controller selection sync on the actual interaction trace."""
import json
import struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC

ROOT = Path(__file__).resolve().parents[2]
HW = ROOT / 'artifacts/hardware'


def run(state, contracts, operation='sync'):
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    pages, known, code_ranges, writes = set(), set(), [], []
    controller = int(state['object'], 16)
    stack, end = 0x8300000, 0x8310000
    model_addresses = {int(m['object'], 16) for m in state['models']}
    count = 0
    boundary = {}
    def supply(address, data, code=False):
        for page in range(address & ~4095, (address + len(data) + 4095) & ~4095, 4096):
            if page not in pages:
                uc.mem_map(page, 4096)
                pages.add(page)
        uc.mem_write(address, data)
        known.update(range(address, address + len(data)))
        if code:
            code_ranges.append((address, address + len(data)))
    supply(0x16925a00, (HW / 'native-setting-node-code.bin').read_bytes(), True)
    for window in contracts['windows']:
        supply(int(window['address'], 16), bytes.fromhex(window['data']), True)
    for table in contracts['vtables']:
        supply(int(table['address'], 16), bytes.fromhex(table['data']))
    original = bytes.fromhex(state['data'])
    supply(controller, original)
    for model in state['models']:
        supply(int(model['object'], 16), bytes.fromhex(model['data']))
    # The observer read this exact array slot to obtain the next logged node.
    # Supply only that observed edge; no unobserved siblings or empty RAM.
    for model, child in zip(state['models'], state['models'][1:]):
        raw = bytes.fromhex(model['data'])
        array, number = struct.unpack_from('<2I', raw, 4)
        selected = struct.unpack_from('<i', raw, 0x18)[0]
        if not 1 <= selected <= number <= 128:
            raise ValueError('Invalid retained traversal edge')
        supply(array + 4 * (selected - 1), struct.pack('<I', int(child['object'], 16)))
    for address in (stack, end):
        uc.mem_map(address, 4096)
    def instruction(_uc, address, size, _data):
        nonlocal count
        if operation == 'action1' and address == 0x15735328:
            boundary.update(target='ViewBase::getWidget', address=hex(address),
                            controller=hex(uc.reg_read(UC_ARM_REG_R0)),
                            resource_id=hex(uc.reg_read(UC_ARM_REG_R1)))
            uc.emu_stop()
            return
        if not any(lo <= address < address + size <= hi for lo, hi in code_ranges):
            raise ValueError('Unprovided original target ' + hex(address))
        count += 1
    def read(_uc, _access, address, size, _value, _data):
        if not all(byte in known for byte in range(address, address + size)):
            raise ValueError('Unobserved memory read ' + hex(address))
    def write(_uc, _access, address, size, value, _data):
        allowed = (stack <= address < address + size <= stack + 4096 or
                   size == 4 and address in {controller + x for x in (0x150, 0x154, 0x158, 0x168)} or
                   size == 4 and address in {node + 0x18 for node in model_addresses})
        if not allowed:
            raise ValueError('Write outside controller sync contract ' + hex(address))
        known.update(range(address, address + size))
        if not stack <= address < stack + 4096:
            writes.append(dict(address=hex(address), value=hex(value)))
    uc.hook_add(UC_HOOK_CODE, instruction)
    uc.hook_add(UC_HOOK_MEM_READ, read)
    uc.hook_add(UC_HOOK_MEM_WRITE, write)
    uc.reg_write(UC_ARM_REG_R0, controller)
    if operation == 'action1':
        uc.reg_write(UC_ARM_REG_R1, 1)
    uc.reg_write(UC_ARM_REG_SP, stack + 0xff0)
    uc.reg_write(UC_ARM_REG_LR, end | 1)
    entries = {'sync': 0x157ec8f3, 'selected': 0x157edc4b, 'action1': 0x6103ef1}
    uc.emu_start(entries[operation], end, count=2000)
    if boundary:
        return dict(sample=state['sample'], operation=operation, instructions=count,
                    returned=False, boundary=boundary, writes=writes)
    if uc.reg_read(UC_ARM_REG_PC) != end:
        raise ValueError('Original sync did not return')
    fields = {hex(offset): struct.unpack('<i', uc.mem_read(controller + offset, 4))[0]
              for offset in (0x150, 0x154, 0x158)}
    recorded = {hex(offset): struct.unpack_from('<i', original, offset)[0]
                for offset in (0x150, 0x154, 0x158)}
    return dict(sample=state['sample'], instructions=count, fields=fields,
                recorded=recorded, matches_recorded=fields == recorded, writes=writes,
                returned_value=hex(uc.reg_read(UC_ARM_REG_R0)))


def main():
    states = json.loads((HW / 'native-menu-controller-probe-pid2349-decoded.json').read_text())
    contracts = json.loads((HW / 'native-controller-sync-contracts.json').read_text())
    controls = [run(state, contracts) for state in states if state['path_result'] == 0]
    if len(controls) != 13 or not all(control['matches_recorded'] for control in controls):
        raise ValueError('Controller sync disagrees with native trace: ' + repr(controls))
    selected = [run(state, contracts, 'selected') for state in states]
    if any(result['returned_value'] != hex(int(state['models'][3]['object'], 16))
           for state, result in zip(states, selected)):
        raise ValueError('Original selected-node helper disagrees with native path')
    before_open = next(state for state in states if state['sample'] == 209)
    action = run(before_open, contracts, 'action1')
    if not action.get('boundary'):
        raise ValueError('Action probe did not reach the original widget-lookup boundary')
    report = dict(scope='Original ARM on non-atomic interaction records; emulator mutations only; action1 is an explicit caller-supplied control',
                  observed_edges_reconstructed_from_logged_traversal=True, controls=controls,
                  selected_node_controls=selected, action_control=action)
    destination = ROOT / 'artifacts/analysis/controller-sync-snapshot-probe.json'
    destination.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(destination)


if __name__ == '__main__':
    main()
