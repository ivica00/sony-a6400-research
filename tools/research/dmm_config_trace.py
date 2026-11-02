"""Bounded original DMM table initialization over an identified package config.

Constructed module/stack mappings; only byte-fill and unsigned division
imports are modeled. This is not a kernel module loader or a running DMM service.
"""
from collections import Counter, deque
import io
import json
import struct

import unicorn
from unicorn import arm_const as arm
from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.mount_evidence import checked_input, symbol
from tools.research.storage_trace import module_relocations
from src.a6400.execution.guest_memory import accessible

MODULE = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/dmm.ko'
CONFIG = 'firmware/extracted_a6400/firmware.tar_unpacked/0800_appli/setting/DmmConfig.bin'
CODE, BSS, CONFIG_BASE, STACK, RETURN = 0x01000000, 0x03000000, 0x04000000, 0x08000000, 0x09000000
SCRATCH = 0x08100000


class DmmConfigProbe:
    def __init__(self, raw, config):
        self.elf = ELFFile(io.BytesIO(raw))
        if (self.elf.elfclass, self.elf.little_endian, self.elf['e_machine'], self.elf['e_type']) != (32, True, 'EM_ARM', 'ET_REL'):
            raise ValueError('Expected ELF32 ARM module')
        self.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
        self.placements = {'.text': CODE, '.bss': BSS}
        self.imports = {}
        self.unresolved = []
        self.config = bytes(config)
        self.config_reads = []
        self.reader_entry = CODE + symbol(self.elf, 'dmm_config_GetConfigData')['st_value']
        self.relocations = module_relocations(self.elf)
        other = 0x02000000
        for section in self.elf.iter_sections():
            if not section['sh_flags'] & 2 or section['sh_size'] == 0:
                continue
            if section.name not in self.placements:
                self.placements[section.name] = other
                other += (section['sh_size'] + 0xffff) & ~0xffff
            perms = unicorn.UC_PROT_READ | (unicorn.UC_PROT_EXEC if section['sh_flags'] & 4 else 0)
            if section['sh_flags'] & 1:
                perms |= unicorn.UC_PROT_WRITE
            self.mu.mem_map(self.placements[section.name], (section['sh_size'] + 4095) & ~4095, perms)
            if section['sh_type'] != 'SHT_NOBITS':
                self.mu.mem_write(self.placements[section.name], section.data())
        for (index, offset), relocation in self.relocations.items():
            section = self.elf.get_section(index)
            if section.name not in self.placements:
                continue
            address = self.placements[section.name] + offset
            target_section = relocation['symbol_section']
            if target_section not in self.placements:
                if relocation['type'] == 28 and section['sh_flags'] & 4:
                    self.imports[address] = relocation['symbol']
                else:
                    self.unresolved.append((address, address + 4, relocation))
                continue
            target_base = self.placements[target_section]
            if relocation['type'] == 2:
                self.mu.mem_write(address, struct.pack('<I', target_base + relocation['target_offset']))
            elif relocation['type'] == 28:
                word = struct.unpack('<I', self.mu.mem_read(address, 4))[0]
                if word >> 24 != 0xeb:
                    raise ValueError('Only unconditional ARM BL relocation is supported')
                addend = (word & 0xffffff) << 2
                if addend & 0x2000000:
                    addend -= 0x4000000
                delta = target_base + relocation['symbol_value'] + addend - address
                if delta % 4 or not -(1 << 25) <= delta < (1 << 25):
                    raise ValueError('Unrepresentable ARM call relocation')
                self.mu.mem_write(address, struct.pack('<I', (word & 0xff000000) | ((delta >> 2) & 0xffffff)))
            else:
                raise ValueError('Unsupported selected local relocation')
        self.mu.mem_map(CONFIG_BASE, max(4096, (len(config) + 4095) & ~4095), unicorn.UC_PROT_READ)
        self.mu.mem_write(CONFIG_BASE, config)
        self.mu.mem_map(STACK, 0x4000, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
        self.mu.mem_map(SCRATCH, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
        self.mu.mem_map(RETURN, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
        # Constructed addr_limit control used only by the original reader's
        # save path; this memory-backed read branch does not service host files.
        self.mu.mem_write(STACK + 0x2008, struct.pack('<I', 0xffffffff))
        self.mu.mem_write(BSS + 0x14, struct.pack('<I', CONFIG_BASE))
        self.mu.hook_add(unicorn.UC_HOOK_CODE, self._code)
        self.mu.hook_add(unicorn.UC_HOOK_MEM_READ, self._read)
        self.mu.hook_add(unicorn.UC_HOOK_MEM_INVALID, self._invalid)
        self.active = None

    def stop(self, reason, **details):
        self.active.update(status=reason, boundary={**details, 'pc': self.mu.reg_read(arm.UC_ARM_REG_PC)})
        self.mu.emu_stop()

    def _read(self, mu, access, address, size, value, data):
        if CONFIG_BASE <= address < CONFIG_BASE + max(4096, (len(self.config) + 4095) & ~4095):
            if address + size > CONFIG_BASE + len(self.config):
                self.stop('config_read_past_supplied_bytes', address=address, size=size)
                return
        for begin, end, relocation in self.unresolved:
            if address < end and begin < address + size:
                self.stop('unresolved_module_data', address=address, relocation=relocation)
                return

    def _invalid(self, mu, access, address, size, value, data):
        self.stop('memory_boundary', address=address, size=size, access=access)
        return False

    def _code(self, mu, address, size, data):
        if address == RETURN:
            self.stop('isolated_function_return')
            return
        name = self.imports.get(address)
        if name:
            r0, r1 = mu.reg_read(arm.UC_ARM_REG_R0), mu.reg_read(arm.UC_ARM_REG_R1)
            if name in ('__memzero', 'memset'):
                length = r1 if name == '__memzero' else mu.reg_read(arm.UC_ARM_REG_R2)
                value = 0 if name == '__memzero' else r1 & 255
                if length > 4 * 1024 * 1024 or not accessible(mu, r0, length, unicorn.UC_PROT_WRITE):
                    self.stop('unsupported_fill_range', address=r0, size=length)
                    return
                mu.mem_write(r0, bytes([value]) * length)
            elif name == '__aeabi_uidiv':
                if r1 == 0:
                    self.stop('division_by_zero_boundary')
                    return
                mu.reg_write(arm.UC_ARM_REG_R0, r0 // r1)
            else:
                details = {'symbol': name, 'arguments': [mu.reg_read(getattr(arm, 'UC_ARM_REG_R' + str(i))) for i in range(4)]}
                # Observe a bounded IPC request without supplying a response.
                if name == 'osal_snd_sync_direct' and accessible(mu, r1, 32, unicorn.UC_PROT_READ):
                    details['request_prefix_hex'] = bytes(mu.mem_read(r1, 32)).hex()
                self.stop('unsupported_kernel_import', **details)
                return
            self.active['helper_calls'][name] += 1
            mu.reg_write(arm.UC_ARM_REG_LR, address + 4)
            mu.reg_write(arm.UC_ARM_REG_PC, address + 4)
            return
        if address == self.reader_entry:
            if len(self.config_reads) >= 8192:
                self.stop('config_read_record_limit')
                return
            self.config_reads.append({'destination': mu.reg_read(arm.UC_ARM_REG_R0),
                                      'size': mu.reg_read(arm.UC_ARM_REG_R1),
                                      'file_offset': struct.unpack('<Q', mu.mem_read(BSS + 8, 8))[0]})
        self.active['instructions_executed'] += 1
        self.active['tail'].append({'address': address, 'bytes': bytes(mu.mem_read(address, size)).hex()})

    def call(self, name, arguments=(), budget=3000000):
        entry = symbol(self.elf, name)
        if not isinstance(entry['st_shndx'], int):
            raise ValueError('Expected a defined function')
        self.active = {'function': name, 'status': 'running', 'instructions_executed': 0,
                       'helper_calls': Counter(), 'tail': deque(maxlen=16),
                       'instruction_budget': budget, 'timeout_us': 30000000}
        self.mu.reg_write(arm.UC_ARM_REG_CPSR, 0x10)
        self.mu.reg_write(arm.UC_ARM_REG_SP, STACK + 0x3000)
        self.mu.reg_write(arm.UC_ARM_REG_LR, RETURN)
        for index, value in enumerate(arguments):
            self.mu.reg_write(getattr(arm, 'UC_ARM_REG_R' + str(index)), value)
        start = self.placements[self.elf.get_section(entry['st_shndx']).name] + entry['st_value']
        try:
            self.mu.emu_start(start, 0, count=budget, timeout=30000000)
        except unicorn.UcError as error:
            if self.active['status'] == 'running':
                self.active.update(status='execution_fault', error=str(error))
        if self.active['status'] == 'running':
            self.active['status'] = 'timeout' if self.mu.query(unicorn.UC_QUERY_TIMEOUT) else 'instruction_budget_exhausted'
        self.active['tail'] = list(self.active['tail'])
        self.active['helper_calls'] = dict(self.active['helper_calls'])
        self.active['return_value'] = self.mu.reg_read(arm.UC_ARM_REG_R0)
        self.active['config_cursor'] = struct.unpack('<Q', self.mu.mem_read(BSS + 8, 8))[0]
        return dict(self.active)

    def words(self, address, count):
        if count < 0 or count > 1024 or not accessible(self.mu, address, count * 4, unicorn.UC_PROT_READ):
            raise ValueError('Table observation exceeds mapped bytes')
        return list(struct.unpack('<' + 'I' * count, self.mu.mem_read(address, count * 4)))

    def tables(self):
        observed = {}
        for getter, label, maximum in [('dmm_ext_tbl_GetRootExtentTbl', 'root_extents', 2),
                                       ('dmm_ext_tbl_GetExtentTbl', 'extents', 1024)]:
            result = self.call(getter)
            if result['status'] != 'isolated_function_return':
                raise ValueError('Original table getter did not return')
            address = result['return_value']
            headers = []
            for index in range(maximum):
                head = self.words(address + index * 0x50, 20)
                if head[2] == 0xffffffff:
                    break
                children = []
                for child_index in range(3072):
                    words = self.words(head[0] + child_index * 20, 5)
                    if words[2] == 0xffffffff:
                        break
                    children.append(words)
                else:
                    raise ValueError('Original extent child table exceeds its observed bound')
                source = next((r['file_offset'] for r in self.config_reads
                               if r['destination'] == address + index * 0x50), None)
                headers.append({'header': head, 'children': children, 'header_file_offset': source})
            else:
                raise ValueError('Original extent headers exceed their observed bound')
            observed[label] = headers
        result = self.call('dmm_unit_tbl_GetUnitTbl')
        address = result['return_value']
        units = []
        for index in range(1024):
            unit, child = self.words(address + index * 8, 2)
            if unit == 0xffffffff:
                break
            extents = []
            for offset in range(3072):
                item = self.words(child + 4 * offset, 1)[0]
                if item == 0xffffffff:
                    break
                extents.append(item)
            else:
                raise ValueError('Original unit extent references exceed their observed bound')
            units.append({'unit': unit, 'extents': extents})
        else:
            raise ValueError('Original unit table exceeds its observed bound')
        observed['units'] = units
        return observed


def main():
    inventory = PROJECT_ROOT / 'artifacts/inventory'
    expected = {row['path']: row['sha256'] for row in json.loads((inventory / 'baseline.json').read_text(encoding='utf-8'))['inputs']}
    raw = checked_input(PROJECT_ROOT, MODULE, expected[MODULE])
    config = checked_input(PROJECT_ROOT, CONFIG, expected[CONFIG])
    probe = DmmConfigProbe(raw, config)
    results = []
    for name in ('dmm_ext_tbl_Init', 'dmm_unit_tbl_Init'):
        result = probe.call(name)
        results.append(result)
        print(name, result['status'], result['return_value'], result['config_cursor'], flush=True)
        if result['status'] != 'isolated_function_return' or result['return_value'] != 0:
            break
    report = {'inputs': {MODULE: expected[MODULE], CONFIG: expected[CONFIG]}, 'calls': results,
              'placements': probe.placements, 'limits': ['Constructed cold module memory and stack; provisional Cortex-A9.',
                 'Only defined ABS32 and ARM CALL relocations. Unresolved imports/data stop explicitly.',
                 'Only __memzero/memset byte semantics and unsigned division are serviced; no kernel or IPC execution.',
                 'The package config is an explicitly selected input, not actual camera /setting state.']}
    if all(r['status'] == 'isolated_function_return' and r['return_value'] == 0 for r in results) and len(results) == 2:
        report['tables'] = probe.tables()
        report['config_reads'] = probe.config_reads
        print('unit 0x280:', [u for u in report['tables']['units'] if u['unit'] == 0x280])
        identifiers = {item for unit in report['tables']['units'] if unit['unit'] == 0x280 for item in unit['extents']}
        report['graphics_unit_extents'] = [h for h in report['tables']['extents'] if any(c[2] in identifiers for c in h['children'])]
        print('extent IDs for unit 0x280:', sorted(identifiers))
    # Separate cold-module attempt: do not reuse parser-only state as if the
    # original DMM initializer and its prerequisite services had completed.
    initialization = DmmConfigProbe(raw, config)
    report['allocation_state_initialization'] = initialization.call('dmm_unit_ctrl_Init')
    print('allocation initialization:', report['allocation_state_initialization']['status'],
          report['allocation_state_initialization'].get('boundary'), flush=True)
    if (report['allocation_state_initialization']['status'] == 'isolated_function_return'
            and report['allocation_state_initialization']['return_value'] == 0):
        boot_count = initialization.call('dmm_ext_tbl_GetBootExtentCnt')
        report['boot_extent_count'] = boot_count
        report['boot_units'] = []
        if boot_count['status'] == 'isolated_function_return' and boot_count['return_value'] <= 32:
            for index in range(boot_count['return_value']):
                unit = initialization.call('dmm_ext_tbl_GetExtentUnitType', (index,))
                result = initialization.call('dmm_unit_ctrl_InitBootUnit', (unit['return_value'],))
                report['boot_units'].append({'index': index, 'lookup': unit, 'initialize': result})
                print('boot unit', hex(unit['return_value']), result['status'], hex(result['return_value']), flush=True)
                if result['status'] != 'isolated_function_return' or result['return_value'] != 0:
                    break
            else:
                result = initialization.call('dmm_unit_ctrl_Alloc', (0x280, 1, SCRATCH))
                report['graphics_allocation'] = result
                print('graphics allocation', result['status'], hex(result['return_value']), result.get('boundary'), flush=True)
                if result['status'] == 'isolated_function_return' and result['return_value'] == 0:
                    handle = struct.unpack('<H', initialization.mu.mem_read(SCRATCH, 2))[0]
                    report['graphics_handle'] = handle
                    opened = initialization.call('dmm_unit_ctrl_Open', (handle, 0, SCRATCH + 0x100, SCRATCH + 0x200))
                    report['graphics_open'] = opened
                    if opened['status'] == 'isolated_function_return' and opened['return_value'] == 0:
                        count = struct.unpack('<H', initialization.mu.mem_read(SCRATCH + 0x200, 2))[0]
                        if count > 32:
                            raise ValueError('Unexpected graphic extent count')
                        report['graphics_memory'] = initialization.words(SCRATCH + 0x100, count * 2)
                    print('graphics open', opened['status'], hex(opened['return_value']),
                          report.get('graphics_memory'), opened.get('boundary'), flush=True)
    output = PROJECT_ROOT / 'artifacts/execution/dmm-config-trace.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
