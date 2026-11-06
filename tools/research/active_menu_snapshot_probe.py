"""Replay original active-menu lookup and geometry from a complete native snapshot."""
import json
import struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC, UC_ARM_REG_CPSR
from tools.research.layout_registry_snapshot_probe import run

ROOT = Path(__file__).resolve().parents[2]
HW = ROOT / 'artifacts/hardware'


def geometry(records, widgets, hit_points=None):
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    pages, known, executable = set(), set(), []
    stack, point, output, end = 0x8300000, 0x8310000, 0x8320000, 0x8330000
    count = 0
    cache_writes = []
    it_fixes = []
    cache_widgets = set(widgets)
    for record in records:
        base = int(record['address'], 16); data = bytes.fromhex(record['data'])
        for offset in (0, 0x64):
            if len(data) >= offset + 0xa0 and struct.unpack_from('<I', data, offset + 4)[0] == 0x7063b28 and struct.unpack_from('<I', data, offset + 0x1c)[0] == base + offset:
                cache_widgets.add(base + offset)
    # Original update methods cache world position/scale, parent/clip and flag words.
    cache_addresses = {widget + offset for widget in cache_widgets
                       for offset in (0x44, 0x48, 0x5c, 0x60, 0x64, 0x68, 0x78, 0x7c, 0x80, 0x90, 0x94, 0x98, 0x9c)}
    def supply(address, data, code=False):
        for page in range(address & ~4095, (address + len(data) + 4095) & ~4095, 4096):
            if page not in pages:
                uc.mem_map(page, 4096); pages.add(page)
        uc.mem_write(address, data); known.update(range(address, address + len(data)))
        if code: executable.append((address, address + len(data)))
    for record in records: supply(int(record['address'], 16), bytes.fromhex(record['data']))
    supply(0x6305000, (HW / 'native-widget-geometry-component.bin').read_bytes(), True)
    world = json.loads((HW / 'native-widget-worldpos-contracts.json').read_text())
    for record in world['additional']:
        supply(int(record['address'], 16), bytes.fromhex(record['data']), record['code'])
    if hit_points is not None:
        for record in json.loads((HW / 'native-hit-visibility-contracts.json').read_text()):
            if record['name'] == 'menu_hit_vtable':
                supply(int(record['address'], 16), bytes.fromhex(record['data']))
            elif record['name'] == '_ZN2ux6wgtsys10WidgetBase9sys_isHitERKNS_4core7Vector2E':
                supply(int(record['address'], 16), bytes.fromhex(record['code']), True)
    for address in (stack, point, output, end): uc.mem_map(address, 4096)
    # Explicit Cortex-A5 VFP architectural setup; no function result is supplied.
    uc.reg_write(UC_ARM_REG_C1_C0_2, 0xf << 20)
    uc.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
    initial_cpu = uc.context_save()
    def instruction(_uc, address, size, _data):
        nonlocal count
        if not any(lo <= address < address + size <= hi for lo, hi in executable):
            raise ValueError('Unknown geometry code ' + hex(address))
        # These are source-verified boundaries AFTER complete Thumb IT blocks.
        # Apply the existing interpreter's narrow stale-IT workaround there only.
        if address in (0x631983a, 0x631984c, 0x6319862, 0x631986c):
            cpsr = uc.reg_read(UC_ARM_REG_CPSR); mask = (3 << 25) | (0x3f << 10)
            if cpsr & mask:
                it_fixes.append(dict(address=hex(address), stale_bits=hex(cpsr & mask)))
                uc.reg_write(UC_ARM_REG_CPSR, cpsr & ~mask)
        count += 1
    def read(_uc, _access, address, size, _value, _data):
        if not all(byte in known for byte in range(address, address + size)):
            raise ValueError('Uncaptured geometry bytes ' + hex(address))
    def write(_uc, _access, address, size, value, _data):
        cache = size == 4 and address in cache_addresses and all(byte in known for byte in range(address, address + size))
        if not (stack <= address < address + size <= stack + 4096 or output <= address < address + size <= output + 8 or cache):
            raise ValueError('Geometry requires unverified cache mutation at ' + hex(address))
        if cache: cache_writes.append(dict(address=hex(address), value=hex(value)))
        known.update(range(address, address + size))
    uc.hook_add(UC_HOOK_CODE, instruction); uc.hook_add(UC_HOOK_MEM_READ, read); uc.hook_add(UC_HOOK_MEM_WRITE, write)
    def call(entry, args):
        nonlocal count
        uc.context_restore(initial_cpu)
        known.difference_update(range(stack, stack + 4096)); known.difference_update(range(output, output + 8))
        for register, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2), args): uc.reg_write(register, value)
        uc.reg_write(UC_ARM_REG_SP, stack + 0xff0); uc.reg_write(UC_ARM_REG_LR, end | 1)
        before = count; uc.emu_start(entry | 1, end, count=2000)
        if uc.reg_read(UC_ARM_REG_PC) != end: raise ValueError('Geometry instruction bound')
        return uc.reg_read(UC_ARM_REG_R0), count - before
    report = []
    for widget in widgets:
        row = dict(widget=hex(widget))
        try:
            width, n1 = call(0x6305440, [widget]); height, n2 = call(0x630544e, [widget])
            row['local_size'] = list(struct.unpack('<2f', struct.pack('<2I', width, height)))
            corners = []; instructions = n1 + n2
            for xy in [(0.0, 0.0), tuple(row['local_size'])]:
                raw = struct.pack('<2f', *xy); uc.mem_write(point, raw); known.update(range(point, point + 8))
                _, n = call(0x63052e8, [output, widget, point]); instructions += n
                corners.append(list(struct.unpack('<2f', uc.mem_read(output, 8))))
            row.update(world_corners=corners, instructions=instructions, returned=True)
            if hit_points is not None:
                row['hit_results'] = []
                for xy in hit_points:
                    uc.mem_write(point, struct.pack('<2f', *xy)); known.update(range(point, point + 8))
                    hit, n = call(0x6305080, [widget, point])
                    row['hit_results'].append(dict(point=list(xy), hit=hit, instructions=n))
        except Exception as error:
            row.update(returned=False, boundary=str(error), pc=hex(uc.reg_read(UC_ARM_REG_PC)))
        report.append(row)
    return report, cache_writes, it_fixes


def main():
    capture = json.loads((HW / 'native-layout-snapshot-pid2491.json').read_text())
    if not capture['complete_binary']: raise ValueError('Complete native binary required')
    records = capture['records']; by = {int(r['address'], 16): r for r in records}
    def raw(address, size):
        for record in records:
            base = int(record['address'], 16); data = bytes.fromhex(record['data'])
            if base <= address and address + size <= base + len(data): return data[address - base:address - base + size]
        raise ValueError('Uncaptured tree bytes ' + hex(address))
    def word(address): return struct.unpack('<I', raw(address, 4))[0]
    registry = word(0x7107f34)
    code = json.loads((HW / 'native-widget-layout-registry-contracts.json').read_text())
    alias_addresses = {0x157e584c, 0x159589f8}
    context_records = [{**record, 'code': int(record['address'], 16) in alias_addresses} for record in records]
    context_records += [dict(address=code['singleton']['slot'], data=struct.pack('<I', 0x7107f34).hex()),
                        *json.loads((HW / 'native-layout-lookup-got.json').read_text())]
    lookup = run(dict(root=by[registry], entries=[]), code, 0xaadca2c7, 0xdfdc8ddd,
                 'widget', dict(records=context_records, resource_id=0xa056f604))
    menu = int(lookup['result'], 16)
    if lookup['error'] or word(menu) != 0x15f1f1d0: raise ValueError('Original lookup did not resolve the actual list tab')
    widgets, seen = [], set()
    def walk(widget, depth):
        if depth > 48 or widget in seen or len(seen) >= 1024: raise ValueError('Widget tree cycle/limit')
        seen.add(widget); widgets.append(widget)
        link = word(widget + 0x14) & ~3
        while link:
            child = link - 8
            if word(child + 0x1c) != child: raise ValueError('Widget self-pointer mismatch')
            walk(child, depth + 1); link = word(child + 8)
            if link & 3: raise ValueError('Unexpected sibling flags')
    walk(menu, 0)
    calculated, cache_writes, it_fixes = geometry(records, widgets)
    result = dict(scope='Original active-menu lookup and geometry on complete non-atomic camera snapshot; original cache updates confined to emulator copies; no camera calls or writes',
                  lookup=lookup, menu=hex(menu), widget_count=len(widgets), geometry=calculated,
                  emulator_cache_writes=cache_writes, stale_it_workarounds=it_fixes)
    destination = ROOT / 'artifacts/analysis/active-menu-snapshot-probe.json'
    destination.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(destination); print('widgets', len(widgets), 'geometry returns', sum(row['returned'] for row in result['geometry']))


if __name__ == '__main__': main()
