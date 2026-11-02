"""Bounded original inode/attribute routines; no runtime timestamps or boot supplied."""
import json
import io
import struct

import capstone
import unicorn
from unicorn import arm_const as arm
from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.mount_evidence import checked_input, terminated_ascii
from tools.research.entropy_trace import KERNEL, KERNEL_BASE

EXPORTS = {'generic_fillattr': (0x36c7f0, 0x601c3070),
           'inode_init_always': (0x36ce48, 0x601d635c),
           'init_special_inode': (0x36ce10, 0x601d5648),
           'touch_atime': (0x36f6d8, 0x601d6664)}


def inspect_exports(data):
    rows = {}
    for name, (offset, expected) in EXPORTS.items():
        value, pointer = struct.unpack_from('<II', data, offset)
        if value != expected or terminated_ascii(data, pointer - KERNEL_BASE) != name:
            raise ValueError('Kernel inode export-table preimage mismatch')
        rows[name] = {'export_file_offset': offset, 'address': value, 'name_pointer': pointer}
    return rows


def execute_case(data, mode=0o100644, device=0):
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
    mu.mem_map(KERNEL_BASE, (len(data) + 4095) & ~4095, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    mu.mem_write(KERNEL_BASE, data)
    mu.mem_map(0x10000, 0x4000)
    mu.mem_map(0x20000, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    mu.reg_write(arm.UC_ARM_REG_CPSR, 0x10)
    inode, superblock, output = 0x10000, 0x11000, 0x12000
    mu.mem_write(inode, b'Z' * 0x200)
    mu.mem_write(superblock + 13, b'\x0c')
    mu.mem_write(superblock + 8, struct.pack('<I', 0x12345678))
    windows = []
    def run(name, start, end, allowed_end, registers):
        for register, value in registers.items():
            mu.reg_write(register, value)
        mu.reg_write(arm.UC_ARM_REG_SP, 0x14000)
        mu.reg_write(arm.UC_ARM_REG_LR, 0x20000)
        report = {'name': name, 'status': 'running', 'trace': [],
                  'instruction_budget': 150, 'timeout_us': 100000}
        def code(uc, address, size, _):
            if address == end:
                report.update(status='boundary_reached', boundary_pc=address)
                uc.emu_stop()
            elif not start <= address < allowed_end:
                report.update(status='unexpected_control_flow', boundary_pc=address)
                uc.emu_stop()
            else:
                report['trace'].append({'pc': address, 'bytes': bytes(uc.mem_read(address, size)).hex()})
        hook = mu.hook_add(unicorn.UC_HOOK_CODE, code)
        try:
            mu.emu_start(start, 0, count=150, timeout=100000)
        except unicorn.UcError as error:
            report.update(status='execution_fault', error=str(error))
        finally:
            mu.hook_del(hook)
        if report['status'] == 'running':
            report['status'] = 'timeout' if mu.query(unicorn.UC_QUERY_TIMEOUT) else 'instruction_budget_exhausted'
        windows.append(report)
        if report['status'] != 'boundary_reached':
            raise ValueError(f'Original inode window failed: {report}')
    run('inode_init_always prefix before first external call', 0x601d635c, 0x601d63e8,
        0x601d63ec, {arm.UC_ARM_REG_R0: superblock, arm.UC_ARM_REG_R1: inode})
    initialized_rdev = struct.unpack('<I', mu.mem_read(inode + 0x88, 4))[0]
    # Explicit constructed inode-loading inputs; these routines do not read ext2.
    mu.mem_write(inode, struct.pack('<H', mode))
    mu.mem_write(inode + 0x7c, struct.pack('<I', 37))
    mu.mem_write(inode + 0xa0, bytes(4))  # stable constructed size sequence
    for offset, value in ((0xa4, 101), (0xac, 102), (0xb4, 103)):
        mu.mem_write(inode + offset, struct.pack('<II', value, 0))
    if mode & 0xf000 in (0x2000, 0x6000):
        run('init_special_inode', 0x601d5648, 0x20000, 0x601d56bc,
            {arm.UC_ARM_REG_R0: inode, arm.UC_ARM_REG_R1: mode, arm.UC_ARM_REG_R2: device})
    run('generic_fillattr', 0x601c3070, 0x20000, 0x601c3140,
        {arm.UC_ARM_REG_R0: inode, arm.UC_ARM_REG_R1: output})
    rdev = struct.unpack('<I', mu.mem_read(output + 0x1c, 4))[0]
    if initialized_rdev != 0 or rdev != (device if mode & 0xf000 in (0x2000, 0x6000) else 0):
        raise ValueError('Original inode/attribute device field did not match the observed contract')
    before_times = bytes(mu.mem_read(inode + 0xa4, 24))
    mu.mem_write(superblock + 0x34, struct.pack('<I', 1))  # SB_RDONLY
    mu.mem_write(0x12500 + 0x3c, struct.pack('<I', inode))  # constructed dentry
    run('touch_atime with read-only superblock', 0x601d6664, 0x20000, 0x601d67a8,
        {arm.UC_ARM_REG_R0: 0x12800, arm.UC_ARM_REG_R1: 0x12500})
    if bytes(mu.mem_read(inode + 0xa4, 24)) != before_times:
        raise ValueError('Read-only atime window modified timestamps')
    return {'mode': mode, 'constructed_device': device, 'initialized_inode_rdev': initialized_rdev,
            'kstat_rdev': rdev, 'readonly_timestamps_unchanged': True, 'windows': windows,
            'assumptions': 'constructed superblock/inode/stack, mode, inode number, stable size sequence and timestamp markers; no filesystem traversal or boot'}


def main():
    baseline = json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text(encoding='utf-8'))
    expected = next(entry['sha256'] for entry in baseline['inputs'] if entry['path'] == KERNEL)
    data = checked_input(PROJECT_ROOT, KERNEL, expected)
    exports = inspect_exports(data)
    decoder = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    blocks = []
    for name, length in [('inode_init_always', 0x90), ('generic_fillattr', 0xd0),
                         ('init_special_inode', 0x74), ('touch_atime', 0x144)]:
        address = exports[name]['address']
        blocks.append({'name': name, 'instructions': [
            {'address': ins.address, 'bytes': ins.bytes.hex(), 'mnemonic': ins.mnemonic, 'operands': ins.op_str}
            for ins in decoder.disasm(data[address - KERNEL_BASE:address - KERNEL_BASE + length], address)]})
    report = {'kernel': {'path': KERNEL, 'sha256': expected}, 'exports': exports, 'blocks': blocks,
              'cases': [execute_case(data), execute_case(data, 0o20644, (1 << 20) | 9),
                        execute_case(data, 0o60644, (252 << 20) | 15)],
              'limitations': ['No mounted inode lifetime, ext2 traversal, camera boot or runtime timestamps established.',
                              'Non-device regular-inode contract relies on inode initialization plus ext2 regular-file semantics; special-node values are separate.']}
    module_path = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/liro.ko'
    inventory = json.loads((PROJECT_ROOT / 'artifacts/inventory/elf-inventory.json').read_text(encoding='utf-8'))
    module_hash = next(entry['sha256'] for entry in inventory['entries'] if entry['path'] == module_path)
    module = ELFFile(io.BytesIO(checked_input(PROJECT_ROOT, module_path, module_hash)))
    report['liro_static_requirements'] = {
        'path': module_path, 'sha256': module_hash,
        'module_info': [value for value in module.get_section_by_name('.modinfo').data().decode('ascii').split('\0') if value],
        'undefined_symbols': [symbol.name for symbol in module.get_section_by_name('.symtab').iter_symbols()
                              if symbol.name and symbol['st_shndx'] == 'SHN_UNDEF'],
        'scope': 'static requirements, not resolved symbols or executed module initialization',
    }
    output = PROJECT_ROOT / 'artifacts/execution/package-h-inode-attributes.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output)
    for case in report['cases']:
        print(oct(case['mode']), 'initialized', case['initialized_inode_rdev'], 'kstat', case['kstat_rdev'])


if __name__ == '__main__':
    main()
