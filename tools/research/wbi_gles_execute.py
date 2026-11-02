"""Execute captured original GLES queries/cache prefix without GPU replies."""
import argparse
import io
import json
import struct

import unicorn
from unicorn import arm_const as arm
from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.dmm_runtime_trace import KERNEL, KERNEL_BASE
from tools.research.gles_contract_trace import MODULE
from tools.research.mount_evidence import checked_input
from tools.research.storage_trace import module_relocations
from tools.research.wbi_gles_state import ROOT
from tools.research.wbi_logging_trace import PackageMemory
from tools.research.wbi_memory import IMAGE
from tools.research.wbi_pagewalk import read_virtual

STACK, OUTPUT, FILE, RETURN = 0x08000000, 0x08100000, 0x08200000, 0x09000000
CAPTURED_CODE = 0x5f400000
CAPTURED_GRAPHICS_THREAD_INFO = 0x684a8000


def load_context():
    hashes = {row['path']: row['sha256'] for row in json.loads(
        (PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text())['inputs']}
    originals = {path: checked_input(PROJECT_ROOT, path, hashes[path]) for path in (IMAGE, MODULE, KERNEL)}
    memory = PackageMemory(originals[IMAGE])
    # Explicit package mapping identified by wbi_gles_state. Reverify the
    # original bytes and anchors instead of depending on a generated report.
    if originals[KERNEL][0x54:0x58] != struct.pack('<I', 0xe3a04941):
        raise ValueError('Selected-root kernel instruction changed')
    base = CAPTURED_CODE
    elf = ELFFile(io.BytesIO(originals[MODULE]))
    index = next(i for i, section in enumerate(elf.iter_sections()) if section.name == '.text')
    original = elf.get_section(index).data()
    captured = read_virtual(memory, ROOT, base, len(original))
    relocations = module_relocations(elf)
    excluded = {off for (i, off) in relocations if i == index}
    for offset in range(0, len(original), 4):
        if offset not in excluded and original[offset:offset + 4] != captured[offset:offset + 4]:
            raise ValueError('Captured GLES text differs from original module')
    if (relocations[(index, 0x1414)]['symbol'] != 'outer_cache'
            or relocations[(index, 0x1734)]['target_offset'] != 0x78):
        raise ValueError('Captured state anchors differ')
    slot = struct.unpack_from('<I', captured, 0x1734)[0]
    device = struct.unpack('<I', read_virtual(memory, ROOT, slot, 4))[0]
    outer = struct.unpack_from('<I', captured, 0x1414)[0]
    sync = struct.unpack('<I', read_virtual(memory, ROOT, outer + 28, 4))[0]
    helpers = {'__put_user_4': [], '__get_user_4': []}
    imports = {}
    for (i, offset), relocation in relocations.items():
        if i == index and relocation['type'] == 28 and relocation['symbol_section'] == 'SHN_UNDEF':
            imports[base + offset] = relocation['symbol']
            if relocation['symbol'] in helpers and 0x900 <= offset < 0x1328:
                word = struct.unpack_from('<I', captured, offset)[0]
                delta = (word & 0xffffff) << 2
                if delta & 0x2000000:
                    delta -= 0x4000000
                if word >> 24 != 0xeb:
                    raise ValueError('Captured user-copy call is not ARM BL')
                helpers[relocation['symbol']].append(base + offset + 8 + delta)
                del imports[base + offset]
    if any(not targets or len(set(targets)) != 1 for targets in helpers.values()):
        raise ValueError('Original user-copy helpers are ambiguous')
    putter, getter = helpers['__put_user_4'][0], helpers['__get_user_4'][0]
    allocation_site = base + 0x59c
    if imports.get(allocation_site) != 'kmem_cache_alloc':
        raise ValueError('Original new-owner allocation call differs')
    word = struct.unpack_from('<I', captured, 0x59c)[0]
    delta = (word & 0xffffff) << 2
    if delta & 0x2000000:
        delta -= 0x4000000
    if word >> 24 != 0xeb:
        raise ValueError('Original allocation call is not ARM BL')
    allocator = allocation_site + 8 + delta
    if relocations[(index, 0x63c)]['symbol'] != 'malloc_sizes':
        raise ValueError('Original new-owner cache table relocation differs')
    cache_table = struct.unpack_from('<I', captured, 0x63c)[0]
    if struct.unpack_from('<I', captured, 0x598)[0] != 0xe593000c:
        raise ValueError('Original new-owner cache table index differs')
    allocation_cache = struct.unpack('<I', read_virtual(memory, ROOT, cache_table + 12, 4))[0]
    word = struct.unpack_from('<I', captured, 0x450)[0]
    delta = (word & 0xffffff) << 2
    if delta & 0x2000000:
        delta -= 0x4000000
    if word >> 24 != 0xeb or imports.get(base + 0x450) != '__migrate_disable':
        raise ValueError('Original migration call differs')
    migrate = base + 0x450 + 8 + delta
    kernel = originals[KERNEL]
    for start, length in ((putter, 60), (getter, 36), (sync, 40), (migrate, 160)):
        if start & 3 or not KERNEL_BASE <= start < start + length <= KERNEL_BASE + len(kernel):
            raise ValueError('Kernel helper escapes original kernel')
        if read_virtual(memory, ROOT, start, length) != kernel[start-KERNEL_BASE:start-KERNEL_BASE+length]:
            raise ValueError('Captured helper does not match preserved kernel')
    locks = []
    for name in ('sugilite_event_open_lock', 'sugilite_event_list_lock'):
        symbols = [symbol for symbol in elf.get_section_by_name('.symtab').iter_symbols() if symbol.name == name]
        if len(symbols) != 1 or symbols[0]['st_size'] != 28:
            raise ValueError('Original GLES lock extent differs')
        address = slot - 0x78 + symbols[0]['st_value']
        locks.append((address, address + symbols[0]['st_size']))
    return {'memory': memory, 'base': base, 'device': device, 'sync': sync, 'putter': putter, 'getter': getter,
            'migrate': migrate, 'owner_head': slot - 0x78, 'imports': imports,
            'kernel': kernel, 'lock_ranges': locks,
            'allocator': allocator,
            'allocation_cache': allocation_cache,
            'inputs': {path: hashes[path] for path in originals}}


def execute(context, command=None, *, address_limit=0x80000000, argument=OUTPUT,
            input_word=0xa5a5a5a5, owner_tgid=None, open_thread_info=None, follow_kernel_locks=False,
            allow_new_owner=False, follow_allocation_prefix=False, follow_allocator_cpu_lock=False,
            follow_allocator_freelist=False, follow_allocator_object=False,
            follow_owner_initializers=False, instruction_budget=1000, owner_lifecycle=False):
    if not 1 <= instruction_budget <= 100000:
        raise ValueError('Instruction budget exceeds bounded research limits')
    if sum(value is not None for value in (command, owner_tgid, open_thread_info)) > 1:
        raise ValueError('Select one original operation')
    memory, base = context['memory'], context['base']
    if follow_kernel_locks and open_thread_info is None:
        raise ValueError('Following kernel locks requires a captured owner task')
    if allow_new_owner and open_thread_info is None:
        raise ValueError('New-owner execution requires an actual captured task')
    if follow_allocation_prefix and not (allow_new_owner and follow_kernel_locks):
        raise ValueError('Allocation prefix requires explicit new-owner and kernel-lock controls')
    if follow_allocator_cpu_lock and not follow_allocation_prefix:
        raise ValueError('Allocator CPU lock requires the allocation prefix control')
    if follow_allocator_freelist and not follow_allocator_cpu_lock:
        raise ValueError('Allocator free-list control requires its CPU lock')
    if follow_allocator_object and not follow_allocator_freelist:
        raise ValueError('Allocator object initialization requires its verified free-list control')
    if follow_owner_initializers and not follow_allocator_object:
        raise ValueError('Owner initializers require original object allocation')
    if owner_lifecycle and not follow_owner_initializers:
        raise ValueError('Owner lifecycle requires original new-owner initialization')
    stack_base = STACK if open_thread_info is None else open_thread_info
    task_binding = None
    if open_thread_info is not None:
        if open_thread_info % 8192:
            raise ValueError('Kernel thread-info control must be aligned')
        header = read_virtual(memory, ROOT, open_thread_info, 64)
        task = struct.unpack_from('<I', header, 12)[0]
        task_data = read_virtual(memory, ROOT, task, 0x10c)
        if struct.unpack_from('<I', task_data, 8)[0] != open_thread_info:
            raise ValueError('Captured task/thread-info backlink differs')
        pid, tgid = struct.unpack_from('<2I', task_data, 0x104)
        owner = execute(context, owner_tgid=tgid)
        if owner['status'] != 'original_owner_lookup_return':
            raise ValueError('Original owner lookup did not return')
        if owner['return_register'] == 0 and not allow_new_owner:
            raise ValueError('Selected captured task does not own a GLES entry')
        if owner['return_register'] and follow_allocation_prefix:
            raise ValueError('Allocation-prefix controls require an absent owner')
        task_binding = {'thread_info': open_thread_info, 'task': task, 'pid': pid, 'tgid': tgid,
                        'header_hex': header.hex(), 'owner_entry': owner['return_register']}
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
    for address, length, permissions in ((stack_base, 8192, 3), (OUTPUT, 4096, 3),
                                         (FILE, 4096, 3 if open_thread_info is not None else 1),
                                         (RETURN, 4096, 5)):
        mu.mem_map(address, length, permissions)
    if open_thread_info is None:
        mu.mem_write(stack_base + 8, struct.pack('<I', address_limit))
        stack_written = set(range(stack_base + 8, stack_base + 12))
    else:
        mu.mem_write(stack_base, header)
        stack_written = set(range(stack_base, stack_base + len(header)))
    mu.mem_write(OUTPUT, struct.pack('<I', input_word))
    file_known = set()
    if open_thread_info is None:
        mu.mem_write(FILE + 0xa8, struct.pack('<I', context['device']))
        file_known.update(range(FILE + 0xa8, FILE + 0xac))
    pages = set()
    imports = dict(context['imports'])
    mutable = []
    allocator_cpu_lock = None
    allocator_freelist = None
    allocator_object = None
    allowed = ([(base + 0x900, base + 0x12e4), (context['putter'], context['putter'] + 60),
                (context['getter'], context['getter'] + 36)]
               if command is not None else
               [(base + 0x54, base + 0x1a4), (base + 0x13e0, base + 0x1414),
                (context['sync'], context['sync'] + 36)])
    if owner_tgid is not None:
        allowed = [(base, base + 0x54)]
    elif open_thread_info is not None:
        allowed = [(base + 0x43c, base + 0x630), (context['migrate'], context['migrate'] + 160)]
        del imports[base + 0x450]
        if follow_kernel_locks:
            mutable = [*context['lock_ranges'], (task + 0xa8, task + 0xac),
                       (context['device'] + 0x40, context['device'] + 0x48)]
            if task_binding['owner_entry']:
                mutable.append((task_binding['owner_entry'] + 12, task_binding['owner_entry'] + 16))
            allowed.append((base, base + 0x54))
            for address, name in list(imports.items()):
                if name in ('rt_spin_lock', 'rt_spin_unlock', '__migrate_disable', '__migrate_enable'):
                    del imports[address]
                elif follow_allocation_prefix and name in ('kmem_cache_alloc', 'kmalloc_add_trace'):
                    del imports[address]
                elif follow_owner_initializers and name in ('__init_waitqueue_head', 'complete_all'):
                    del imports[address]
                elif owner_lifecycle and name in ('kfree', 'completion_done'):
                    del imports[address]
            if owner_lifecycle:
                allowed.extend(((base + 0x310, base + 0x43c), (base + 0x900, base + 0x12e4)))
            if follow_allocator_cpu_lock:
                allocator = context['allocator']
                pointers = []
                for offset, register in ((0x24, 2), (0x2c, 3)):
                    original_word = struct.unpack_from('<I', context['kernel'], allocator-KERNEL_BASE+offset)[0]
                    if original_word & 0xfffff000 != 0xe59f0000 | register << 12:
                        raise ValueError('Allocator per-CPU literal instruction differs')
                    literal = allocator + offset + 8 + (original_word & 4095)
                    captured_word = read_virtual(memory, ROOT, literal, 4)
                    if captured_word != context['kernel'][literal-KERNEL_BASE:literal-KERNEL_BASE+4]:
                        raise ValueError('Allocator pointer literal identity differs')
                    pointers.append(struct.unpack('<I', captured_word)[0])
                cpu = struct.unpack_from('<I', header, 20)[0]
                if cpu >= 64:
                    raise ValueError('Captured CPU index exceeds research bound')
                cpu_offset = struct.unpack('<I', read_virtual(memory, ROOT, pointers[0] + cpu * 4, 4))[0]
                lock = pointers[1] + cpu_offset
                if not 0 <= lock < lock + 40 <= 1 << 32:
                    raise ValueError('Allocator per-CPU lock range overflows')
                mutable.append((lock, lock + 40))
                allocator_cpu_lock = {'cpu': cpu, 'offset_table': pointers[0], 'cpu_offset': cpu_offset,
                                      'base_literal': pointers[1], 'address': lock, 'size': 40}
                if follow_allocator_freelist:
                    cache = context['allocation_cache']
                    array = struct.unpack('<I', read_virtual(memory, ROOT, cache + cpu * 4, 4))[0]
                    if not array:
                        raise ValueError('Captured allocation array is NULL for selected CPU')
                    available, limit, batch, touched = struct.unpack('<4I', read_virtual(memory, ROOT, array, 16))
                    if not 0 < available <= limit <= 4096 or batch > limit:
                        raise ValueError('Captured allocation array exceeds supported nonempty bounds')
                    slot = array + available * 4 + 0x28
                    candidate = struct.unpack('<I', read_virtual(memory, ROOT, slot, 4))[0]
                    mutable.extend(((array, array + 4), (array + 12, array + 16)))
                    allocator_freelist = {'cache': cache, 'array': array, 'available': available,
                                          'limit': limit, 'batch': batch, 'touched': touched,
                                          'selected_slot': slot, 'candidate_object': candidate}
                    if follow_allocator_object:
                        size = struct.unpack('<I', read_virtual(memory, ROOT, cache + 0x1c, 4))[0]
                        if size != 64 or candidate & 3 or not 0 <= candidate < candidate + size <= 1 << 32:
                            raise ValueError('Selected object does not fit original 60-byte owner in 64-byte cache')
                        if any(begin < candidate + size and candidate < end for begin, end in mutable):
                            raise ValueError('Selected free object overlaps known live mutation ranges')
                        read_virtual(memory, ROOT, candidate, size)
                        mutable.append((candidate, candidate + size))
                        allocator_object = {'address': candidate, 'size': size, 'cache_size_offset': 0x1c,
                                            'requested_owner_bytes': 60}
                        if follow_owner_initializers:
                            head = context['owner_head']
                            first, last = struct.unpack('<2I', read_virtual(memory, ROOT, head, 8))
                            if first != last or struct.unpack('<2I', read_virtual(memory, ROOT, first, 8)) != (head, head):
                                raise ValueError('Expected reciprocal single-owner list before new insertion')
                            mutable.extend(((head, head + 8), (last, last + 4)))
                            if owner_lifecycle:
                                wait_head = last + 0x34
                                if struct.unpack('<2I', read_virtual(memory, ROOT, wait_head, 8)) != (wait_head, wait_head):
                                    raise ValueError('Peer completion has waiters requiring a scheduler contract')
                                mutable.extend(((slot, slot + 4), (last + 0x14, last + 0x3c)))
    active_call = 'open' if open_thread_info is not None else 'query'
    report = {'status': 'running', 'command': command, 'trace': [], 'writes': [],
              'instruction_budget': instruction_budget, 'timeout_us': 1000000, 'privilege_mode_control': 0x13,
              'cpu': 'Cortex-A9 provisional research control, not verified camera CPU',
              'address_limit_control': (address_limit if open_thread_info is None else
                                         struct.unpack_from('<I', header, 8)[0]),
              'argument': argument, 'input_word': input_word, 'stack_base': stack_base,
              'owner_tgid_control': owner_tgid,
              'captured_task_control': task_binding,
              'follow_kernel_locks': follow_kernel_locks, 'mutation_ranges': mutable,
              'allow_new_owner': allow_new_owner, 'follow_allocation_prefix': follow_allocation_prefix,
              'allocator_cpu_lock': allocator_cpu_lock,
              'allocator_freelist': allocator_freelist,
              'allocator_object': allocator_object,
              'follow_owner_initializers': follow_owner_initializers,
              'owner_lifecycle': owner_lifecycle, 'calls': [],
              'hardware_responses_supplied': 0, 'service_returns_supplied': 0}

    def stop(reason, **details):
        report.update(status=reason, boundary={'pc': mu.reg_read(arm.UC_ARM_REG_PC), **details})
        mu.emu_stop()

    def supply(address):
        page = address & ~4095
        if page not in pages:
            data = read_virtual(memory, ROOT, page, 4096)
            permissions = unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC
            if any(begin < page + 4096 and page < end for begin, end in mutable):
                permissions |= unicorn.UC_PROT_WRITE
            mu.mem_map(page, 4096, permissions)
            mu.mem_write(page, data)
            pages.add(page)

    def code(uc, address, size, _):
        kernel_instruction = (follow_kernel_locks and
                              KERNEL_BASE <= address <= address + size <= KERNEL_BASE + len(context['kernel']))
        if address == RETURN:
            stop('original_driver_release_return' if active_call == 'release' else
                 'original_owner_lookup_return' if owner_tgid is not None else
                 'original_ioctl_return' if active_call == 'query' else
                 'original_driver_open_return' if open_thread_info is not None else 'original_ioctl_return')
        elif address in imports:
            stop('unsupported_kernel_import', symbol=imports[address])
        elif not kernel_instruction and not any(begin <= address and address + size <= end for begin, end in allowed):
            stop('unsupported_control_flow', address=address)
        else:
            raw = bytes(uc.mem_read(address, size))
            if kernel_instruction and raw != context['kernel'][address-KERNEL_BASE:address-KERNEL_BASE+size]:
                stop('kernel_instruction_identity_mismatch', address=address)
                return
            instruction = int.from_bytes(raw, 'little')
            if instruction & 0x0f000010 == 0x0e000010 and instruction >> 8 & 15 == 15:
                stop('unsupplied_cpu_system_register', instruction_bytes=raw.hex())
                return
            report['trace'].append({'pc': address, 'bytes': raw.hex()})

    def read(uc, access, address, size, value, _):
        if stack_base <= address < stack_base + 8192:
            if not all(byte in stack_written for byte in range(address, address + size)):
                stop('unsupplied_kernel_stack_state', address=address, size=size)
        elif FILE <= address < FILE + 4096:
            if not all(byte in file_known for byte in range(address, address + size)):
                stop('constructed_file_padding_read', address=address, size=size)
        elif OUTPUT <= address < OUTPUT + 4096 and address + size > OUTPUT + 4:
            stop('constructed_output_padding_read', address=address, size=size)

    def write(uc, access, address, size, value, _):
        if stack_base <= address <= address + size <= stack_base + 8192:
            stack_written.update(range(address, address + size))
        elif (((command is not None or active_call == 'query') and address == OUTPUT and size == 4)
              or (open_thread_info is not None and address == FILE + 0xa8 and size == 4)):
            if address == FILE + 0xa8:
                file_known.update(range(address, address + size))
            report['writes'].append({'pc': uc.reg_read(arm.UC_ARM_REG_PC), 'address': address,
                                     'size': size, 'value': value})
        elif any(begin <= address <= address + size <= end for begin, end in mutable):
            report['writes'].append({'pc': uc.reg_read(arm.UC_ARM_REG_PC), 'address': address,
                                     'size': size, 'value': value})
        else:
            stop('unsupported_device_or_snapshot_write', address=address, size=size, value=value)

    def invalid(uc, access, address, size, value, _):
        if report['status'] != 'running':
            return False
        if access not in (unicorn.UC_MEM_READ_UNMAPPED, unicorn.UC_MEM_FETCH_UNMAPPED):
            stop('unsupported_memory_access', address=address, size=size, access=access)
            return False
        try:
            supply(address)
            supply(address + size - 1)
            return True
        except ValueError as error:
            stop('unsupplied_snapshot_memory', address=address, error=str(error))
            return False

    mu.hook_add(unicorn.UC_HOOK_CODE, code)
    mu.hook_add(unicorn.UC_HOOK_MEM_READ, read)
    mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, write)
    mu.hook_add(unicorn.UC_HOOK_MEM_INVALID, invalid)
    before_mutations = []
    for begin, end in mutable:
        before_mutations.append(read_virtual(memory, ROOT, begin, end - begin))
        supply(begin)
        supply(end - 1)
    mu.reg_write(arm.UC_ARM_REG_CPSR, 0x13)
    mu.reg_write(arm.UC_ARM_REG_SP, stack_base + 0x1800)
    mu.reg_write(arm.UC_ARM_REG_LR, RETURN)
    mu.reg_write(arm.UC_ARM_REG_R0, owner_tgid if owner_tgid is not None else
                 FILE if command is not None else FILE + 0x400 if open_thread_info is not None else context['device'])
    if open_thread_info is not None:
        # Explicit inode fixture: its device pointer comes from verified captured state.
        mu.mem_write(FILE + 0x590, struct.pack('<I', context['device']))
        file_known.update(range(FILE + 0x590, FILE + 0x594))
    mu.reg_write(arm.UC_ARM_REG_R1, command if command is not None else FILE if open_thread_info is not None else 0)
    mu.reg_write(arm.UC_ARM_REG_R2, argument)
    entry = base + (0 if owner_tgid is not None else 0x900 if command is not None else
                    0x43c if open_thread_info is not None else 0x54)
    try:
        mu.emu_start(entry, 0, count=instruction_budget, timeout=1000000)
        if owner_lifecycle and report['status'] == 'original_driver_open_return' and mu.reg_read(arm.UC_ARM_REG_R0) == 0:
            report['calls'].append({'operation': 'open', 'returned': 0, 'instructions': len(report['trace']),
                'mutation_state': [{'start': begin, 'hex': bytes(mu.mem_read(begin, end-begin)).hex()}
                                   for begin, end in mutable]})
            previous_count = len(report['trace'])
            for next_call, next_entry in (('query', base + 0x900), ('release', base + 0x310)):
                remaining = instruction_budget - len(report['trace'])
                if remaining <= 0:
                    report['status'] = 'instruction_budget_exhausted'
                    break
                active_call = next_call
                report['status'] = 'running'
                mu.reg_write(arm.UC_ARM_REG_R0, FILE if next_call == 'query' else FILE + 0x400)
                mu.reg_write(arm.UC_ARM_REG_R1, 0x80048200 if next_call == 'query' else FILE)
                mu.reg_write(arm.UC_ARM_REG_R2, OUTPUT)
                mu.reg_write(arm.UC_ARM_REG_LR, RETURN)
                mu.reg_write(arm.UC_ARM_REG_SP, stack_base + 0x1800)
                mu.emu_start(next_entry, 0, count=remaining, timeout=1000000)
                returned = mu.reg_read(arm.UC_ARM_REG_R0)
                report['calls'].append({'operation': next_call, 'returned': returned,
                    'status': report['status'], 'instructions': len(report['trace']) - previous_count,
                    'output_word': struct.unpack('<I', mu.mem_read(OUTPUT, 4))[0]})
                previous_count = len(report['trace'])
                expected = 'original_ioctl_return' if next_call == 'query' else 'original_driver_release_return'
                if report['status'] != expected or returned != 0:
                    break
    except unicorn.UcError as error:
        if report['status'] == 'running':
            report.update(status='execution_fault', error=str(error))
    if report['status'] == 'running':
        report['status'] = 'timeout' if mu.query(unicorn.UC_QUERY_TIMEOUT) else 'instruction_budget_exhausted'
    report.update(return_register=mu.reg_read(arm.UC_ARM_REG_R0),
                  output_word=struct.unpack('<I', mu.mem_read(OUTPUT, 4))[0])
    if open_thread_info is not None:
        report['file_private_word'] = struct.unpack('<I', mu.mem_read(FILE + 0xa8, 4))[0]
    report['snapshot_mutations'] = [
        {'start': begin, 'end': end, 'before_hex': before.hex(),
         'after_hex': bytes(mu.mem_read(begin, end - begin)).hex()}
        for (begin, end), before in zip(mutable, before_mutations)]
    return report


def new_owner_options(thread_info):
    """Explicit research controls; every allocator/driver operation remains original code."""
    return dict(open_thread_info=thread_info, follow_kernel_locks=True,
                allow_new_owner=True, follow_allocation_prefix=True,
                follow_allocator_cpu_lock=True, follow_allocator_freelist=True,
                follow_allocator_object=True, follow_owner_initializers=True,
                instruction_budget=10000)


def run(new_owner_thread_info=None):
    context = load_context()
    cases = [execute(context, command) for command in
             (0x80048200, 0x80048205, 0x80048206, 0x80048207, 0x8004820a, 0x80048263,
              0x40048204, 0)]
    indexed = [execute(context, command, input_word=index)
               for command in (0xc0048201, 0xc0048202) for index in (0, 1)]
    rejected = execute(context, 0x80048200, address_limit=OUTPUT + 3)
    rejected_read = execute(context, 0xc0048202, address_limit=OUTPUT + 3, input_word=1)
    submission = execute(context, 0xc0048203, input_word=0x40000000)
    setup = execute(context)
    owner_node = struct.unpack('<I', read_virtual(context['memory'], ROOT, context['owner_head'], 4))[0]
    owner_tgid = struct.unpack('<I', read_virtual(context['memory'], ROOT, owner_node + 8, 4))[0]
    ownership = [execute(context, owner_tgid=owner_tgid), execute(context, owner_tgid=0xffffffff)]
    opened = execute(context, open_thread_info=CAPTURED_GRAPHICS_THREAD_INFO)
    kernel_open = execute(context, open_thread_info=CAPTURED_GRAPHICS_THREAD_INFO, follow_kernel_locks=True)
    result = {'inputs': context['inputs'], 'code_virtual': context['base'], 'selected_root': ROOT,
            'device_virtual': context['device'], 'original_put_user_4': context['putter'],
            'original_get_user_4': context['getter'], 'original_cache_sync': context['sync'],
            'queries': cases, 'indexed_queries': indexed, 'submission': submission,
            'owner_lookup': ownership,
            'captured_open_prefix': opened, 'original_migrate_disable': context['migrate'],
            'captured_open_kernel_trace': kernel_open,
            'address_limit_rejection': rejected, 'read_address_limit_rejection': rejected_read,
            'register_setup': setup,
            'limitations': ['Explicit captured package-WBI environment; not main-process open/driver initialization.',
                            'Constructed file pointer, stack, privilege mode and user address-limit controls.',
                            'Snapshot writes are confined to operation-specific declared kernel ranges in an isolated CPU copy.',
                            'Original input bytes remain immutable; unwritten stack and padding reads stop.',
                            'Captured task ownership is not a binding to the newly launched im.elf process.',
                            'No imported success, GPU MMIO result, interrupt, command execution or pixels supplied.']}
    if new_owner_thread_info is not None:
        result['new_owner_lifecycle'] = execute(context, **new_owner_options(new_owner_thread_info),
                                                owner_lifecycle=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', required=True)
    parser.add_argument('--new-owner-thread-info', type=lambda value: int(value, 0))
    args = parser.parse_args()
    output = (PROJECT_ROOT / args.report_dir).resolve()
    if not output.is_relative_to(PROJECT_ROOT / 'artifacts'):
        parser.error('Reports must remain under artifacts')
    output.mkdir(parents=True, exist_ok=False)
    report = run(args.new_owner_thread_info)
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print([(hex(case['command']), case['status'], hex(case['return_register']), hex(case['output_word']))
           for case in report['queries']])
    print('setup', report['register_setup']['status'], report['register_setup'].get('boundary'))
    opened = report['captured_open_kernel_trace']
    print('captured open', opened['status'], len(opened['trace']), 'instructions,', len(opened['writes']), 'writes')


if __name__ == '__main__':
    main()
