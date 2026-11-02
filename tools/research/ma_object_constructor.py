"""Original client constructor prefix with explicitly uninitialized test storage."""
import argparse
import io
import json
import struct

import unicorn
from unicorn import arm_const as arm
from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input
from tools.research.wbi_ma_client import CLIENT
from tools.research.startup_trace import plt_symbols, read_va, arm_rotated_immediate, file_to_va
from tools.research.ma_sysconf_trace import LIBC
from tools.research.pthread_init_profile import PTHREAD, profile as pthread_profile

OBJECT, STACK = 0x08300000, 0x08000000


def execute(raw, *, libc_raw=None, loader_state=None, pthread_raw=None, lookup_reply=None):
    elf = ELFFile(io.BytesIO(raw))
    if (elf.elfclass, elf.little_endian, elf['e_machine'], elf['e_type']) != (32, True, 'EM_ARM', 'ET_DYN'):
        raise ValueError('Expected original ARM32 dynamic library')
    sections = [s for s in elf.iter_sections() if s['sh_flags'] & 2 and s['sh_type'] != 'SHT_NOBITS']
    source_sections = [(s, 0) for s in sections]
    slots = (0x13704f0, 0x1370a18)
    relocations = {}
    for section in elf.iter_sections():
        if section['sh_type'] == 'SHT_REL':
            for relocation in section.iter_relocations():
                address = relocation['r_offset']
                relocations.setdefault(address, []).append((relocation['r_info_type'], relocation['r_info_sym']))
    for slot in slots:
        if relocations.get(slot) != [(23, 0)]:
            raise ValueError('Constructor GOT slot is not one R_ARM_RELATIVE relocation')
    bindings, libc_windows, pthread_windows = {}, [], []
    if pthread_raw is not None and libc_raw is None:
        raise ValueError('Pthread initializer execution requires the original loader/libc chain')
    if lookup_reply is not None and (pthread_raw is None or len(lookup_reply) != 4 or lookup_reply[0] != 0):
        raise ValueError('Lookup initialization requires a completed constructor and successful original lookup')
    if (libc_raw is None) != (loader_state is None):
        raise ValueError('Original libc and fresh loader state must be supplied together')
    if libc_raw is not None:
        libc = ELFFile(io.BytesIO(libc_raw))
        bias = 0x30000000
        symbols = {s.name: s for s in libc.get_section_by_name('.dynsym').iter_symbols()}
        for name in ('sysconf', 'getpagesize'):
            symbol = symbols[name]
            if symbol['st_shndx'] == 'SHN_UNDEF':
                raise ValueError('Undefined original libc function')
            entry = symbol['st_value'] & ~1
            libc_windows.append((bias + entry, bias + entry + symbol['st_size']))
        source_sections.extend((s, bias) for s in libc.iter_sections() if s['sh_flags'] & 2 and s['sh_type'] != 'SHT_NOBITS')
        for section in libc.iter_sections():
            if section['sh_type'] == 'SHT_REL':
                for relocation in section.iter_relocations():
                    address = bias + relocation['r_offset']
                    relocations.setdefault(address, []).append((relocation['r_info_type'], relocation['r_info_sym']))
        first, second, third = struct.unpack('<3I', read_va(elf, raw, 0x102f84, 12))
        if first & 0xfffff000 != 0xe28fc000 or second & 0xfffff000 != 0xe28cc000 or third & 0xfffff000 not in (0xe59cf000, 0xe5bcf000):
            raise ValueError('Unsupported original sysconf PLT stub')
        jump_slot = (0x102f84 + 8 + arm_rotated_immediate(first) + arm_rotated_immediate(second) + (third & 4095)) & 0xffffffff
        symbol_index = relocations.get(jump_slot, [(0, 0)])[0][1]
        dynsym = elf.get_section_by_name('.dynsym')
        if relocations.get(jump_slot) != [(22, symbol_index)] or dynsym.get_symbol(symbol_index).name != 'sysconf':
            raise ValueError('Original sysconf jump slot does not match')
        bindings[jump_slot] = {'symbol': 'sysconf', 'value': bias + symbols['sysconf']['st_value'], 'type': 22}
        word = lambda address: struct.unpack('<I', read_va(libc, libc_raw, address, 4))[0]
        loader_slot = (word(0x9b594) + 0x9b588 + word(0x9b598)) & 0xffffffff
        symbol_index = relocations.get(bias + loader_slot, [(0, 0)])[0][1]
        loader_symbol = libc.get_section_by_name('.dynsym').get_symbol(symbol_index)
        if relocations.get(bias + loader_slot) != [(21, symbol_index)] or loader_symbol.name != '_rtld_global_ro' or loader_symbol['st_shndx'] != 'SHN_UNDEF':
            raise ValueError('Original loader-global binding does not match')
        field = loader_state['field_address']
        produced_bytes = bytes.fromhex(loader_state['after'])
        writes = loader_state['writes']
        if (len(produced_bytes) != 4 or field != loader_state['symbol_address'] + 16 or len(writes) != 1
                or writes[0]['address'] != field or writes[0]['size'] != 4
                or produced_bytes != struct.pack('<I', writes[0]['value'])):
            raise ValueError('Loader field lacks a complete original producer store')
        bindings[bias + loader_slot] = {'symbol': '_rtld_global_ro', 'value': loader_state['symbol_address'], 'type': 21}
        object_word = lambda address: struct.unpack('<I', read_va(elf, raw, address, 4))[0]
        sync_slot = (object_word(0x71f2b4) + 0x71f29c + object_word(0x71f2b8)) & 0xffffffff
        if relocations.get(sync_slot) != [(23, 0)]:
            raise ValueError('User synchronization vtable slot is not source-backed relative data')
        slots = (*slots, sync_slot)
    if pthread_raw is not None:
        pthread, provider_profile = pthread_profile(elf, pthread_raw, loader_state['application_needed'])
        pthread_bias = 0x50000000
        source_sections.extend((s, pthread_bias) for s in pthread.iter_sections() if s['sh_flags'] & 2 and s['sh_type'] != 'SHT_NOBITS')
        for section in pthread.iter_sections():
            if section['sh_type'] == 'SHT_REL':
                for relocation in section.iter_relocations():
                    address = pthread_bias + relocation['r_offset']
                    relocations.setdefault(address, []).append((relocation['r_info_type'], relocation['r_info_sym']))
        for name, plt_address in (('pthread_mutex_init', 0x104828), ('pthread_cond_init', 0xfefd8)):
            function = provider_profile['functions'][name]
            entry = function['value'] & ~1
            pthread_windows.append((pthread_bias + entry, pthread_bias + entry + function['size']))
            pthread_windows.append((plt_address, plt_address + 12))
            first, second, third = struct.unpack('<3I', read_va(elf, raw, plt_address, 12))
            if first & 0xfffff000 != 0xe28fc000 or second & 0xfffff000 != 0xe28cc000 or third & 0xfffff000 not in (0xe59cf000, 0xe5bcf000):
                raise ValueError('Unsupported original pthread PLT stub')
            slot = (plt_address + 8 + arm_rotated_immediate(first) + arm_rotated_immediate(second) + (third & 4095)) & 0xffffffff
            index = function['client_symbol_index']
            if relocations.get(slot) != [(22, index)]:
                raise ValueError('Pthread initializer PLT relocation mismatch')
            bindings[slot] = {'symbol': name, 'value': pthread_bias + function['value'], 'type': 22,
                              'version': function['version']}
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_THUMB)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
    mu.mem_map(OBJECT, 4096)
    mu.mem_write(OBJECT, b'\xa5' * 184)
    mu.mem_map(STACK, 16384)
    mu.mem_map(0x09000000, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    pages, source_known, initialized = set(), set(), set()
    phase = 'constructor'
    report = {'status': 'running', 'trace': [], 'writes': [], 'got_reads': [],
        'selected_load_bias': 0, 'constructed_object_storage': {'address': OBJECT, 'size': 184},
        'limitations': ['Constructed uninitialized storage, not an operator-new result or initialized captured object.',
            'Only original constructor prefixes execute; sysconf and OS/mutex services are not supplied.',
            'Load bias zero is an isolated coordinate choice; two existing relative GOT addends need no adjustment.',
            'No IPC exchange, main-process response, object completion or GUI.']}
    if libc_raw is not None:
        report.update(original_sysconf=True, bindings=bindings,
                      produced_loader_field={'address': field, 'bytes': produced_bytes.hex(), 'writes': writes},
                      loader_field_reads=[])
        report['limitations'] = ['Original loader producer uses declared AT_PAGESZ and process-entry assumptions, not camera reset state.',
            'Constructed uninitialized object storage; operator new is not executed.',
            'Explicit isolated libc/loader symbol bindings; only the produced loader field is supplied.',
            'No completed client object, pthread initialization, IPC/mutex response or GUI.']
    if pthread_raw is not None:
        report.update(pthread_provider=provider_profile, initializer_calls=[])
        report['limitations'] = ['Original loader and selected matching pthread/libc providers in isolated mappings.',
            'Constructed object storage; operator new and complete runtime symbol search are not executed.',
            'Original object initialization may complete, but no GRM callback lock, IPC, mapping, camera boot or GUI is supplied.']

    def stop(reason, **details):
        report.update(status=reason, boundary={'pc': mu.reg_read(arm.UC_ARM_REG_PC), **details})
        mu.emu_stop()

    def map_page(address):
        page = address & ~4095
        if page in pages:
            return
        pieces = []
        for section, load_bias in source_sections:
            section_start = load_bias + section['sh_addr']
            begin = max(page, section_start)
            end = min(page + 4096, section_start + section['sh_size'])
            if begin < end:
                pieces.append((begin, section.data()[begin - section_start:end - section_start]))
        if libc_raw is not None and page <= field < page + 4096:
            pieces.append((field, produced_bytes))
        if not pieces:
            raise ValueError('No source-backed bytes at requested page')
        covered = set()
        for begin, data in pieces:
            addresses = set(range(begin, begin + len(data)))
            if covered & addresses:
                raise ValueError('Ambiguous overlapping source sections')
            covered.update(addresses)
        mu.mem_map(page, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
        for begin, data in pieces:
            mu.mem_write(begin, data)
        for slot, binding in bindings.items():
            if page <= slot < page + 4096:
                if not all(address in covered for address in range(slot, slot + 4)):
                    raise ValueError('Symbol binding escapes source-backed slot')
                mu.mem_write(slot, struct.pack('<I', binding['value']))
        source_known.update(covered)
        pages.add(page)

    def code(uc, address, size, _):
        if pthread_raw is not None:
            for name, function in provider_profile['functions'].items():
                if address == pthread_bias + (function['value'] & ~1):
                    report['initializer_calls'].append({'symbol': name, 'pc': address,
                        'object_address': uc.reg_read(arm.UC_ARM_REG_R0), 'attributes': uc.reg_read(arm.UC_ARM_REG_R1),
                        'return_pc': uc.reg_read(arm.UC_ARM_REG_LR) & ~1})
            for call in report['initializer_calls']:
                if address == call['return_pc']:
                    call['result'] = uc.reg_read(arm.UC_ARM_REG_R0)
        if libc_raw is not None and address == 0x71f92c:
            report['sysconf_return'] = uc.reg_read(arm.UC_ARM_REG_R0)
        if address == 0x09000000:
            stop('isolated_constructor_return' if phase == 'constructor' else 'isolated_lookup_initializer_return',
                 return_register=uc.reg_read(arm.UC_ARM_REG_R0))
        elif phase == 'lookup-init' and address == 0x720740:
            stop('trace_message_allocation_call_boundary', call_target=0x1030a0,
                 arguments=[uc.reg_read(r) for r in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2, arm.UC_ARM_REG_R3)])
        elif address == 0x71f928 and libc_raw is None:
            stop('sysconf_call_boundary', selector=uc.reg_read(arm.UC_ARM_REG_R0), call_target=0x102f84)
        elif address == 0x71f2a2 and libc_raw is not None and pthread_raw is None:
            stop('pthread_mutex_init_call_boundary', object_address=uc.reg_read(arm.UC_ARM_REG_R0),
                 attributes=uc.reg_read(arm.UC_ARM_REG_R1), call_target=0x104828)
        elif not any(a <= address and address + size <= b for a, b in
                     ([(0x71fbf4, 0x71fc50 if pthread_raw is not None else 0x71fc2a), (0x71f910, 0x71f946)] +
                      (libc_windows + [(0x102f84, 0x102f90), (0x71f28c, 0x71f2b4 if pthread_raw is not None else 0x71f2a6)] if libc_raw is not None else []) + pthread_windows +
                      ([(0x71fc64, 0x71fccc), (0x720800, 0x720824), (0x720724, 0x720744)] if phase == 'lookup-init' else []))):
            stop('unsupported_control_flow', address=address)
        else:
            report['trace'].append({'pc': address, 'bytes': bytes(uc.mem_read(address, size)).hex()})

    def read(uc, access, address, size, value, _):
        span = range(address, address + size)
        if STACK <= address and address + size <= STACK + 16384:
            return
        if OBJECT <= address and address + size <= OBJECT + 184:
            if not all(a in initialized for a in span):
                stop('uninitialized_object_read', address=address, size=size)
            return
        if not all(a in source_known for a in span):
            stop('unsupplied_source_read', address=address, size=size)
            return
        if libc_raw is not None and address < field + 4 and field < address + size:
            report['loader_field_reads'].append({'address': address, 'size': size,
                'bytes': bytes(uc.mem_read(address, size)).hex()})
        affected = [slot for slot in relocations if address < slot + 4 and slot < address + size]
        if any(slot not in slots and slot not in bindings for slot in affected):
            stop('unsupported_relocated_read', address=address, size=size)
        elif affected:
            report['got_reads'].append({'address': address, 'size': size,
                'value': int.from_bytes(uc.mem_read(address, size), 'little'),
                'relocation_type': relocations[affected[0]][0][0]})

    def write(uc, access, address, size, value, _):
        if STACK <= address and address + size <= STACK + 16384:
            return
        if OBJECT <= address and address + size <= OBJECT + 184:
            initialized.update(range(address, address + size))
            report['writes'].append({'pc': uc.reg_read(arm.UC_ARM_REG_PC), 'offset': address - OBJECT, 'size': size, 'value': value})
        else:
            stop('unsupported_write', address=address, size=size)

    def invalid(uc, access, address, size, value, _):
        if access not in (unicorn.UC_MEM_READ_UNMAPPED, unicorn.UC_MEM_FETCH_UNMAPPED):
            stop('memory_boundary', address=address, size=size)
            return False
        try:
            for page in range(address & ~4095, ((address + size - 1) & ~4095) + 1, 4096):
                map_page(page)
            return True
        except ValueError as error:
            stop('unsupplied_source_memory', address=address, error=str(error))
            return False

    mu.hook_add(unicorn.UC_HOOK_CODE, code)
    mu.hook_add(unicorn.UC_HOOK_MEM_READ, read)
    mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, write)
    mu.hook_add(unicorn.UC_HOOK_MEM_INVALID, invalid)
    mu.reg_write(arm.UC_ARM_REG_CPSR, 0x30)
    mu.reg_write(arm.UC_ARM_REG_SP, STACK + 0x3000)
    mu.reg_write(arm.UC_ARM_REG_R0, OBJECT)
    mu.reg_write(arm.UC_ARM_REG_LR, 0x09000001)
    try:
        mu.emu_start(0x71fbf5, 0, count=1000, timeout=100000)
    except unicorn.UcError as error:
        if report['status'] == 'running':
            report.update(status='execution_fault', error=str(error))
    if report['status'] == 'running':
        report['status'] = 'timeout' if mu.query(unicorn.UC_QUERY_TIMEOUT) else 'instruction_limit'
    if lookup_reply is not None and report['status'] == 'isolated_constructor_return':
        if plt_symbols(elf).get(0x1030a0) != 'osal_valloc_msg_wait':
            raise ValueError('Original trace allocation PLT target changed')
        name_offset = raw.find(b'gl_common\0')
        name_address = file_to_va(elf, name_offset)
        if name_offset < 0 or name_address is None or read_va(elf, raw, name_address, 10) != b'gl_common\0':
            raise ValueError('Original lookup name not source-backed')
        report['constructor_phase'] = {'status': report['status'], 'boundary': report['boundary'],
            'instructions': len(report['trace']), 'stores': len(report['writes']), 'known_object_bytes': len(initialized)}
        report['lookup_initializer_input'] = {'reply': lookup_reply, 'name_address': name_address,
            'framing': 'Direct original function call with constructed ABI frame, not client IPC execution'}
        phase = 'lookup-init'
        report['status'] = 'running'
        mu.reg_write(arm.UC_ARM_REG_SP, STACK + 0x3000)
        mu.mem_write(STACK + 0x3000, struct.pack('<I', lookup_reply[3]))
        mu.reg_write(arm.UC_ARM_REG_R0, OBJECT)
        mu.reg_write(arm.UC_ARM_REG_R1, lookup_reply[1])
        mu.reg_write(arm.UC_ARM_REG_R2, lookup_reply[2])
        mu.reg_write(arm.UC_ARM_REG_R3, name_address)
        mu.reg_write(arm.UC_ARM_REG_LR, 0x09000001)
        try:
            mu.emu_start(0x71fc65, 0, count=1000, timeout=100000)
        except unicorn.UcError as error:
            if report['status'] == 'running':
                report.update(status='execution_fault', error=str(error))
        if report['status'] == 'running':
            report['status'] = 'timeout' if mu.query(unicorn.UC_QUERY_TIMEOUT) else 'instruction_limit'
    report['object_bytes_at_stop'] = bytes(mu.mem_read(OBJECT, 184)).hex()
    report['initialized_offsets'] = sorted(a - OBJECT for a in initialized)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', required=True)
    parser.add_argument('--loader-pagesize', action='store_true', help='Run original sysconf using a freshly executed original loader field')
    parser.add_argument('--pthread-initializers', action='store_true', help='Execute selected version-matched original pthread initializers')
    parser.add_argument('--lookup-initialize', action='store_true', help='Direct original initializer call with a fresh original GRM lookup result')
    args = parser.parse_args()
    if args.pthread_initializers and not args.loader_pagesize:
        parser.error('--pthread-initializers requires --loader-pagesize')
    if args.lookup_initialize and not args.pthread_initializers:
        parser.error('--lookup-initialize requires --pthread-initializers')
    output = (PROJECT_ROOT / args.report_dir).resolve()
    if not output.is_relative_to(PROJECT_ROOT / 'artifacts'):
        parser.error('Output must remain under artifacts')
    output.mkdir(parents=True, exist_ok=False)
    digest = next(r['sha256'] for r in json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text())['inputs'] if r['path'] == CLIENT)
    raw = checked_input(PROJECT_ROOT, CLIENT, digest)
    if plt_symbols(ELFFile(io.BytesIO(raw))).get(0x102f84) != 'sysconf':
        raise ValueError('Constructor call target is not the original sysconf PLT entry')
    if args.loader_pagesize and plt_symbols(ELFFile(io.BytesIO(raw))).get(0x104828) != 'pthread_mutex_init':
        raise ValueError('Synchronization call target is not original pthread_mutex_init')
    if args.loader_pagesize:
        from tools.research.loader_pagesize_trace import produce
        state = produce()
        libc_digest = next(r['sha256'] for r in json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text())['inputs'] if r['path'] == LIBC)
        libc_raw = checked_input(PROJECT_ROOT, LIBC, libc_digest)
        pthread_raw, pthread_digest = None, None
        if args.pthread_initializers:
            pthread_digest = next(r['sha256'] for r in json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text())['inputs'] if r['path'] == PTHREAD)
            pthread_raw = checked_input(PROJECT_ROOT, PTHREAD, pthread_digest)
        lookup_result = None
        if args.lookup_initialize:
            from tools.research.wbi_grm_consumer import main as lookup
            lookup_result = lookup(['--report-dir', str((output / 'lookup-producer').relative_to(PROJECT_ROOT))])
            if lookup_result['status'] != 'isolated_lookup_return':
                raise ValueError('Original lookup producer did not return')
        report = execute(raw, libc_raw=libc_raw, loader_state=state, pthread_raw=pthread_raw,
                         lookup_reply=lookup_result['reply'] if lookup_result else None)
        checked_input(PROJECT_ROOT, LIBC, libc_digest)
        report['additional_inputs'] = {**state['inputs'], LIBC: libc_digest}
        if lookup_result:
            report['additional_inputs'].update(lookup_result['inputs'])
        if pthread_raw is not None:
            checked_input(PROJECT_ROOT, PTHREAD, pthread_digest)
            report['additional_inputs'][PTHREAD] = pthread_digest
        (output / 'loader-producer.json').write_text(json.dumps(state, indent=2))
    else:
        report = execute(raw)
    report['input'] = {'path': CLIENT, 'sha256': digest}
    checked_input(PROJECT_ROOT, CLIENT, digest)
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    print(output, report['status'], len(report['trace']), len(report['writes']))


if __name__ == '__main__':
    main()
