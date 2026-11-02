"""Execute bounded original bootin event handlers up to external-call boundaries."""
import json
import struct

import unicorn
from unicorn import arm_const as arm

from project_paths import PROJECT_ROOT
from src.a6400.images.process_elf import inspect_image, map_image
from src.a6400.execution.guest_memory import cstring_preview
from tools.research.startup_trace import analyze

BOOTIN = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/bin/bootin.elf'
RETURN = 0x70000


def run_window(image, start, allowed, setup, terminals, budget=200):
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
    mapping = map_image(mu, image, 0)
    mu.mem_map(0x30000, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
    mu.mem_map(0x40000, 0x4000, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
    mu.mem_map(RETURN, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    mu.reg_write(arm.UC_ARM_REG_CPSR, 0x30)
    mu.reg_write(arm.UC_ARM_REG_SP, 0x44000)
    mu.reg_write(arm.UC_ARM_REG_LR, RETURN)
    setup(mu)
    report = {'status': 'running', 'trace': [], 'image_sha256': image['sha256'],
              'mapping': mapping, 'instruction_budget': budget, 'timeout_us': 100000}
    def code(uc, address, size, _):
        if address in terminals:
            report.update(status=terminals[address], boundary_pc=address)
            uc.emu_stop()
            return
        if not allowed[0] <= address < allowed[1]:
            report.update(status='unexpected_control_flow', boundary_pc=address)
            uc.emu_stop()
            return
        report['trace'].append({'pc': address, 'bytes': bytes(uc.mem_read(address, size)).hex()})
    mu.hook_add(unicorn.UC_HOOK_CODE, code)
    try:
        mu.emu_start(start, 0, count=budget, timeout=100000)
    except unicorn.UcError as error:
        report.update(status='execution_fault', error=str(error))
    if report['status'] == 'running':
        report['status'] = 'timeout' if mu.query(unicorn.UC_QUERY_TIMEOUT) else 'instruction_budget_exhausted'
    report['registers'] = {name: mu.reg_read(getattr(arm, 'UC_ARM_REG_' + name.upper()))
                           for name in ('r0', 'r1', 'r2', 'r3', 'r4', 'r5', 'r6', 'sp', 'lr', 'pc')}
    return report, mu


def dispatch_case(image, event):
    def setup(mu):
        mu.mem_write(0x30000, struct.pack('<5I', 0x11223344, event, 0, 0, 0))
        mu.reg_write(arm.UC_ARM_REG_R0, 0x30004)
    report, mu = run_window(image, 0x98fd, (0x98fc, 0x9a38), setup,
                             {0x8b6c: 'system_call_boundary', 0x8e18: 'message_helper_boundary',
                              RETURN: 'normal_return'})
    report['input'] = {'event': event, 'sender': 'constructed marker 0x11223344', 'body': 'event plus three zero words'}
    if report['status'] == 'system_call_boundary':
        report['command'] = cstring_preview(mu, report['registers']['r0'])
    report['host_commands_executed'] = 0
    return report


def message_case(image):
    def setup(mu):
        mu.reg_write(arm.UC_ARM_REG_R0, 0)  # observed helper success branch; allocator itself is not run
        mu.reg_write(arm.UC_ARM_REG_R4, 0x0094016a)
        mu.reg_write(arm.UC_ARM_REG_R5, 0)
        mu.reg_write(arm.UC_ARM_REG_R6, 0x009400f3)
        mu.reg_write(arm.UC_ARM_REG_R7, 0x43000)
        mu.reg_write(arm.UC_ARM_REG_SP, 0x43000)
        mu.mem_write(0x43004, struct.pack('<I', 0x30004))
        mu.mem_write(0x30000, bytes([0xa5]) * 20)
    report, mu = run_window(image, 0x8e37, (0x8e36, 0x8e48), setup,
                             {0x8e48: 'send_callsite_boundary'})
    report['allocation_assumption'] = 'start after successful allocation; constructed 16-byte body with 4-byte prefix'
    report['message_with_prefix_hex'] = bytes(mu.mem_read(0x30000, 20)).hex()
    report['words'] = list(struct.unpack('<5I', mu.mem_read(0x30000, 20)))
    report['guest_messages_sent'] = 0
    return report


def main():
    inventory = json.loads((PROJECT_ROOT / 'artifacts/inventory/elf-inventory.json').read_text(encoding='utf-8'))
    expected = next(entry['sha256'] for entry in inventory['entries'] if entry['path'] == BOOTIN)
    image = inspect_image(PROJECT_ROOT / BOOTIN, expected)
    cases = [dispatch_case(image, event) for event in range(0x940031, 0x940039)]
    cases += [dispatch_case(image, event) for event in (0x940002, 0x9400f3, 0x9400f4)]
    message = message_case(image)
    report = {'bootin': {'path': BOOTIN, 'sha256': expected}, 'dispatch': cases, 'message_layout': message,
              'static': analyze(PROJECT_ROOT / BOOTIN, [], explicit_blocks=[
                  ('event receiver code', 0x98fd, 0x13c), ('message construction', 0x8e19, 0x52)]),
              'limitations': ['Constructed messages, stack and allocator-success context; no full boot or process launch.',
                              'Stops before system/IPC calls; no host commands, child processes or queue messages emitted.',
                              'Phase delivery ordering and prerequisites are not established by these independent cases.']}
    output = PROJECT_ROOT / 'artifacts/execution/package-h-boot-producers.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output)
    for case in cases:
        print(hex(case['input']['event']), case['status'], case.get('command', case['registers']['r0']), len(case['trace']))
    print('message', message['status'], [hex(word) for word in message['words']])
    if ([case['status'] for case in cases] != ['system_call_boundary'] * 7 + ['normal_return'] + ['message_helper_boundary'] * 3
            or message['status'] != 'send_callsite_boundary'):
        raise SystemExit(2)


if __name__ == '__main__':
    main()
