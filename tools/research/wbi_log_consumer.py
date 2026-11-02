"""Original logging lookup against selected verified package WBI state."""
import io
import json
import struct

import unicorn
from unicorn import arm_const as arm
from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input
from tools.research.wbi_memory import IMAGE
from tools.research.wbi_logging_trace import PackageMemory, STATE_PHYSICAL, cached_physical
from tools.research.mount_evidence import symbol
from tools.research.storage_trace import module_relocations

MODULE = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/osal_ulogio.ko'
CODE, STACK, REQUEST, RETURN = 0x10000000, 0x08000000, 0x08100000, 0x09000000


def main():
    inputs = json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text(encoding='utf-8'))['inputs']
    hashes = {r['path']: r['sha256'] for r in inputs}
    raw = checked_input(PROJECT_ROOT, MODULE, hashes[MODULE])
    memory = PackageMemory(checked_input(PROJECT_ROOT, IMAGE, hashes[IMAGE]))
    elf = ELFFile(io.BytesIO(raw))
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
    known, placements = [], {'.text': CODE, '.bss': STATE_PHYSICAL + 0x60000000}

    def mapped(address, data, perms):
        mu.mem_map(address, (len(data) + 4095) & ~4095, perms)
        mu.mem_write(address, data)
        known.append((address, address + len(data)))

    other = 0x11000000
    for section in elf.iter_sections():
        if section.name == '.text' or section.name.startswith('.rodata'):
            if section.name != '.text':
                placements[section.name] = other
                other += (section['sh_size'] + 0xffff) & ~0xffff
            mapped(placements[section.name], section.data(), unicorn.UC_PROT_READ | (unicorn.UC_PROT_EXEC if section.name == '.text' else 0))
    bss_page = placements['.bss'] & ~4095
    mapped(bss_page, memory.read(bss_page - 0x60000000, 4096), unicorn.UC_PROT_READ)
    map_size, map_pointer = struct.unpack('<2I', memory.read(STATE_PHYSICAL + 0x274, 8))
    if not 0 < map_size <= 4096:
        raise ValueError('Unsupported captured lookup-table size')
    table_page = map_pointer & ~4095
    table_length = (map_pointer - table_page + map_size * 8 + 4095) & ~4095
    mapped(table_page, memory.read(cached_physical(table_page), table_length), unicorn.UC_PROT_READ)
    root_pointer = struct.unpack('<I', memory.read(STATE_PHYSICAL + 28, 4))[0]
    root = struct.unpack('<15I', memory.read(cached_physical(root_pointer), 60))
    root_size = root[14] + 60
    if root_pointer % 4096 or root_size % 4096 or root_size > 8 * 1024 * 1024:
        raise ValueError('Unsupported captured logging backing range')
    mu.mem_map(root_pointer, root_size, unicorn.UC_PROT_READ)
    for offset in range(0, root_size, 1024 * 1024):
        data = memory.read(cached_physical(root_pointer) + offset, min(1024 * 1024, root_size - offset))
        mu.mem_write(root_pointer + offset, data)
    known.append((root_pointer, root_pointer + root_size))
    unresolved, imports = [], {}
    for (index, offset), relocation in module_relocations(elf).items():
        source = elf.get_section(index)
        if source.name not in placements or source.name == '.bss':
            continue
        address = placements[source.name] + offset
        target = relocation['symbol_section']
        if target not in placements:
            if relocation['type'] == 28:
                imports[address] = relocation['symbol']
            else:
                unresolved.append(address)
        elif relocation['type'] == 2:
            mu.mem_write(address, struct.pack('<I', placements[target] + relocation['target_offset']))
        elif relocation['type'] == 28:
            word = struct.unpack('<I', mu.mem_read(address, 4))[0]
            if word >> 24 != 0xeb:
                raise ValueError('Unsupported call instruction')
            addend = (word & 0xffffff) << 2
            if addend & 0x2000000:
                addend -= 0x4000000
            delta = placements[target] + relocation['symbol_value'] + addend - address
            if delta % 4 or not -(1 << 25) <= delta < 1 << 25:
                raise ValueError('Unrepresentable original call relocation')
            mu.mem_write(address, struct.pack('<I', 0xeb000000 | ((delta >> 2) & 0xffffff)))
        else:
            raise ValueError('Unsupported selected relocation')
    mapped(STACK, bytes(16384), unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
    packet = struct.pack('<HHIII', 0xb, 0x61, 0, 0xa5a5a5a5, 0xa5a5a5a5)
    mapped(REQUEST, packet, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
    mapped(RETURN, bytes(4), unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    allowed = []
    for name in ('ulogio_get_logaddr', 'ulogio_lbm_lookup_table_find'):
        function = symbol(elf, name)
        allowed.append((CODE + function['st_value'], CODE + function['st_value'] + function['st_size']))
    report = {'inputs': {IMAGE: hashes[IMAGE], MODULE: hashes[MODULE]}, 'status': 'running',
        'trace': [], 'writes': [], 'request_before': packet.hex(), 'lookup_map_size': map_size,
        'limitations': ['Original functions executed against explicitly selected packaged WBI data.',
            'No kernel boot, IPC registration, clock response or current-camera-state validation.',
            'Snapshot field/layout compatibility is not complete loaded-module identity validation.']}

    def stop(reason, **details):
        report.update(status=reason, boundary={'pc': mu.reg_read(arm.UC_ARM_REG_PC), **details})
        mu.emu_stop()

    def code(uc, address, size, _):
        if address == RETURN:
            stop('isolated_lookup_return')
        elif address in imports:
            stop('unsupported_import', symbol=imports[address])
        elif not any(a <= address < b for a, b in allowed):
            stop('unsupported_control_flow', address=address)
        else:
            report['trace'].append({'offset': address - CODE, 'bytes': bytes(uc.mem_read(address, size)).hex()})

    def read(uc, access, address, size, value, _):
        if not any(a <= address and address + size <= b for a, b in known) or any(address < a + 4 and a < address + size for a in unresolved):
            stop('unsupported_read', address=address, size=size)

    def write(uc, access, address, size, value, _):
        if STACK <= address and address + size <= STACK + 16384:
            return
        if size == 4 and address in (REQUEST + 8, REQUEST + 12):
            report['writes'].append({'offset': address - REQUEST, 'value': value})
        else:
            stop('unsupported_write', address=address, size=size)

    def invalid(uc, access, address, size, value, _):
        stop('memory_boundary', address=address, size=size, access=access)
        return False

    mu.hook_add(unicorn.UC_HOOK_CODE, code)
    mu.hook_add(unicorn.UC_HOOK_MEM_READ, read)
    mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, write)
    mu.hook_add(unicorn.UC_HOOK_MEM_INVALID, invalid)
    mu.reg_write(arm.UC_ARM_REG_CPSR, 0x10)
    mu.reg_write(arm.UC_ARM_REG_SP, STACK + 0x3000)
    mu.reg_write(arm.UC_ARM_REG_R0, REQUEST)
    mu.reg_write(arm.UC_ARM_REG_LR, RETURN)
    try:
        mu.emu_start(allowed[0][0], 0, count=2000, timeout=1000000)
    except unicorn.UcError as error:
        if report['status'] == 'running':
            report.update(status='execution_fault', error=str(error))
    if report['status'] == 'running':
        report['status'] = 'timeout' if mu.query(unicorn.UC_QUERY_TIMEOUT) else 'instruction_limit'
    result = bytes(mu.mem_read(REQUEST, 16))
    report['request_after'] = result.hex()
    report['returned_size'], report['returned_physical'] = struct.unpack_from('<II', result, 8)
    output = PROJECT_ROOT / 'artifacts/execution/wbi-log-consumer.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output, report['status'], hex(report['returned_physical']), hex(report['returned_size']), len(report['trace']))


if __name__ == '__main__':
    main()
