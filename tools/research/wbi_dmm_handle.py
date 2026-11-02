"""Locate captured DMM code and execute original unit-to-handle search."""
import argparse
import io
import json
import struct

import unicorn
from unicorn import arm_const as arm
from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input
from tools.research.wbi_memory import IMAGE, decode_section
from tools.research.wbi_logging_trace import PackageMemory
from tools.research.wbi_pagewalk import translate, read_virtual
from tools.research.dmm_config_trace import MODULE
from tools.research.storage_trace import module_relocations
from tools.research.mount_evidence import symbol
from tools.research.dmm_runtime_trace import KERNEL, KERNEL_BASE

ROOT, STACK, RETURN = 0x104000, 0x08000000, 0x09000000


def mutation_allowed(address, size, ranges):
    """Permit a complete ARM32 access only inside one explicit interval."""
    return (0 <= address < 1 << 32 and 0 < size <= 8 and address + size <= 1 << 32
            and any(0 <= begin <= address and address + size <= end <= 1 << 32
                    for begin, end in ranges))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', required=True)
    parser.add_argument('--operation', choices=('search', 'alloc'), default='search')
    parser.add_argument('--inner-extent', action='store_true', help='Permit the E0049 inner extent prefix and its bounded scratch state')
    args = parser.parse_args()
    if args.inner_extent and args.operation != 'alloc':
        parser.error('--inner-extent requires --operation alloc')
    output = (PROJECT_ROOT / args.report_dir).resolve()
    if not output.is_relative_to(PROJECT_ROOT / 'artifacts'):
        parser.error('Output must remain under artifacts')
    output.mkdir(parents=True, exist_ok=False)
    hashes = {r['path']: r['sha256'] for r in json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text())['inputs']}
    raw = checked_input(PROJECT_ROOT, MODULE, hashes[MODULE])
    memory = PackageMemory(checked_input(PROJECT_ROOT, IMAGE, hashes[IMAGE]))
    kernel = checked_input(PROJECT_ROOT, KERNEL, hashes[KERNEL]) if args.operation == 'alloc' else None
    elf = ELFFile(io.BytesIO(raw))
    text = elf.get_section_by_name('.text').data()
    index = next(i for i, s in enumerate(elf.iter_sections()) if s.name == '.text')
    relocations = module_relocations(elf)
    make = symbol(elf, 'dmm_unit_ctrl_MakeHandle')
    search = symbol(elf, 'dmm_unit_ctrl_SearchUnitTypeToHandle')
    needle = text[make['st_value']:make['st_value'] + make['st_size']]
    if any(i == index and make['st_value'] <= o < make['st_value'] + make['st_size'] for i, o in relocations):
        raise ValueError('Locator function has relocations')
    hits = []
    for section in memory.sections:
        data = decode_section(memory.raw, section)[0]
        start = 0
        while (offset := data.find(needle, start)) >= 0:
            hits.append(section['physical'] + offset)
            start = offset + 1
    if len(hits) != 1:
        raise ValueError('Captured function is missing/ambiguous')
    aliases = []
    for page in range(0x5f000000, 0x60000000, 4096):
        try:
            physical, _ = translate(memory, ROOT, page)
        except ValueError:
            continue
        if physical == hits[0] & ~4095:
            aliases.append(page + (hits[0] & 4095))
    if len(aliases) != 1:
        raise ValueError('Captured VMALLOC code alias missing/ambiguous')
    base = aliases[0] - make['st_value']
    captured = read_virtual(memory, ROOT, base, len(text))
    relocated = {o for (i, o) in relocations if i == index}
    verified = 0
    for offset in range(0, len(text), 4):
        if offset not in relocated:
            if captured[offset:offset + 4] != text[offset:offset + 4]:
                raise ValueError('Captured DMM text mismatch at ' + hex(offset))
            verified += len(text[offset:offset + 4])
    table_literals = [o for (i, o), r in relocations.items() if i == index
        and search['st_value'] <= o < search['st_value'] + search['st_size']
        and r['type'] == 2 and r['symbol_section'] == '.bss' and r['target_offset'] == 617912]
    if len(table_literals) != 1:
        raise ValueError('Unit-table literal is ambiguous')
    table = struct.unpack_from('<I', captured, table_literals[0])[0]
    matches = []
    for n in range(0x580):
        data = read_virtual(memory, ROOT, table + n * 336, 16)
        if struct.unpack_from('<I', data)[0] == 0x280:
            record = read_virtual(memory, ROOT, table + n * 336, 336)
            item = {'index': n, 'address': table + n * 336, 'prefix_hex': data.hex(),
                    'record_hex': record.hex()}
            extent = struct.unpack_from('<I', record, 16)[0]
            if extent:
                extent_bytes = read_virtual(memory, ROOT, extent, 48)
                item.update(first_extent=extent, first_extent_words=list(struct.unpack('<12I', extent_bytes)))
            matches.append(item)
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
    mu.mem_map(STACK, 16384)
    mu.mem_map(RETURN, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    allowed = [(base + s['st_value'], base + s['st_value'] + s['st_size']) for s in (search, make)]
    mutation_ranges = []
    imports = {}
    if args.operation == 'alloc':
        functions = ('dmm_unit_ctrl_Alloc', 'dmm_unit_tbl_GetUnitTbl', 'dmm_unit_ctrl_MakeHandle',
                     'dmm_ext_ctrl_AllocExtent', 'dmm_ext_ctrl_GetCurrentAllocRule')
        allowed = [(base + symbol(elf, n)['st_value'], base + symbol(elf, n)['st_value'] + symbol(elf, n)['st_size']) for n in functions]
        # Exact REA entries18588/18600 minus this module's observed .text base1003c.
        allowed.extend(((base + 0x854c, base + 0x854c + 88), (base + 0x85c4, base + 0x85c4 + 40)))
        queue_tail, queue_head = struct.unpack('<2I', read_virtual(memory, ROOT, table - 0xb18, 8))
        if queue_head > 0x580 or queue_tail > 0x580:
            raise ValueError('Captured free-record queue indices exceed bounds')
        free_index = struct.unpack('<H', read_virtual(memory, ROOT, table - 0xb10 + queue_head * 2, 2))[0]
        if free_index >= 0x580:
            raise ValueError('Captured free-record index exceeds bounds')
        selected_record = table + free_index * 336
        mutation_ranges = [(table - 0xb14, table - 0xb10), (table - 12, table - 4),
                           (selected_record, selected_record + 336)]
        if args.inner_extent:
            allowed.append((base + 0xa658, base + 0xa658 + 1724))
            allowed.extend(((base + 0x9e9c, base + 0x9e9c + 152),
                            (base + 0xa23c, base + 0xa23c + 40),
                            (base + 0x84d8, base + 0x84d8 + 112)))
            for name in ('dmm_ext_tbl_GetExtentTbl', 'dmm_ext_tbl_GetExtentCount',
                         'dmm_ext_tbl_GetExtentTblIndex', 'dmm_ext_tbl_GetExtentTblNameIndex'):
                fn = symbol(elf, name)
                allowed.append((base + fn['st_value'], base + fn['st_value'] + fn['st_size']))
            # Exact original literals at .text+ad14/ad18/ad1c; the first
            # points to the scratch region whose depth word is at +5e0.
            scratch_base, error_word, bitset = struct.unpack('<3I', captured[0xad14:0xad20])
            mutation_ranges.extend(((scratch_base + 0x5e0, scratch_base + 0x5e4),
                                    (error_word, error_word + 2), (bitset, bitset + 256)))
            # Original failure cleanup puts the consumed record at the old
            # queue tail and updates only that tail word/count.
            queue_slot = table - 0xb10 + queue_tail * 2
            mutation_ranges.extend(((table - 0xb18, table - 0xb14), (queue_slot, queue_slot + 2)))
        alloc = symbol(elf, functions[0])
        for (i, offset), relocation in relocations.items():
            if i != index or relocation['type'] != 28 or relocation['symbol_section'] != 'SHN_UNDEF':
                continue
            imports[base + offset] = relocation['symbol']
            permitted_fill = (relocation['symbol'] == 'memset' and alloc['st_value'] <= offset < alloc['st_value'] + alloc['st_size'])
            permitted_fill |= (args.inner_extent and relocation['symbol'] in ('memset', '__memzero') and 0xa658 <= offset < 0xa658 + 1724)
            if permitted_fill:
                branch = struct.unpack_from('<I', captured, offset)[0]
                if branch >> 24 != 0xeb:
                    raise ValueError('Unsupported captured memset branch')
                delta = (branch & 0xffffff) << 2
                if delta & 0x2000000:
                    delta -= 0x4000000
                target = base + offset + 8 + delta
                if not KERNEL_BASE <= target < KERNEL_BASE + len(kernel) - 256:
                    raise ValueError('Captured memset is outside preserved kernel')
                if read_virtual(memory, ROOT, target, 256) != kernel[target - KERNEL_BASE:target - KERNEL_BASE + 256]:
                    raise ValueError('Captured memset differs from preserved kernel')
                allowed.append((target, target + 256))
                del imports[base + offset]
        mu.mem_map(0x08100000, 4096)
        mu.mem_write(0x08100000, b'\xa5\xa5')
    report = {'inputs': {p: hashes[p] for p in (IMAGE, MODULE)}, 'selected_root': ROOT,
        'locator_physical': hits[0], 'module_base': base, 'verified_nonrelocated_bytes': verified,
        'relocation_words': len(relocated), 'unit_table': table, 'unit_matches': matches,
        'status': 'running', 'trace': [], 'page_walks': [],
        'limitations': ['Explicit selected captured root, not active MMU discovery or current camera state.',
            'Constructed stack and input unit0x280; only original search and handle construction execute.',
            'No allocation, clock response, transport, ownership transfer or GUI.']}
    pages = set()
    if args.operation == 'alloc':
        report.update(operation='alloc', inputs={p: hashes[p] for p in (IMAGE, MODULE, KERNEL)},
                      free_queue_head=queue_head, free_queue_tail=queue_tail, selected_free_index=free_index,
                      mutation_ranges=mutation_ranges, writes=[], record_before=read_virtual(memory, ROOT, selected_record, 336).hex())
        if args.inner_extent:
            report['inner_extent'] = True
        report['limitations'] = ['Selected captured root and disposable snapshot copy; not current camera state.',
            'Direct Alloc(0x280,1) call with explicit queue/record mutation ranges, no IPC or access-info handler.',
            'Unknown control flow, imports, writes and hardware reads stop; no allocation success inferred from a boundary.']
        for begin, end in mutation_ranges:
            for page in range(begin & ~4095, ((end - 1) & ~4095) + 1, 4096):
                if page not in pages:
                    data = read_virtual(memory, ROOT, page, 4096)
                    _, walk = translate(memory, ROOT, page)
                    mu.mem_map(page, 4096, unicorn.UC_PROT_ALL)
                    mu.mem_write(page, data)
                    pages.add(page)
                    report['page_walks'].append(walk)

    def stop(reason, **details):
        report.update(status=reason, boundary={'pc': mu.reg_read(arm.UC_ARM_REG_PC), **details})
        mu.emu_stop()

    def code(uc, address, size, _):
        if args.operation == 'alloc':
            if args.inner_extent and address == base + 0xa658:
                report.setdefault('inner_calls', []).append({'arguments': [uc.reg_read(r) for r in
                    (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2, arm.UC_ARM_REG_R3)],
                    'return_pc': uc.reg_read(arm.UC_ARM_REG_LR)})
            if address == base + make['st_value']:
                report['handle_construction'] = {'index': uc.reg_read(arm.UC_ARM_REG_R0),
                    'generation': uc.reg_read(arm.UC_ARM_REG_R1), 'return_pc': uc.reg_read(arm.UC_ARM_REG_LR)}
            observed = report.get('handle_construction')
            if observed and address == observed['return_pc']:
                observed['result'] = uc.reg_read(arm.UC_ARM_REG_R0)
        if address == RETURN:
            stop('isolated_handle_search_return' if args.operation == 'search' else 'isolated_alloc_return')
        elif address in imports:
            stop('unsupported_import', symbol=imports[address], arguments=[uc.reg_read(r) for r in
                 (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2, arm.UC_ARM_REG_R3)])
        elif not any(a <= address and address + size <= b for a, b in allowed):
            stop('unsupported_control_flow', address=address)
        else:
            report['trace'].append({'pc': address, 'bytes': bytes(uc.mem_read(address, size)).hex()})

    def write(uc, access, address, size, value, _):
        if STACK <= address <= address + size <= STACK + 16384:
            return
        if args.operation == 'alloc' and ((address == 0x08100000 and size == 2) or
                mutation_allowed(address, size, mutation_ranges)):
            report['writes'].append({'pc': uc.reg_read(arm.UC_ARM_REG_PC), 'address': address,
                                     'size': size, 'value': value, 'before': bytes(uc.mem_read(address, size)).hex()})
        else:
            stop('unsupported_write', address=address, size=size, value=value)

    def read(uc, access, address, size, value, _):
        if args.operation == 'alloc' and address & ~4095 == 0x08100000:
            if not (0x08100000 <= address and address + size <= 0x08100002):
                stop('constructed_output_padding_read', address=address, size=size)

    def invalid(uc, access, address, size, value, _):
        if access not in (unicorn.UC_MEM_READ_UNMAPPED, unicorn.UC_MEM_FETCH_UNMAPPED):
            stop('unsupported_memory_access', address=address)
            return False
        try:
            for page in range(address & ~4095, ((address + size - 1) & ~4095) + 1, 4096):
                if page not in pages:
                    data = read_virtual(memory, ROOT, page, 4096)
                    _, walk = translate(memory, ROOT, page)
                    uc.mem_map(page, 4096, unicorn.UC_PROT_ALL if args.operation == 'alloc' else unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
                    uc.mem_write(page, data)
                    pages.add(page)
                    report['page_walks'].append(walk)
            return True
        except ValueError as error:
            stop('unsupplied_memory', address=address, error=str(error))
            return False

    mu.hook_add(unicorn.UC_HOOK_CODE, code)
    mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, write)
    mu.hook_add(unicorn.UC_HOOK_MEM_READ, read)
    mu.hook_add(unicorn.UC_HOOK_MEM_INVALID, invalid)
    mu.reg_write(arm.UC_ARM_REG_CPSR, 0x10)
    mu.reg_write(arm.UC_ARM_REG_SP, STACK + 0x3000)
    mu.reg_write(arm.UC_ARM_REG_LR, RETURN)
    mu.reg_write(arm.UC_ARM_REG_R0, 0x280)
    if args.operation == 'alloc':
        mu.reg_write(arm.UC_ARM_REG_R1, 1)
        mu.reg_write(arm.UC_ARM_REG_R2, 0x08100000)
    try:
        mu.emu_start(allowed[0][0], 0, count=50000, timeout=1000000)
    except unicorn.UcError as error:
        if report['status'] == 'running':
            report.update(status='execution_fault', error=str(error))
    if report['status'] == 'running':
        report['status'] = 'timeout' if mu.query(unicorn.UC_QUERY_TIMEOUT) else 'instruction_limit'
    report['returned_handle'] = mu.reg_read(arm.UC_ARM_REG_R0)
    if args.operation == 'alloc':
        report['r0_at_stop'] = report.pop('returned_handle')
        report['output_halfword_at_stop'] = struct.unpack('<H', mu.mem_read(0x08100000, 2))[0]
        if report['status'] == 'isolated_alloc_return':
            value = report['r0_at_stop']
            report['allocation_status_signed'] = value if value < 0x80000000 else value - (1 << 32)
        if args.inner_extent:
            report['scratch_and_queue_at_stop'] = [
                {'address': begin, 'bytes': bytes(mu.mem_read(begin, end - begin)).hex()}
                for begin, end in mutation_ranges]
        if selected_record & ~4095 in pages:
            report['record_at_stop'] = bytes(mu.mem_read(selected_record, 336)).hex()
    for p in ((IMAGE, MODULE, KERNEL) if args.operation == 'alloc' else (IMAGE, MODULE)):
        checked_input(PROJECT_ROOT, p, hashes[p])
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    print(output, report['status'], len(report['trace']), hex(report.get('returned_handle', report.get('r0_at_stop'))),
          'matching records', [m['index'] for m in matches])


if __name__ == '__main__':
    main()
