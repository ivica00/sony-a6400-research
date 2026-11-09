"""Attempt original ListTab activation on captured state; stop at missing evidence.

The caller explicitly supplies the captured selected node. This is offline
execution, not proof of the originating physical input or application thread.
"""
import json
import hashlib
import argparse
import re
import struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_INVALID
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R10, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC, UC_ARM_REG_C13_C0_3, UC_ARM_REG_CPSR
from tools.research.active_menu_snapshot_probe import ROOT, HW
from tools.research.prepare_active_menu_control import model_path, capture_tag


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--main-thread-control', action='store_true')
    parser.add_argument('--resource-snapshot', action='store_true', help='Use explicitly refreshed E0111 coherent heap subset; remaining input is still non-atomic')
    parser.add_argument('--menu-resource-header', action='store_true', help='Explicit E0113 control using the actual active-MENU resource header')
    parser.add_argument('--active-state', type=Path, help='Actual coupled V4 capture; uncovered dependencies are still separately qualified')
    parser.add_argument('--native-row-entry', action='store_true', help='Explicit offline direction1 navigation, then original model binding; no forced focus byte')
    parser.add_argument('--refresh-only', action='store_true', help='Separate original ListTab refresh control; never invokes activation')
    parser.add_argument('--auxiliary-usb-control', action='store_true', help='Explicit separate exploratory USB auxiliary-object input; not a coherent MENU activation claim')
    parser.add_argument('--packed-index-usb-control', action='store_true', help='Explicit exploratory later-USB packed indices; no coherent MENU claim')
    args = parser.parse_args()
    if args.refresh_only and (not args.active_state or args.auxiliary_usb_control or args.packed_index_usb_control):
        parser.error('Refresh control requires active capture without exploratory USB inputs')
    if args.packed_index_usb_control and (not args.active_state or args.auxiliary_usb_control): parser.error('Packed-index control requires active state and is separate from auxiliary-object control')
    if args.native_row_entry and not args.active_state:
        parser.error('Native row-entry control requires an actual active capture')
    if args.active_state and (not args.main_thread_control or args.resource_snapshot or args.menu_resource_header):
        parser.error('Use active-state with main-thread-control, separately from older partial controls')
    if args.menu_resource_header and not (args.main_thread_control and args.resource_snapshot):
        parser.error('The active resource-header control requires both existing explicit controls')
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    pages, known, executable = set(), {}, []
    writes, trace = [], []
    boundary = {}
    scoped_writes = set()
    accounting = []
    allocator_mutexes = set()
    bitmap_mutexes = set()
    bitmap_conditions = set()
    bitmap_writes = set()
    bitmap_initial = {}
    bitmap_lock_calls = {}
    allocation_mutexes = set()
    fastbin_pops = []
    fastbin_pop_writes = set()
    reference_release_writes = set()
    reference_acquire_writes = set()
    acquisition_checks = []
    allocated_ranges = []
    resource_lists = []
    pointer_reads, reference_checks = {}, []
    call_contract_observations = []
    menu, stack, end = 0x10f61008, 0x8300000, 0x8310000
    snapshot = json.loads((args.active_state or HW / 'native-layout-snapshot-pid2491.json').read_text())
    if not snapshot['complete_binary']: raise ValueError('Complete menu required')
    if args.active_state:
        menus = [r for r in snapshot['records'] if r['size'] == 0x186bc and bytes.fromhex(r['data'])[:4] == struct.pack('<I', 0x15f1f1d0)]
        if len(menus) != 1: raise ValueError('Ambiguous captured menu')
        menu = int(menus[0]['address'], 16)
        path = model_path(snapshot, menu)
        tag = capture_tag(args.active_state.stem.rsplit('-', 1)[-1])
        manifest = json.loads((HW / f'native-active-menu-{tag}-control.json').read_text())
        if manifest['source_capture_sha256'] != snapshot['sha256']: raise ValueError('Prepared input belongs to a different capture')
    else:
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
    extra = HW / (f'native-menu-activation-dependencies-{tag}.json' if args.active_state else 'native-menu-activation-dependencies-e0113.json' if args.menu_resource_header else 'native-menu-activation-dependencies-e0111.json' if args.resource_snapshot else 'native-menu-activation-dependencies.json')
    if extra.exists():
        for record in json.loads(extra.read_text()):
            supply(int(record['address'], 16), bytes.fromhex(record['data']), record['code'])
            for mutation in record.get('original_cache_writes', []) + record.get('original_scoped_writes', []):
                scoped_writes.add((int(mutation['address'], 16), int(mutation['pc'], 16), mutation.get('size', 4)))
    if args.refresh_only:
        refresh_extra = HW / f'native-menu-refresh-dependencies-{tag}.json'
        if refresh_extra.exists():
            for record in json.loads(refresh_extra.read_text()):
                if not record.get('source_equal') or not record.get('immutable'):
                    raise ValueError('Refresh additions must be source-equal immutable bytes')
                supply(int(record['address'], 16), bytes.fromhex(record['data']), record['code'])
        table_path = HW / 'native-refresh-method-table-e0129.json'
        if table_path.exists():
            record = json.loads(table_path.read_text())
            data = bytes.fromhex(record['data'])
            if (record['address'] != '0x70546e8' or len(data) != 64 or
                    not record.get('relocation_verified') or
                    hashlib.sha256(data).hexdigest() != record['sha256']):
                raise ValueError('Unexpected refresh table provenance')
            supply(0x70546e8, data)
        icon_path = HW / 'native-refresh-icon-import-e0130.json'
        if icon_path.exists():
            icon = json.loads(icon_path.read_text())
            if icon.get('import_name') != '_ZN8GEN_Icon8setImageEjb' or not icon.get('relocation_verified'):
                raise ValueError('Unexpected refresh import provenance')
            for record in icon['records']:
                supply(int(record['address'], 16), bytes.fromhex(record['data']), record['code'])
    auxiliary_sources = []
    if args.auxiliary_usb_control:
        for name in ('native-auxiliary-contract-usb-e0121.json', 'native-image-handle-accessor-code-e0121.json', 'native-image-handle-reference-code-e0121.json', 'native-libobj-got-usb-e0121.json', 'native-image-callback-usb-e0121.json'):
            auxiliary_sources.append(dict(path=str(HW/name), sha256=hashlib.sha256((HW/name).read_bytes()).hexdigest()))
        if not args.active_state: parser.error('Auxiliary USB control requires explicit active state')
        auxiliary = json.loads((HW / 'native-auxiliary-contract-usb-e0121.json').read_text())
        region = auxiliary['records'][0]
        # Only manager and its embedded accessor objects, excluding neighboring heap.
        supply(0x69ed8, bytes.fromhex(region['data'])[8:0x78])
        methods = json.loads((HW / 'native-image-handle-accessor-code-e0121.json').read_text())
        supply(int(methods['table_address'], 16), bytes.fromhex(methods['table']))
        supply(int(methods['function'], 16), bytes.fromhex(methods['code']), True)
        callbacks = json.loads((HW / 'native-image-callback-usb-e0121.json').read_text())
        if struct.unpack('<I', bytes.fromhex(callbacks['records'][0]['data']))[0] != int(callbacks['records'][1]['address'],16): raise ValueError('Callback pointer changed')
        for row in callbacks['records']: supply(int(row['address'],16), bytes.fromhex(row['data']))
        got = json.loads((HW / 'native-libobj-got-usb-e0121.json').read_text())
        for row in got['records']: supply(int(row['address'], 16), bytes.fromhex(row['data']))
        target = json.loads((HW / 'native-image-handle-reference-code-e0121.json').read_text())
        supply(int(target['address'], 16), bytes.fromhex(target['data']), True)
    if args.packed_index_usb_control:
        index_path = HW/'native-packed-resource-indices-usb-e0123.json'
        index_capture = json.loads(index_path.read_text())
        if not index_capture['complete_binary']: raise ValueError('Complete explicit index input required')
        auxiliary_sources.append(dict(path=str(index_path), sha256=hashlib.sha256(index_path.read_bytes()).hexdigest()))
        for row in index_capture['records']: supply(int(row['address'],16),bytes.fromhex(row['data']))
    for address in (stack, end): uc.mem_map(address, 4096)
    uc.reg_write(UC_ARM_REG_C1_C0_2, 0xf << 20); uc.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
    if args.main_thread_control:
        if args.active_state:
            def captured(address, size):
                if not all(address + i in known for i in range(size)): raise ValueError('Uncaptured active TLS bytes')
                return bytes(known[address + i] for i in range(size))
            log = args.active_state.with_suffix('.log').read_text()
            match = re.search(r'MAIN_TLS value=([0-9a-f]{8}) allocator=([0-9a-f]{8})', log)
            if not match: raise ValueError('Captured main TLS missing')
            tls = int(match[1], 16); address = tls - 0x4c0 + 0x60
            data = captured(address, 16)
        else:
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
        if address in (0x64c33b8, 0x64c33bc, 0x64c33c6, 0x64c33cc, 0x64c0518, 0x64bcc04, 0x6316b5e):
            call_contract_observations.append(dict(pc=hex(address), cpsr=hex(uc.reg_read(UC_ARM_REG_CPSR)),
                registers=[hex(uc.reg_read(reg)) for reg in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R4, UC_ARM_REG_R5)]))
        if args.menu_resource_header and address == 0x64bbde4 and reference_checks and reference_checks[-1].get('matches_original_decrement'):
            boundary.update(kind='control_complete', name='actual_menu_header_reference_release',
                            original_return=hex(uc.reg_read(UC_ARM_REG_R0)),
                            scope='Reference-release primitive only; cache ownership from other phases is not a valid full activation input')
            uc.emu_stop()
            return
        if address == 0x63916bc:
            bitmap = uc.reg_read(UC_ARM_REG_R0)
            if not all(bitmap + i in known for i in range(0x80)) or struct.unpack('<I',uc.mem_read(bitmap,4))[0] != 0x7066cf0:
                raise ValueError('Original bitmap lock lacks captured BitmapImpl')
            if bitmap not in bitmap_initial: bitmap_initial[bitmap] = bytes(uc.mem_read(bitmap,0x80))
            bitmap_lock_calls[bitmap] = bitmap_lock_calls.get(bitmap,0) + 1
            bitmap_mutexes.add(bitmap + 0x24)
            bitmap_conditions.add(bitmap + 0x40)
            bitmap_writes.update({(bitmap + 0x2c,0x407fbea,4), (bitmap + 0x34,0x407fbee,4),
                                  (bitmap + 0x18,0x639173a,4), (bitmap + 0x18,0x639106c,4), (bitmap + 0x2c,0x4080d20,4), (bitmap + 0x34,0x4080d50,4)})
        if address == 0x431c9b4:
            freeing = uc.reg_read(UC_ARM_REG_R5)
            allocated_ranges[:] = [(lo, hi) for lo, hi in allocated_ranges if lo != freeing]
        if address == 0x431c4dc and fastbin_pops:
            result = uc.reg_read(UC_ARM_REG_R0)
            event = fastbin_pops[-1]
            requested = uc.reg_read(UC_ARM_REG_R8)
            chunk = int(event['chunk'], 16)
            # Original glibc fastbin chunk lends the next chunk's prev_size
            # word to the allocation: usable size is chunk size minus 4.
            if result != chunk + 8 or not 0 < requested <= event['size'] - 4:
                raise ValueError('Original malloc result/size differs from verified fastbin pop')
            if not all(result + i in known for i in range(requested)):
                raise ValueError('Original allocation lacks captured payload bytes')
            allocated_ranges.append((result, result + requested))
            event.update(returned=hex(result), requested=requested)
        if address == 0x431a320:
            arena = uc.reg_read(UC_ARM_REG_R7)
            slot = uc.reg_read(UC_ARM_REG_R3)
            chunk = uc.reg_read(UC_ARM_REG_R10)
            if arena not in allocation_mutexes or slot not in range(arena + 8, arena + 48, 4):
                raise ValueError('Unverified original fastbin allocation slot')
            def word(at):
                if not all(at + i in known for i in range(4)): raise ValueError('Uncaptured fastbin word')
                return struct.unpack('<I', uc.mem_read(at, 4))[0]
            size = word(chunk + 4) & ~7
            if word(slot) != chunk or size != (slot - arena) * 2 or word(chunk + 8) != uc.reg_read(UC_ARM_REG_R0):
                raise ValueError('Original fastbin pop differs from captured chain')
            fastbin_pop_writes.add((slot, address, 4))
            fastbin_pops.append(dict(arena=hex(arena), slot=hex(slot), chunk=hex(chunk), size=size,
                                     next=hex(word(chunk + 8))))
        if address == 0x431c4b6 and args.active_state:
            # Original malloc loaded this arena from captured main TLS+0x34.
            arena = uc.reg_read(UC_ARM_REG_R6)
            captured_arena = struct.unpack('<I', captured(tls + 0x34, 4))[0]
            if arena != captured_arena or not all(arena + i in known for i in range(4)):
                raise ValueError('Allocation arena does not match actual captured TLS')
            allocation_mutexes.add(arena)
        if address == 0x431c9ca:
            # Original free derives the arena from the chunk's 1 MiB heap
            # header. Admit only its captured mutex, at the two original CAS
            # call sites; never grant general allocator/heap writes.
            chunk = uc.reg_read(UC_ARM_REG_R5)
            if not all(chunk + 4 + i in known for i in range(4)): raise ValueError('Uncaptured free chunk header')
            flags = struct.unpack('<I', uc.mem_read(chunk + 4, 4))[0]
            if flags & 4:
                header = chunk & ~0xfffff
                if not all(header + i in known for i in range(4)): raise ValueError('Uncaptured nonmain heap header')
                arena = struct.unpack('<I', uc.mem_read(header, 4))[0]
            else:
                # Original free's main-arena branch at431ca4a resolves this
                # libc BSS object, captured by V5 and later observers.
                literal = 0x431ca7c
                if not all(literal + i in known for i in range(4)): raise ValueError('Uncaptured main-arena relocation literal')
                arena = (struct.unpack('<I', uc.mem_read(literal,4))[0] + 0x431ca50) & 0xffffffff
            if arena != uc.reg_read(UC_ARM_REG_R6) or not all(arena + i in known for i in range(4)):
                raise ValueError('Unverified original free arena mutex')
            allocator_mutexes.add(arena)
        if address == 0x64bdfd8:
            resource = uc.reg_read(UC_ARM_REG_R0)
            if not all(resource + i in known for i in range(0x10)): raise ValueError('Uncaptured acquired resource')
            owner = struct.unpack('<I',uc.mem_read(resource+4,4))[0]
            count = struct.unpack('<H',uc.mem_read(resource+0xc,2))[0]
            if owner != 0x6c880 or count == 0xffff: raise ValueError('Unverified acquisition owner/count')
            reference_acquire_writes.add((resource+0xc,0x64bdfe0,2))
            acquisition_checks.append(dict(resource=hex(resource),before=count))
        elif address == 0x64bdfe2 and acquisition_checks:
            event = acquisition_checks[-1]
            event['after'] = struct.unpack('<H',uc.mem_read(int(event['resource'],16)+0xc,2))[0]
            if event['after'] != event['before']+1: raise ValueError('Original acquisition arithmetic differs')
        if address == 0x64be068:
            resource = uc.reg_read(UC_ARM_REG_R0)
            if all(resource + 0xc + i in known for i in range(2)):
                count = struct.unpack('<H', uc.mem_read(resource + 0xc, 2))[0]
                reference_checks.append(dict(resource=hex(resource), captured_count=count,
                                             pointer_sources=pointer_reads.get(resource, []),
                                             payload_pointer_sources=pointer_reads.get(resource + 0x10, [])))
                if count > 0:
                    reference_release_writes.add((resource + 0xc, 0x64be08c, 2))
                if count == 0:
                    boundary.update(kind='invariant', name='release_requires_live_reference',
                                    resource=hex(resource), address=hex(resource + 0xc), count=count)
                    raise ValueError('Original release diagnostic: zero reference count; refusing to admit underflow')
        elif address == 0x64be094 and reference_checks:
            event = reference_checks[-1]
            value = struct.unpack('<H', uc.mem_read(int(event['resource'], 16) + 0xc, 2))[0]
            event.update(after_original_decrement=value, matches_original_decrement=value == event['captured_count'] - 1)
            if not event['matches_original_decrement']:
                raise ValueError('Original reference decrement disagrees with captured input')
        if address == 0x64bb4e6:
            query = uc.reg_read(UC_ARM_REG_R1)
            if not all(query + i in known for i in range(4)):
                raise ValueError('Uncaptured original list query')
            resource_lists.append(dict(root=hex(uc.reg_read(UC_ARM_REG_R0)),
                                       requested_payload=hex(struct.unpack('<I', uc.mem_read(query, 4))[0])))
        # Observe the original virtual result and subsequent stores. These
        # checks never alter execution, registers, fields or return values.
        if address == 0x64c2f9e:
            manager = uc.reg_read(UC_ARM_REG_R5)
            if not all(manager + i in known for i in range(0x18, 0x20)):
                raise ValueError('Uncaptured resource accounting fields')
            current, peak = struct.unpack('<2I', uc.mem_read(manager + 0x18, 8))
            accounting.append(dict(manager=hex(manager), before_current=current, before_peak=peak,
                                   original_virtual_result=uc.reg_read(UC_ARM_REG_R0)))
        elif address == 0x64c2fae and accounting:
            event = accounting[-1]
            manager = int(event['manager'], 16)
            current, peak = struct.unpack('<2I', uc.mem_read(manager + 0x18, 8))
            expected = (event['before_current'] + event['original_virtual_result']) & 0xffffffff
            event.update(after_current=current, after_peak=peak,
                         matches_original_arithmetic=current == expected and peak == max(expected, event['before_peak']))
            if not event['matches_original_arithmetic']:
                raise ValueError('Original accounting stores disagree with captured operands')
    def read(_uc, _access, address, size, _value, _data):
        if not all(byte in known for byte in range(address, address + size)):
            boundary.update(kind='data', address=hex(address), size=size)
            raise ValueError('Uncaptured data ' + hex(address) + ' size=' + str(size))
        if size == 4:
            value = struct.unpack('<I', uc.mem_read(address, 4))[0]
            if 0x14000 <= value < 0x5f000000:
                history = pointer_reads.setdefault(value, [])
                history.append(dict(address=hex(address), pc=hex(uc.reg_read(UC_ARM_REG_PC))))
                if len(history) > 12: del history[0]
    def write(_uc, _access, address, size, value, _data):
        allowed = (any(lo <= address < address + size <= hi for lo, hi in allocated_ranges) and
                   all(address + i in known for i in range(size)) or
                   stack <= address < address + size <= stack + 4096 or
                   menu <= address < address + size <= menu + 0x186bc and all(byte in known for byte in range(address, address + size)) or
                   (size == 4 and uc.reg_read(UC_ARM_REG_PC) in (0x64c82a6, 0x64c82a8, 0x64c8460, 0x64c8462) and
                    any(uc.reg_read(UC_ARM_REG_R4) == lo for lo, hi in allocated_ranges) and
                    all(address + i in known for i in range(4))) or
                   (address, uc.reg_read(UC_ARM_REG_PC), size) in bitmap_writes or
                   (address in bitmap_conditions and size == 4 and uc.reg_read(UC_ARM_REG_PC) == 0xffff0fcc and
                    uc.reg_read(UC_ARM_REG_LR) in (0x408224d,0x40822e7)) or
                   (address in bitmap_mutexes and size == 4 and uc.reg_read(UC_ARM_REG_PC) == 0xffff0fcc and
                    uc.reg_read(UC_ARM_REG_LR) in (0x407fbdd,0x4080d3d)) or
                   (address in allocation_mutexes and size == 4 and uc.reg_read(UC_ARM_REG_PC) == 0xffff0fcc and
                    uc.reg_read(UC_ARM_REG_LR) in (0x431c4cd, 0x431c4fd)) or
                   (address in allocator_mutexes and size == 4 and uc.reg_read(UC_ARM_REG_PC) == 0xffff0fcc and
                    uc.reg_read(UC_ARM_REG_LR) in (0x431c9e3, 0x431ca0d)) or
                   (size == 4 and uc.reg_read(UC_ARM_REG_R5) in allocator_mutexes and
                    all(address + i in known for i in range(4)) and
                    ((uc.reg_read(UC_ARM_REG_PC) == 0x4319c16 and address == uc.reg_read(UC_ARM_REG_R5) + 4) or
                     (uc.reg_read(UC_ARM_REG_PC) == 0x4319c1c and address == uc.reg_read(UC_ARM_REG_R4) + 8) or
                     (uc.reg_read(UC_ARM_REG_PC) == 0x4319c1e and address == uc.reg_read(UC_ARM_REG_R5) + 4 * uc.reg_read(UC_ARM_REG_R6)))) or
                   (address, uc.reg_read(UC_ARM_REG_PC), size) in reference_acquire_writes or
                   (address, uc.reg_read(UC_ARM_REG_PC), size) in reference_release_writes or
                   (address, uc.reg_read(UC_ARM_REG_PC), size) in fastbin_pop_writes or
                   (address, uc.reg_read(UC_ARM_REG_PC), size) in scoped_writes and all(byte in known for byte in range(address, address + size)) or
                   size == 4 and any(address == node + offset for node in node_addresses for offset in (0x18, 0x24)) or
                   # Original doubly-linked resource-list unlink (0x64c8300: str next,[prev+4];
                   # str prev,[next]). Only these two stores, only into captured bytes.
                   (uc.reg_read(UC_ARM_REG_PC) in (0x64c8314, 0x64c831a, 0x64c831c, 0x64c8322) and size == 4 and
                    all(byte in known for byte in range(address, address + size))))
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
    sync_fields = [(0x12abf0, 'resource_manager_mutex_lock'), (0x12abf8, 'resource_manager_mutex_owner'),
                   (0x12ac00, 'resource_manager_mutex_users'), (0x36fdac, 'participation_mutex_lock'),
                   (0x36fdb4, 'participation_mutex_owner'), (0x36fdbc, 'participation_mutex_users'),
                   (0x36fda0, 'participation_count'), (0x36fdc8, 'condition_internal_lock')]
    initial_sync = {address: bytes(uc.mem_read(address, 4)) for address, _label in sync_fields
                    if all(address + i in known for i in range(4))}
    error = None
    native_selection = []
    navigation = None
    try:
        if args.active_state:
            node = int(path[0]['object'], 16)
            for level in range(3):
                table = struct.unpack('<I', uc.mem_read(node, 4))[0]
                entry = struct.unpack('<I', uc.mem_read(table + 0x28, 4))[0]
                uc.reg_write(UC_ARM_REG_R0, node); uc.reg_write(UC_ARM_REG_R1, stack + 0x80)
                uc.reg_write(UC_ARM_REG_SP, stack + 0xff0); uc.reg_write(UC_ARM_REG_LR, end | 1)
                uc.emu_start(entry, end, count=2000)
                if uc.reg_read(UC_ARM_REG_PC) != end or uc.reg_read(UC_ARM_REG_R0) != 1:
                    raise ValueError('Original selected-node method did not return success')
                child = struct.unpack('<I', uc.mem_read(stack + 0x80, 4))[0]
                if child != int(path[level + 1]['object'], 16): raise ValueError('Original selection differs from captured model edge')
                native_selection.append(dict(node=hex(node), selected=hex(child)))
                node = child
            if args.native_row_entry:
                navigation = dict(explicit_control=True, physical_key_mapping_proven=False, direction=1,
                                  before_flag=uc.mem_read(menu + 0x1d8, 1)[0],
                                  before_row=struct.unpack('<i', uc.mem_read(menu + 0x1f8, 4))[0])
                uc.reg_write(UC_ARM_REG_R0, stack + 0x100); uc.reg_write(UC_ARM_REG_R1, menu)
                uc.reg_write(UC_ARM_REG_R2, 1)
                uc.reg_write(UC_ARM_REG_SP, stack + 0xff0); uc.reg_write(UC_ARM_REG_LR, end | 1)
                uc.emu_start(0x15b91573, end, count=10000)
                if uc.reg_read(UC_ARM_REG_PC) != end: raise ValueError('Original navigation did not return')
                if not all(stack + 0x100 + i in known for i in range(12)): raise ValueError('Navigation result not written by original code')
                navigation['original_result'] = list(struct.unpack('<3i', uc.mem_read(stack + 0x100, 12)))
                navigation['after_flag'] = uc.mem_read(menu + 0x1d8, 1)[0]
                uc.reg_write(UC_ARM_REG_R0, menu)
                uc.reg_write(UC_ARM_REG_SP, stack + 0xff0); uc.reg_write(UC_ARM_REG_LR, end | 1)
                uc.emu_start(0x15b91431, end, count=10000)
                if uc.reg_read(UC_ARM_REG_PC) != end: raise ValueError('Original post-navigation binding did not return')
                navigation['bound_row'] = struct.unpack('<i', uc.mem_read(menu + 0x1f8, 4))[0]
                if navigation['bound_row'] != navigation['original_result'][2]:
                    raise ValueError('Native navigation and current model selection disagree; not forcing model state')
            uc.reg_write(UC_ARM_REG_R0, menu); uc.reg_write(UC_ARM_REG_R1, node)
            uc.reg_write(UC_ARM_REG_SP, stack + 0xff0); uc.reg_write(UC_ARM_REG_LR, end | 1)
        entry = 0x15b92045
        if args.refresh_only:
            # Direct source-verified method control. The retained table prefix
            # does not cover +0x1ac; do not invent that missing virtual slot.
            entry = 0x15b92111
            # Original ViewSettingMenu refresh of resource A056F604 passes0.
            uc.reg_write(UC_ARM_REG_R1, 0)
        uc.emu_start(entry, end, count=50000)
    except Exception as exception: error = str(exception)
    returned = uc.reg_read(UC_ARM_REG_PC) == end and error is None
    if not returned and error is None: error = 'Original instruction bound reached'
    restored = []
    for address, label in sync_fields:
        if address in initial_sync:
            relevant = [write for write in writes if int(write['address'], 16) == address]
            if relevant:
                restored.append(dict(field=label, address=hex(address), captured_value=struct.unpack('<I', initial_sync[address])[0],
                                     final_value=struct.unpack('<I', uc.mem_read(address, 4))[0], writes=relevant,
                                     restored_to_capture=bytes(uc.mem_read(address, 4)) == initial_sync[address]))
    report = dict(scope=__doc__, source_non_atomic=True, returned=returned, exploratory_auxiliary_usb_control=args.auxiliary_usb_control, exploratory_packed_index_usb_control=args.packed_index_usb_control, auxiliary_usb_sources=auxiliary_sources,
                  explicit_main_thread_control=args.main_thread_control, originating_ui_thread_proven=False,
                  explicit_resource_snapshot=args.resource_snapshot,
                  explicit_active_menu_resource_header=args.menu_resource_header,
                  coupled_active_capture=str(args.active_state) if args.active_state else None,
                  original_selected_node_calls=native_selection,
                  native_navigation_control=navigation, original_fastbin_pops=fastbin_pops,
                  instructions=len(trace), error=error, boundary=boundary, pc=hex(uc.reg_read(UC_ARM_REG_PC)),
                  registers={name: hex(uc.reg_read(reg)) for name, reg in [('r0', UC_ARM_REG_R0), ('r1', UC_ARM_REG_R1), ('r2', UC_ARM_REG_R2), ('r3', UC_ARM_REG_R3), ('r4', UC_ARM_REG_R4), ('r5', UC_ARM_REG_R5), ('lr', UC_ARM_REG_LR)]},
                  writes=writes, trace=trace, resource_accounting_observations=accounting,
                  resource_reference_observations=reference_checks,
                  synchronization_observations=restored, activation_success_proven=False)
    report['call_contract_observations'] = call_contract_observations
    report['refresh_only_control'] = args.refresh_only
    report['visible_camera_refresh_proven'] = False
    if args.refresh_only:
        report['scope'] = ('Direct original ListTab refresh method on retained active state; '
                           'no activation call; explicit offline thread control, not live UI execution')
        report['refresh_entry'] = '0x15b92111'
        report['refresh_argument'] = 0
        report['refresh_returned'] = returned
    report['bitmap_synchronization_observations'] = []
    for bitmap, initial in bitmap_initial.items():
        after = bytes(uc.mem_read(bitmap,0x80))
        offsets = (0x18,0x24,0x2c,0x34,0x40)
        before_values = [struct.unpack_from('<I',initial,i)[0] for i in offsets]
        after_values = [struct.unpack_from('<I',after,i)[0] for i in offsets]
        report['bitmap_synchronization_observations'].append(dict(bitmap=hex(bitmap),lock_calls=bitmap_lock_calls[bitmap],
            offsets=[hex(i) for i in offsets],before=before_values,after=after_values,restored=before_values==after_values))
    report['resource_acquisition_observations'] = acquisition_checks
    report['resource_list_observations'] = resource_lists
    report['boundary_pointer_provenance'] = {hex(uc.reg_read(reg)): pointer_reads.get(uc.reg_read(reg), []) for reg in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R4, UC_ARM_REG_R5)}
    destination = ROOT / 'artifacts/analysis' / ('menu-activation-coupled-state-probe.json' if args.active_state else 'menu-activation-live-resource-header-probe.json' if args.menu_resource_header else 'menu-activation-resource-snapshot-probe.json' if args.resource_snapshot else 'menu-activation-main-thread-snapshot-probe.json' if args.main_thread_control else 'menu-activation-snapshot-probe.json')
    if args.auxiliary_usb_control: destination = destination.with_name('menu-activation-auxiliary-usb-control.json')
    if args.packed_index_usb_control: destination = destination.with_name('menu-activation-packed-index-usb-control.json')
    if args.refresh_only: destination = destination.with_name('menu-refresh-coupled-state-probe.json')
    destination.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key not in ('trace', 'writes', 'scope', 'synchronization_observations', 'call_contract_observations', 'boundary_pointer_provenance', 'resource_acquisition_observations', 'resource_reference_observations', 'bitmap_synchronization_observations')}, indent=2))
    print(destination)


if __name__ == '__main__': main()
