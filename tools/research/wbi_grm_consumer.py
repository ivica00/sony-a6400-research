"""Bounded captured original GRM lookup under an explicit selected page-table root."""
import argparse
import io
import json
import struct

import unicorn
from unicorn import arm_const as arm
from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input
from tools.research.wbi_logging_trace import PackageMemory
from tools.research.wbi_memory import IMAGE
from tools.research.wbi_pagewalk import translate, read_virtual
from tools.research.storage_trace import module_relocations
from tools.research.mount_evidence import symbol
from tools.research.dmm_runtime_trace import KERNEL, KERNEL_BASE

MODULE = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/grm_ma.ko'
ROOT, CODE, HEAD = 0x104000, 0x5f3f8000, 0x5f3fc348
STACK, REQUEST, RETURN = 0x08000000, 0x08100000, 0x09000000


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', required=True)
    parser.add_argument('--name', choices=('gl_common', 'absent_control'), default='gl_common')
    parser.add_argument('--operation', choices=('lookup', 'open', 'callback'), default='lookup')
    parser.add_argument('--mutex-prefix', action='store_true', help='Execute verified kernel locking prefix with unknown stack-state reads guarded')
    args = parser.parse_args(argv)
    if args.mutex_prefix and args.operation != 'callback':
        parser.error('--mutex-prefix requires --operation callback')
    output = (PROJECT_ROOT / args.report_dir).resolve()
    if not output.is_relative_to(PROJECT_ROOT / 'artifacts'):
        parser.error('Output must remain under artifacts')
    output.mkdir(parents=True, exist_ok=False)
    hashes = {r['path']: r['sha256'] for r in json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text())['inputs']}
    originals = {p: checked_input(PROJECT_ROOT, p, hashes[p]) for p in (IMAGE, MODULE, KERNEL)}
    memory = PackageMemory(originals[IMAGE])
    elf = ELFFile(io.BytesIO(originals[MODULE]))
    text = elf.get_section_by_name('.text')
    text_index = next(i for i, s in enumerate(elf.iter_sections()) if s.name == '.text')
    relocated = {o for (i, o) in module_relocations(elf) if i == text_index}
    captured = read_virtual(memory, ROOT, CODE, text['sh_size'])
    expected = text.data()
    checked = 0
    for offset in range(0, len(expected), 4):
        if offset in relocated:
            continue
        if expected[offset:offset + 4] != captured[offset:offset + 4]:
            raise ValueError('Captured module text mismatch at ' + hex(offset))
        checked += len(expected[offset:offset + 4])
    physical, head_walk = translate(memory, ROOT, HEAD)
    if physical != 0x096ce348:
        raise ValueError('Captured head mapping mismatch')
    # Static boot instruction explicitly constructs 0x104000 in r4.
    if originals[KERNEL][0x54:0x58] != struct.pack('<I', 0xe3a04941):
        raise ValueError('Kernel table-base instruction changed')
    names = (('ma_dmm_open_impl', 'ma_dmm_open_send_recv') if args.operation == 'open'
             else (('ma_user_sync_cb', 'ma_findbyname_impl', 'ma_list_findbyname') if args.operation == 'callback'
                   else ('ma_findbyname_impl', 'ma_list_findbyname')))
    allowed = [(CODE + symbol(elf, n)['st_value'], CODE + symbol(elf, n)['st_value'] + symbol(elf, n)['st_size']) for n in names]
    # Resolve the actual relocated strncmp call, rather than substituting a helper.
    lookup = symbol(elf, 'ma_list_findbyname')
    calls = [(o, r) for (i, o), r in module_relocations(elf).items() if i == text_index and r['symbol'] == 'strncmp'
             and lookup['st_value'] <= o < lookup['st_value'] + lookup['st_size']]
    if len(calls) != 1:
        raise ValueError('Ambiguous original strncmp call')
    call_offset = calls[0][0]
    word = struct.unpack_from('<I', captured, call_offset)[0]
    if word >> 24 != 0xeb:
        raise ValueError('Unexpected original branch encoding')
    delta = (word & 0xffffff) << 2
    if delta & 0x2000000:
        delta -= 0x4000000
    compare = CODE + call_offset + 8 + delta
    if not KERNEL_BASE <= compare < KERNEL_BASE + len(originals[KERNEL]) - 256:
        raise ValueError('Comparison target is outside preserved kernel')
    compare_bytes = read_virtual(memory, ROOT, compare, 256)
    if compare_bytes != originals[KERNEL][compare - KERNEL_BASE:compare - KERNEL_BASE + 256]:
        raise ValueError('Captured comparison code differs from preserved kernel')
    if args.operation != 'open':
        allowed.append((compare, compare + 256))
    imports = {CODE + o: r['symbol'] for (i, o), r in module_relocations(elf).items()
               if i == text_index and r['type'] == 28 and r['symbol_section'] == 'SHN_UNDEF'}
    if args.operation != 'open':
        # This exact captured call target was verified against original kernel
        # bytes above and is explicitly included in the executable windows.
        imports.pop(CODE + call_offset)
    mutex_prefix_windows = []
    if args.mutex_prefix:
        # Bounded original paths observed from the captured _mutex_lock BL.
        mutex_prefix_windows = [(0x603c6998, 0x603c69ac), (0x603c60ec, 0x603c610c),
                                (0x603c5f98, 0x603c5fc8), (0x603c6ed8, 0x603c6eec),
                                (0x603c6e40, 0x603c6e60)]
        for begin, end in mutex_prefix_windows:
            if read_virtual(memory, ROOT, begin, end - begin) != originals[KERNEL][begin - KERNEL_BASE:end - KERNEL_BASE]:
                raise ValueError('Captured mutex prefix differs from preserved kernel')
        callback = symbol(elf, 'ma_user_sync_cb')
        sites = [address for address, name in imports.items() if name == '_mutex_lock'
                 and CODE + callback['st_value'] <= address < CODE + callback['st_value'] + callback['st_size']]
        if len(sites) != 1:
            raise ValueError('Ambiguous original mutex call')
        branch = struct.unpack_from('<I', captured, sites[0] - CODE)[0]
        delta = (branch & 0xffffff) << 2
        if delta & 0x2000000:
            delta -= 0x4000000
        if branch >> 24 != 0xeb or sites[0] + 8 + delta != mutex_prefix_windows[0][0]:
            raise ValueError('Captured mutex call target changed')
        del imports[sites[0]]
        allowed.extend(mutex_prefix_windows)
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
    mu.mem_map(STACK, 16384)
    mu.mem_map(REQUEST, 4096)
    request_name = args.name.encode('ascii') + b'\0'
    request_name = request_name.ljust(16, b'\0')
    packet = request_name + b'\xa5' * 16
    reply_offset = 16
    input_pointer = REQUEST
    if args.operation == 'open':
        packet = struct.pack('<HHIB', 1, 0, 0x280, 0) + request_name + bytes(3) + b'\xa5' * 16
        reply_offset, input_pointer = 28, REQUEST + 4
    elif args.operation == 'callback':
        packet = struct.pack('<HH', 7, 0) + request_name + b'\xa5' * 16
        reply_offset = 20
    mu.mem_write(REQUEST, packet)
    mu.mem_map(RETURN, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    pages = set()
    stack_written = set()
    walks = []
    report = {'inputs': {p: hashes[p] for p in originals}, 'status': 'running', 'selected_root': ROOT, 'name': args.name,
        'head_walk': head_walk, 'text_verified_nonrelocated_bytes': checked,
        'text_relocation_words': len(relocated), 'comparison_target': compare,
        'trace': [], 'writes': [], 'page_walks': walks,
        'limitations': ['Selected captured root, not recovered active TTBR/TTBCR or a full MMU simulation.',
            'Isolated lookup with constructed name/output/stack; no IPC, locks or allocator lifecycle executed.',
            'Original snapshot backing is copied into disposable RAM; preserved inputs are unchanged.',
            'No current camera state, cold-start allocation reply or GUI advancement.']}
    if args.operation == 'open':
        report.update(operation='open', request_before=packet.hex())
    elif args.operation == 'callback':
        report.update(operation='callback', request_before=packet.hex())
        if args.mutex_prefix:
            report.update(mutex_prefix=True, verified_kernel_windows=mutex_prefix_windows,
                          mutex_entries=[], stack_write_ranges=[])
            report['limitations'] = ['Original callback and source-verified kernel lock prefix only.',
                'Constructed stack has no supplied kernel thread context; reads of unwritten stack bytes stop.',
                'No completed lock, IPC exchange, owner task, scheduler state or current camera boot is supplied.']

    def stop(reason, **details):
        report.update(status=reason, boundary={'pc': mu.reg_read(arm.UC_ARM_REG_PC), **details})
        mu.emu_stop()

    def supply(address):
        page = address & ~4095
        if page not in pages:
            data = read_virtual(memory, ROOT, page, 4096)
            _, walk = translate(memory, ROOT, page)
            mu.mem_map(page, 4096)
            mu.mem_write(page, data)
            pages.add(page)
            walks.append(walk)

    def code(uc, address, size, _):
        if args.mutex_prefix and address == 0x603c6998:
            mutex_address = uc.reg_read(arm.UC_ARM_REG_R0)
            report['mutex_entries'].append({'address': mutex_address,
                'snapshot_prefix': read_virtual(memory, ROOT, mutex_address, 24).hex()})
        if address == RETURN:
            stop('isolated_lookup_return')
        elif address in imports:
            stop('unsupported_import', symbol=imports[address],
                 arguments=[uc.reg_read(r) for r in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2, arm.UC_ARM_REG_R3)])
        elif not any(a <= address and address + size <= b for a, b in allowed):
            stop('unsupported_control_flow', address=address)
        else:
            report['trace'].append({'pc': address, 'bytes': bytes(uc.mem_read(address, size)).hex()})

    def write(uc, access, address, size, value, _):
        if STACK <= address and address + size <= STACK + 16384:
            if args.mutex_prefix:
                stack_written.update(range(address, address + size))
                report['stack_write_ranges'].append({'address': address, 'size': size})
            return
        if (size == 4 and address in tuple(REQUEST + reply_offset + i for i in (0, 4, 8, 12))) or (args.operation != 'open' and size == 2 and address == 0x68a96222):
            report['writes'].append({'pc': uc.reg_read(arm.UC_ARM_REG_PC), 'address': address, 'size': size, 'value': value})
        else:
            stop('unsupported_write', address=address, size=size)

    def read(uc, access, address, size, value, _):
        if STACK <= address and address + size <= STACK + 16384:
            if args.mutex_prefix and not all(a in stack_written for a in range(address, address + size)):
                stop('unsupplied_kernel_stack_state', address=address, size=size)
            return
        if REQUEST <= address and address + size <= REQUEST + len(packet):
            return
        if all(page in pages for page in range(address & ~4095, (address + size - 1 & ~4095) + 1, 4096)):
            return
        # Unmapped snapshot reads are checked and supplied by invalid().
        if address & ~4095 in (REQUEST, RETURN):
            stop('constructed_memory_padding_read', address=address, size=size)

    def invalid(uc, access, address, size, value, _):
        if access not in (unicorn.UC_MEM_READ_UNMAPPED, unicorn.UC_MEM_FETCH_UNMAPPED):
            stop('unsupported_memory_access', address=address, access=access)
            return False
        try:
            supply(address)
            if (address & 4095) + size > 4096:
                supply(address + size - 1)
            return True
        except ValueError as error:
            stop('unsupplied_snapshot_memory', address=address, error=str(error))
            return False

    mu.hook_add(unicorn.UC_HOOK_CODE, code)
    mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, write)
    mu.hook_add(unicorn.UC_HOOK_MEM_READ, read)
    mu.hook_add(unicorn.UC_HOOK_MEM_INVALID, invalid)
    mu.reg_write(arm.UC_ARM_REG_CPSR, 0x10)
    mu.reg_write(arm.UC_ARM_REG_SP, STACK + 0x3000)
    mu.reg_write(arm.UC_ARM_REG_R0, input_pointer)
    mu.reg_write(arm.UC_ARM_REG_R1, REQUEST + reply_offset)
    mu.reg_write(arm.UC_ARM_REG_LR, RETURN)
    try:
        mu.emu_start(allowed[0][0], 0, count=10000, timeout=1000000)
    except unicorn.UcError as error:
        if report['status'] == 'running':
            report.update(status='execution_fault', error=str(error))
    if report['status'] == 'running':
        report['status'] = 'timeout' if mu.query(unicorn.UC_QUERY_TIMEOUT) else 'instruction_limit'
    report['reply'] = list(struct.unpack('<4I', mu.mem_read(REQUEST + reply_offset, 16)))
    report['return_register'] = mu.reg_read(arm.UC_ARM_REG_R0)
    for p in originals:
        checked_input(PROJECT_ROOT, p, hashes[p])
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    print(output, report['status'], len(report['trace']), report['reply'])
    return report


if __name__ == '__main__':
    main()
