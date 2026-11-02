"""Original timer descriptor-to-runtime-pointer slice; no clock values supplied."""
import json
import struct

import unicorn
from unicorn import arm_const as arm

from project_paths import PROJECT_ROOT
from tools.research.dmm_runtime_trace import export_address, timer_window, TIMER_NAME, KERNEL, KERNEL_BASE
from tools.research.mount_evidence import checked_input

START, END = 0x6012534c, 0x60125380
TABLE = 0x604be020


def words(raw, address, count):
    offset = address - KERNEL_BASE
    if offset < 0 or count < 0 or offset + count * 4 > len(raw):
        raise ValueError('Descriptor pointer escapes preserved kernel')
    return list(struct.unpack_from('<' + 'I' * count, raw, offset))


def descriptors(raw):
    driver = export_address(raw, b'udif_hwtimer\0')
    fields = words(raw, driver['address'], 11)
    if fields[9] != 1:
        raise ValueError('Unexpected timer device count')
    device = words(raw, fields[8], 1)[0]
    fields = words(raw, device, 6)
    if struct.pack('<2I', *fields[:2]).rstrip(b'\0') != b'hwtimer' or fields[4] != 4:
        raise ValueError('Unexpected timer device descriptor')
    channels = []
    for cpu in range(4):
        address = fields[5] + cpu * 0x5c
        data = words(raw, address, 5)
        name = struct.pack('<2I', *data[:2]).rstrip(b'\0')
        if name != ('hwtimer' + str(cpu)).encode():
            raise ValueError('Unexpected timer channel descriptor')
        channels.append({'cpu': cpu, 'descriptor': address, 'name': name.decode(),
                         'physical_base': data[2], 'size': data[3], 'compiled_virtual_base': data[4]})
    return {'driver_export': driver, 'device': device, 'channels': channels}


def execute_setup(raw, device, cpu):
    if cpu not in range(4):
        raise ValueError('Unsupported timer channel')
    # This is a slice after earlier initialization calls, not successful
    # execution of those calls or the entire driver initialization callback.
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
    mu.mem_map(KERNEL_BASE, (len(raw) + 4095) & ~4095, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    mu.mem_write(KERNEL_BASE, raw)
    mu.mem_protect(TABLE & ~4095, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
    mu.reg_write(arm.UC_ARM_REG_CPSR, 0x10)
    mu.reg_write(arm.UC_ARM_REG_R4, cpu)
    mu.reg_write(arm.UC_ARM_REG_R5, device)
    result = {'cpu': cpu, 'status': 'running', 'trace': [], 'writes': []}

    def stop(reason, **details):
        result.update(status=reason, boundary={'pc': mu.reg_read(arm.UC_ARM_REG_PC), **details})
        mu.emu_stop()

    def code(uc, address, size, _):
        if address == END:
            stop('runtime_pointer_store_completed')
        elif not START <= address < END:
            stop('unsupported_control_flow', target=address)
        else:
            result['trace'].append({'pc': address, 'bytes': bytes(uc.mem_read(address, size)).hex()})

    channel = words(raw, device + 0x14, 1)[0] + cpu * 0x5c

    def read(uc, access, address, size, value, _):
        allowed = ((device + 0x14, device + 0x18), (channel + 0x10, channel + 0x14),
                   (0x60125468, 0x60125470))
        if not any(a <= address and address + size <= b for a, b in allowed):
            stop('unsupported_data_read', address=address, size=size)

    def write(uc, access, address, size, value, _):
        if address != TABLE + cpu * 20 or size != 4:
            stop('unsupported_data_write', address=address, size=size)
        else:
            result['writes'].append({'address': address, 'size': size, 'value': value})

    def invalid(uc, access, address, size, value, _):
        stop('memory_boundary', address=address, size=size, access=access)
        return False

    mu.hook_add(unicorn.UC_HOOK_CODE, code)
    mu.hook_add(unicorn.UC_HOOK_MEM_READ, read)
    mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, write)
    mu.hook_add(unicorn.UC_HOOK_MEM_INVALID, invalid)
    try:
        mu.emu_start(START, 0, count=100, timeout=1000000)
    except unicorn.UcError as error:
        if result['status'] == 'running':
            result.update(status='execution_fault', error=str(error))
    if result['status'] == 'running':
        result['status'] = 'timeout' if mu.query(unicorn.UC_QUERY_TIMEOUT) else 'instruction_limit'
    return result


def main():
    inputs = json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text(encoding='utf-8'))['inputs']
    expected = next(row['sha256'] for row in inputs if row['path'] == KERNEL)
    raw = checked_input(PROJECT_ROOT, KERNEL, expected)
    description = descriptors(raw)
    report = {'input': {'path': KERNEL, 'sha256': expected}, **description,
              'windows': [execute_setup(raw, description['device'], cpu) for cpu in range(4)],
              'limitations': ['Isolated original slice with selected static driver/device/channel descriptors.',
                  'Earlier initialization, locks, IRQ registration and later timer setup are not executed.',
                  'Compiled virtual addresses do not prove established MMIO mappings or register values.',
                  'No timestamps, hardware responses or application-service replies supplied.']}
    entry = export_address(raw, TIMER_NAME)['address']
    report['composed_reads'] = []
    for window in report['windows']:
        if window['status'] != 'runtime_pointer_store_completed' or len(window['writes']) != 1:
            raise ValueError('Original initialization slice did not establish one timer pointer')
        report['composed_reads'].append(timer_window(raw, entry, window['cpu'], window['writes'][0]['value']))
    output = PROJECT_ROOT / 'artifacts/execution/dmm-timer-setup.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output)
    for window in report['windows']:
        print(window['cpu'], window['status'], window['writes'])


if __name__ == '__main__':
    main()
