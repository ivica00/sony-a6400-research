"""Bounded original-kernel memory-device dispatch; no runtime entropy is invented."""
import json
import struct

import capstone
import unicorn
from unicorn import arm_const as arm

from project_paths import PROJECT_ROOT
from tools.research.mount_evidence import checked_input, terminated_ascii
from src.a6400.images.ext2_metadata import Ext2Metadata

KERNEL = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
KERNEL_BASE = 0x60108000
DEVLIST_OFFSET = 0x2d6bf0
MEMORY_OPEN = 0x60295c40
URANDOM_READ = 0x60296f20
EXTRACT_USER = 0x60296e0c


def inspect_kernel(data):
    def offset(address, size):
        value = address - KERNEL_BASE
        if value < 0 or value + size > len(data):
            raise ValueError('Kernel pointer escapes preserved image')
        return value
    rows = []
    for minor in range(12):
        name, mode, fops, backing = struct.unpack_from('<4I', data, DEVLIST_OFFSET + 16 * minor)
        if not name:
            continue
        rows.append({'minor': minor, 'name': terminated_ascii(data, offset(name, 1)),
                     'mode': mode, 'fops': fops, 'backing_info': backing})
    expected_names = {1: 'mem', 3: 'null', 4: 'port', 5: 'zero', 7: 'full', 8: 'random', 9: 'urandom', 11: 'kmsg'}
    if {row['minor']: row['name'] for row in rows} != expected_names:
        raise ValueError('Kernel device-table/string mapping preimage mismatch')
    urandom = next(row for row in rows if row['minor'] == 9)
    fops_offset = offset(urandom['fops'], 104)
    fops = struct.unpack_from('<26I', data, fops_offset)
    if urandom['name'] != 'urandom' or urandom['mode'] != 0o666 or fops[2] != URANDOM_READ or fops[11] != 0:
        raise ValueError('Kernel urandom dispatch preimage mismatch')
    pool = struct.unpack_from('<I', data, offset(URANDOM_READ + 24, 4))[0]
    decoder = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    blocks = []
    for name, start, size in [('memory_open', MEMORY_OPEN, 132), ('urandom_read', URANDOM_READ, 24),
                              ('extract_entropy_user', EXTRACT_USER, 272)]:
        raw = data[offset(start, size):offset(start, size) + size]
        blocks.append({'name': name, 'address': start, 'bytes': raw.hex(),
                       'instructions': [{'address': ins.address, 'bytes': ins.bytes.hex(),
                                         'mnemonic': ins.mnemonic, 'operands': ins.op_str}
                                        for ins in decoder.disasm(raw, start)]})
    return {'kernel_base': KERNEL_BASE,
            'base_basis': 'consistent pointer-to-string differences for all nonempty devlist entries',
            'devlist_file_offset': DEVLIST_OFFSET, 'devlist': rows,
            'urandom': {'fops': urandom['fops'], 'read': fops[2], 'open': fops[11],
                        'pool_pointer': pool, 'extract_user': EXTRACT_USER}, 'blocks': blocks}


def execute_window(data, start, end_boundary, mode):
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
    mu.mem_map(KERNEL_BASE, (len(data) + 4095) & ~4095, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    mu.mem_write(KERNEL_BASE, data)
    mu.mem_map(0x10000, 0x4000, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
    mu.mem_map(0x20000, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    mu.reg_write(arm.UC_ARM_REG_CPSR, 0x10)
    mu.reg_write(arm.UC_ARM_REG_SP, 0x14000)
    mu.reg_write(arm.UC_ARM_REG_LR, 0x20000)
    mu.reg_write(arm.UC_ARM_REG_R0, 0x10000)
    mu.reg_write(arm.UC_ARM_REG_R1, 0x11000)
    mu.reg_write(arm.UC_ARM_REG_R2, 4)
    # Constructed inode's i_rdev: kernel internal MKDEV(1,9), not userspace stat encoding.
    mu.mem_write(0x10088, struct.pack('<I', (1 << 20) | 9))
    report = {'status': 'not_reached', 'mode': mode, 'trace': [],
              'assumptions': 'constructed inode/file/stack; no VFS, entropy pool or boot state supplied'}
    def code(uc, address, size, _):
        if address == end_boundary:
            report['status'] = 'normal_return' if mode == 'open' else 'entropy_extractor_boundary'
            uc.emu_stop()
            return
        limit = MEMORY_OPEN + 132 if mode == 'open' else URANDOM_READ + 24
        if not start <= address < limit:
            report['status'] = 'unexpected_control_flow'
            uc.emu_stop()
            return
        report['trace'].append({'pc': address, 'bytes': bytes(uc.mem_read(address, size)).hex()})
    mu.hook_add(unicorn.UC_HOOK_CODE, code)
    try:
        mu.emu_start(start, 0, count=100, timeout=100000)
    except unicorn.UcError as error:
        report.update(status='execution_fault', error=str(error))
    report['registers'] = {name: mu.reg_read(getattr(arm, 'UC_ARM_REG_' + name.upper()))
                           for name in ('r0', 'r1', 'r2', 'r3', 'pc', 'lr')}
    report['file_fops'] = struct.unpack('<I', bytes(mu.mem_read(0x11010, 4)))[0]
    report['entropy_bytes_supplied'] = 0
    return report


def main():
    manifest = json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text(encoding='utf-8'))
    expected = {item['path']: item['sha256'] for item in manifest['inputs']}
    data = checked_input(PROJECT_ROOT, KERNEL, expected[KERNEL])
    report = {'kernel': {'path': KERNEL, 'sha256': expected[KERNEL]}, **inspect_kernel(data)}
    image = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha7'
    source = Ext2Metadata(PROJECT_ROOT / image, expected[image])
    report['image_node'] = {'path': '/dev/urandom', 'image_sha256': source.sha256,
                            **source.index()['/dev/urandom']}
    report['windows'] = [execute_window(data, MEMORY_OPEN, 0x20000, 'open'),
                          execute_window(data, URANDOM_READ, EXTRACT_USER, 'read')]
    opened, read = report['windows']
    if (opened['registers']['r0'] != 0 or opened['file_fops'] != report['urandom']['fops']
            or read['registers']['r0'] != report['urandom']['pool_pointer']
            or read['registers']['r1'] != 0x11000 or read['registers']['r2'] != 4):
        raise ValueError('Original routine output does not establish expected dispatch')
    report['limitations'] = ['No camera boot, driver registration, namespace lifetime or entropy output validated.',
                            'Routine identities inferred by original table/call shape plus Linux 3.0 source; no recovered symbol names.',
                            'Pool pointer is not permission to consume static initializer bytes as runtime state.']
    output = PROJECT_ROOT / 'artifacts/execution/package-h-entropy-trace.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output)
    for window in report['windows']:
        print(window['mode'], window['status'], len(window['trace']), window['registers'])
    if [w['status'] for w in report['windows']] != ['normal_return', 'entropy_extractor_boundary']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
