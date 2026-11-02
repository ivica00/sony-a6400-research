"""Original Thumb lookup reply consumer using a freshly executed GRM producer.

The transport-return stack/context are explicit constructed research inputs.
No IPC, allocation or mutex result is invented or supplied to main startup.
"""
import argparse
import io
import json
import struct

import unicorn
from unicorn import arm_const as arm
from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input
from tools.research.wbi_grm_consumer import main as produce

CLIENT = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libObj.so'
STACK, CONTEXT, PACKET = 0x08000000, 0x08100000, 0x08200000


def consume(raw, packet):
    if len(packet) != 36 or struct.unpack_from('<H', packet)[0] != 7:
        raise ValueError('Expected bounded original lookup packet layout')
    elf = ELFFile(io.BytesIO(raw))
    section = next(s for s in elf.iter_sections() if s['sh_addr'] <= 0x720986 < s['sh_addr'] + s['sh_size'])
    if not section['sh_flags'] & 4:
        raise ValueError('Original client window is not executable')
    page = 0x720000
    offset = page - section['sh_addr']
    data = section.data()[offset:offset + 4096]
    if len(data) != 4096:
        raise ValueError('Client code page escapes original section')
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_THUMB)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
    mu.mem_map(page, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    mu.mem_write(page, data)
    mu.mem_map(STACK, 16384)
    mu.mem_map(CONTEXT, 4096, unicorn.UC_PROT_READ)
    mu.mem_write(CONTEXT, struct.pack('<3I', 0, PACKET, 1))
    mu.mem_map(PACKET, 4096, unicorn.UC_PROT_READ)
    mu.mem_write(PACKET, packet)
    # Explicit post-transport helper frame: saved r3/r4/r7/lr. This models
    # neither the transport call nor a successful kernel response.
    mu.mem_write(STACK + 0x2000, struct.pack('<4I', 0, PACKET + 4, STACK + 0x2100, 0x720f0b))
    mu.reg_write(arm.UC_ARM_REG_CPSR, 0x30)
    mu.reg_write(arm.UC_ARM_REG_SP, STACK + 0x2000)
    mu.reg_write(arm.UC_ARM_REG_R4, CONTEXT)
    mu.reg_write(arm.UC_ARM_REG_R6, PACKET + 20)
    allowed = [(0x720986, 0x72098c), (0x720f0a, 0x720f10)]
    report = {'status': 'running', 'packet_hex': packet.hex(), 'trace': [], 'reads': [],
        'constructed_context': {'address': CONTEXT, 'message_pointer_offset': 4,
            'post_transport_stack': STACK + 0x2000, 'saved_return': 0x720f0b},
        'limitations': ['Fresh original producer bytes, copied into a constructed transport-return context.',
            'IPC, kernel/mutex effects, operator new and object constructor are not executed.',
            'No service policy or main-process response is supplied.']}

    def stop(reason, **details):
        report.update(status=reason, boundary={'pc': mu.reg_read(arm.UC_ARM_REG_PC), **details})
        mu.emu_stop()

    def code(uc, address, size, _):
        if address == 0x720f10:
            stop('operator_new_call_boundary', requested_size=uc.reg_read(arm.UC_ARM_REG_R0))
        elif address == 0x720f4a:
            stop('lookup_error_cleanup_boundary', error=uc.reg_read(arm.UC_ARM_REG_R5))
        elif not any(a <= address and address + size <= b for a, b in allowed):
            stop('unsupported_control_flow', address=address)
        else:
            report['trace'].append({'pc': address, 'bytes': bytes(uc.mem_read(address, size)).hex()})

    def read(uc, access, address, size, value, _):
        known = ((STACK, STACK + 16384), (CONTEXT, CONTEXT + 12), (PACKET, PACKET + 36))
        if not any(a <= address and address + size <= b for a, b in known):
            stop('unsupplied_read', address=address, size=size)
        else:
            report['reads'].append({'address': address, 'size': size, 'bytes': bytes(uc.mem_read(address, size)).hex()})

    def write(uc, access, address, size, value, _):
        stop('unsupported_write', address=address, size=size)

    def invalid(uc, access, address, size, value, _):
        stop('memory_boundary', address=address, size=size, access=access)
        return False

    mu.hook_add(unicorn.UC_HOOK_CODE, code)
    mu.hook_add(unicorn.UC_HOOK_MEM_READ, read)
    mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, write)
    mu.hook_add(unicorn.UC_HOOK_MEM_INVALID, invalid)
    try:
        mu.emu_start(0x720987, 0, count=100, timeout=100000)
    except unicorn.UcError as error:
        if report['status'] == 'running':
            report.update(status='execution_fault', error=str(error))
    if report['status'] == 'running':
        report['status'] = 'timeout' if mu.query(unicorn.UC_QUERY_TIMEOUT) else 'instruction_limit'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', required=True)
    parser.add_argument('--name', choices=('gl_common', 'absent_control'), default='gl_common')
    args = parser.parse_args()
    output = (PROJECT_ROOT / args.report_dir).resolve()
    if not output.is_relative_to(PROJECT_ROOT / 'artifacts'):
        parser.error('Output must remain under artifacts')
    output.mkdir(parents=True, exist_ok=False)
    producer = produce(['--report-dir', str((output / 'producer').relative_to(PROJECT_ROOT)), '--name', args.name])
    if producer['status'] != 'isolated_lookup_return':
        raise ValueError('Original producer did not return')
    hashes = {r['path']: r['sha256'] for r in json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text())['inputs']}
    raw = checked_input(PROJECT_ROOT, CLIENT, hashes[CLIENT])
    name = args.name.encode('ascii').ljust(16, b'\0')
    packet = struct.pack('<HH', 7, 0) + name + struct.pack('<4I', *producer['reply'])
    report = consume(raw, packet)
    report.update(inputs={**producer['inputs'], CLIENT: hashes[CLIENT]}, producer_status=producer['status'], name=args.name)
    checked_input(PROJECT_ROOT, CLIENT, hashes[CLIENT])
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    print(output, report['status'], len(report['trace']), report['boundary'])


if __name__ == '__main__':
    main()
