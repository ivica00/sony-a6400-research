"""Original Sony task/context copy windows; no allocation, PID or fork success."""
import argparse
import json
import struct

import unicorn
from unicorn import arm_const as arm

from project_paths import PROJECT_ROOT
from src.a6400.execution.kernel_task_identity import KernelTaskObservation
from tools.research.dmm_runtime_trace import KERNEL_BASE
from tools.research.wbi_gles_execute import load_context
from tools.research.wbi_gles_state import ROOT, owner_context_candidates
from tools.research.wbi_pagewalk import read_virtual

STACK, CHILD, CHILD_TI, RETURN = 0x08000000, 0x08300000, 0x08400000, 0x09000000
COPY_TASK, COPY_THREAD = 0x60131734, 0x6010f164
COPY_INFO, INFO_END, NOTIFIER_CALL = 0x6013225c, 0x60132280, 0x6010f1d4
MEMCPY, MEMZERO = 0x60258b80, 0x602592e0


def observed_task_name(context, task):
    """Name bytes from original get_task_comm's source offset, not a string scan."""
    kernel = context['kernel']
    # add r1,r6,#0x1e8; mov r2,#16; mov r0,r4; bl strlcpy
    if kernel[0xbbfb0:0xbbfbc] != bytes.fromhex('7a1f86e21020a0e30400a0e1'):
        raise ValueError('Original get_task_comm source extent differs')
    raw = read_virtual(context['memory'], ROOT, task + 0x1e8, 16)
    return {'source_address': task + 0x1e8, 'raw_hex': raw.hex(),
            'value': raw.split(b'\0', 1)[0].decode('ascii', errors='replace')}


def observed_group(context, tgid=152):
    rows = []
    for candidate in owner_context_candidates(context['memory'], [{'tgid': tgid}]):
        observation = KernelTaskObservation.read(
            lambda a, n: read_virtual(context['memory'], ROOT, a, n), candidate['thread_info'])
        row = {**observation.__dict__, 'comm': observed_task_name(context, observation.task)}
        if row['comm']['value'] in ('THREAD_INFRA0', 'grm_dn_vdf_if'):
            row['saved_frame_hex'] = read_virtual(context['memory'], ROOT,
                                                  observation.thread_info+0x1fb0, 72).hex()
        rows.append(row)
    return rows


def branch_target(kernel, address):
    word = struct.unpack_from('<I', kernel, address - KERNEL_BASE)[0]
    if word >> 24 != 0xeb:
        raise ValueError('Original call is not unconditional ARM BL')
    delta = (word & 0xffffff) << 2
    if delta & 0x2000000:
        delta -= 0x4000000
    return address + 8 + delta


def execute_area_prefix(context, *, length, address=0, flags=2):
    """Original get_unmapped_area prefix; never answer its mm callback."""
    kernel = context['kernel']
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
    mu.mem_map(KERNEL_BASE, (len(kernel)+4095) & ~4095, 5)
    mu.mem_write(KERNEL_BASE, kernel)
    mu.mem_map(STACK, 8192, 3)
    mu.mem_map(RETURN, 4096, 5)
    entry_sp = STACK+0x1800
    mu.mem_write(entry_sp, struct.pack('<I', flags))
    known = set(range(entry_sp, entry_sp+4))
    for register, value in ((arm.UC_ARM_REG_CPSR, 0x13), (arm.UC_ARM_REG_SP, entry_sp),
                            (arm.UC_ARM_REG_LR, RETURN), (arm.UC_ARM_REG_R0, 0),
                            (arm.UC_ARM_REG_R1, address), (arm.UC_ARM_REG_R2, length),
                            (arm.UC_ARM_REG_R3, 0)):
        mu.reg_write(register, value)
    report = {'status': 'running', 'length': length, 'address': address,
              'flags': flags, 'trace': [], 'callback_responses_supplied': 0}

    def stop(status):
        report.update(status=status, pc=mu.reg_read(arm.UC_ARM_REG_PC))
        mu.emu_stop()

    def code(uc, pc, size, _):
        if pc == RETURN:
            report['returned'] = uc.reg_read(arm.UC_ARM_REG_R0)
            stop('original_area_return')
        elif pc == 0x6019cb10:
            stop('task_mm_callback_prerequisite')
        elif not 0x6019cadc <= pc < 0x6019cb8c:
            stop('unsupported_control_flow')
        else:
            raw = bytes(uc.mem_read(pc, size))
            if raw != read_virtual(context['memory'], ROOT, pc, size):
                stop('kernel_instruction_identity_mismatch')
            else:
                report['trace'].append({'pc': pc, 'bytes': raw.hex()})

    def read(uc, access, address, size, value, _):
        if not all(a in known for a in range(address, address+size)):
            stop('unsupplied_stack_bytes')

    def write(uc, access, address, size, value, _):
        if not STACK <= address <= address+size <= STACK+8192:
            stop('unsupported_write')
        else:
            known.update(range(address, address+size))

    mu.hook_add(unicorn.UC_HOOK_CODE, code)
    mu.hook_add(unicorn.UC_HOOK_MEM_READ, read)
    mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, write)
    try:
        mu.emu_start(0x6019cadc, 0, count=128, timeout=1000000)
    except unicorn.UcError as error:
        report.update(status='execution_fault', error=str(error))
    if report['status'] == 'running':
        report['status'] = 'execution_limit'
    return report


def execute(context, *, thread_info=0x684a8000, clone_flags=0x3d0f00,
            user_stack=0x10002000, instruction_budget=5000):
    if not 1 <= instruction_budget <= 100000:
        raise ValueError('Instruction budget outside research bound')
    kernel, memory = context['kernel'], context['memory']
    reader = lambda address, size: read_virtual(memory, ROOT, address, size)
    parent = KernelTaskObservation.read(reader, thread_info)
    parent.require_caller(guest_pid=parent.pid, guest_tgid=parent.tgid,
                          user_ranges=[(user_stack, 0)])
    for call, expected in ((0x6010ec9c, 0x601330e8), (0x601331d8, 0x601320b0),
                           (0x6013223c, COPY_TASK), (0x60132a4c, COPY_THREAD),
                           (COPY_TASK + 16, MEMCPY), (0x60132268, MEMCPY),
                           (0x6010f194, MEMCPY), (0x6010f1ac, MEMZERO)):
        if branch_target(kernel, call) != expected:
            raise ValueError('Original task-copy call chain differs')
    frame_address = thread_info + 0x1fb0
    frame = reader(frame_address, 0x48)
    frame_words = struct.unpack('<18I', frame)
    if (frame_words[16] & 0x1f != 0x10 or frame_words[13] >= parent.address_limit
            or frame_words[15] >= parent.address_limit):
        raise ValueError('Captured frame does not establish a supported user register context')
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
    mu.mem_map(KERNEL_BASE, (len(kernel) + 4095) & ~4095, 5)
    mu.mem_write(KERNEL_BASE, kernel)
    for address, length, permissions in ((STACK, 8192, 3), (CHILD, 4096, 3),
                                         (CHILD_TI, 8192, 3), (RETURN, 4096, 5)):
        mu.mem_map(address, length, permissions)
    # A caller frame is a declared research input, not a scheduler-created task.
    for index in range(13):
        mu.reg_write(getattr(arm, 'UC_ARM_REG_R' + str(index)), 0x11000000 + index)
    mu.reg_write(arm.UC_ARM_REG_CPSR, 0x13)
    known = set()
    snapshot_pages = set()
    checked_code_pages = set()
    mutable = [(CHILD, CHILD + 0x3d0), (CHILD_TI, CHILD_TI + 0x128),
               (CHILD_TI + 0x1fb0, CHILD_TI + 0x1ff8)]
    allowed = [(COPY_TASK, COPY_TASK + 28), (COPY_INFO, INFO_END),
               (COPY_THREAD, COPY_THREAD + 0x84), (MEMCPY, MEMCPY + 0xdc),
               (MEMZERO, MEMZERO + 0x7c), (0x60256d70, 0x60256da4)]
    result = {'status': 'running', 'trace': [], 'writes': [], 'stages': [],
              'parent': parent.__dict__, 'parent_frame_address': frame_address,
              'parent_comm': observed_task_name(context, parent.task),
              'parent_frame_hex': frame.hex(), 'clone_flags': clone_flags,
              'user_stack_control': user_stack, 'instruction_budget': instruction_budget,
              'service_returns_supplied': 0, 'child_pid_allocated': False,
              'assumptions': ['Explicit isolated child storage and caller registers/stack.',
                              'Child stack pointer is a caller fixture, not an allocator reply.',
                              'Windows are composed with explicit ABI frames; intervening fork helpers are not executed.']}
    terminal = RETURN

    def stop(status, **details):
        result.update(status=status, boundary=details)
        mu.emu_stop()

    def code(uc, address, size, _):
        if address == terminal:
            stop('window_boundary', pc=address)
            return
        if not any(a <= address and address + size <= b for a, b in allowed):
            stop('unsupported_control_flow', pc=address)
            return
        page = address & ~4095
        if page not in checked_code_pages:
            if reader(page, 4096) != kernel[page-KERNEL_BASE:page-KERNEL_BASE+4096]:
                stop('captured_kernel_code_identity_mismatch', page=page)
                return
            checked_code_pages.add(page)
        raw = bytes(uc.mem_read(address, size))
        if raw != kernel[address-KERNEL_BASE:address-KERNEL_BASE+size]:
            stop('original_kernel_instruction_mismatch', pc=address)
            return
        word = int.from_bytes(raw, 'little')
        if word & 0x0f000010 == 0x0e000010 and word >> 8 & 15 == 15:
            stop('unsupported_cpu_system_register', pc=address)
            return
        result['trace'].append({'pc': address, 'bytes': raw.hex()})

    def read(uc, access, address, size, value, _):
        if any(a <= address < b for a, b in ((STACK, STACK+8192), (CHILD, CHILD+4096),
                                            (CHILD_TI, CHILD_TI+8192))):
            if not all(p in known for p in range(address, address+size)):
                stop('unsupplied_constructed_memory', address=address, size=size)

    def write(uc, access, address, size, value, _):
        if not (STACK <= address <= address+size <= STACK+8192 or
                any(a <= address <= address+size <= b for a, b in mutable)):
            stop('unsupported_write', address=address, size=size)
            return
        known.update(range(address, address+size))
        result['writes'].append({'pc': uc.reg_read(arm.UC_ARM_REG_PC),
                                 'address': address, 'size': size, 'value': value})

    def invalid(uc, access, address, size, value, _):
        if access != unicorn.UC_MEM_READ_UNMAPPED:
            stop('unsupported_memory_access', address=address, access=access)
            return False
        try:
            for page in {address & ~4095, (address+size-1) & ~4095}:
                if page not in snapshot_pages:
                    data = reader(page, 4096)
                    mu.mem_map(page, 4096, 1)
                    mu.mem_write(page, data)
                    snapshot_pages.add(page)
            return True
        except ValueError as error:
            stop('unsupplied_snapshot_memory', address=address, error=str(error))
            return False

    mu.hook_add(unicorn.UC_HOOK_CODE, code)
    mu.hook_add(unicorn.UC_HOOK_MEM_READ, read)
    mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, write)
    mu.hook_add(unicorn.UC_HOOK_MEM_INVALID, invalid)

    def stage(name, entry, end, registers):
        nonlocal terminal
        remaining = instruction_budget - len(result['trace'])
        if remaining <= 0:
            result['status'] = 'instruction_budget_exhausted'
            return False
        terminal = end
        result['status'] = 'running'
        mu.reg_write(arm.UC_ARM_REG_SP, STACK+0x1800)
        mu.reg_write(arm.UC_ARM_REG_LR, RETURN)
        for register, value in registers.items():
            mu.reg_write(register, value)
        before = len(result['trace'])
        try:
            mu.emu_start(entry, 0, count=remaining, timeout=1000000)
        except unicorn.UcError as error:
            if result['status'] == 'running':
                result.update(status='execution_fault', error=str(error))
        if result['status'] == 'running':
            result['status'] = 'timeout' if mu.query(unicorn.UC_QUERY_TIMEOUT) else 'instruction_budget_exhausted'
        result['stages'].append({'name': name, 'status': result['status'],
                                'instructions': len(result['trace'])-before})
        return result['status'] == 'window_boundary'

    if not stage('original_arch_task_copy', COPY_TASK, RETURN,
                 {arm.UC_ARM_REG_R0: CHILD, arm.UC_ARM_REG_R1: parent.task}):
        return result
    # Declared allocated-storage pointer for the next isolated fork window.
    mu.mem_write(CHILD+8, struct.pack('<I', CHILD_TI))
    if not stage('original_thread_info_copy', COPY_INFO, INFO_END,
                 {arm.UC_ARM_REG_R4: CHILD, arm.UC_ARM_REG_R10: parent.task}):
        return result
    result['copied_thread_info_hex'] = bytes(mu.mem_read(CHILD_TI, 0x128)).hex()
    result['copied_task_pid_tgid'] = list(struct.unpack('<2I', mu.mem_read(CHILD+0x104, 8)))
    mu.mem_write(STACK+0x1800, struct.pack('<I', frame_address))
    known.update(range(STACK+0x1800, STACK+0x1804))
    if stage('original_copy_thread_prefix', COPY_THREAD, NOTIFIER_CALL,
             {arm.UC_ARM_REG_R0: clone_flags, arm.UC_ARM_REG_R1: user_stack,
              arm.UC_ARM_REG_R2: 0, arm.UC_ARM_REG_R3: CHILD}):
        result.update(status='original_thread_notifier_boundary',
                      child_frame_hex=bytes(mu.mem_read(CHILD_TI+0x1fb0, 0x48)).hex(),
                      child_context_hex=bytes(mu.mem_read(CHILD_TI+0x1c, 0x48)).hex(),
                      notifier_arguments=[mu.reg_read(r) for r in (arm.UC_ARM_REG_R0,
                                                                  arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2)])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', required=True)
    args = parser.parse_args()
    output = (PROJECT_ROOT / args.report_dir).resolve()
    if not output.is_relative_to(PROJECT_ROOT / 'artifacts'):
        parser.error('Reports must remain under artifacts')
    context = load_context()
    result = {'inputs': context['inputs'], 'selected_root': ROOT,
              'cases': [execute(context, clone_flags=flags) for flags in (0x3d0f00, 0)],
              'observed_group_tasks': observed_group(context),
              'area_prefix_cases': [execute_area_prefix(context, length=0x5f000001),
                                    execute_area_prefix(context, length=4096, address=1, flags=0x12),
                                    execute_area_prefix(context, length=4096)],
              'compiled_limit_windows': [
                  {'start': start, 'bytes': context['kernel'][start-KERNEL_BASE:end-KERNEL_BASE].hex()}
                  for start, end in ((0x601381c8, 0x601381d0), (0x6019cb54, 0x6019cb8c),
                                     (0x601c4e0c, 0x601c4e14), (0x601c5284, 0x601c5298))],
              'limitations': ['Original bounded copy windows, not a completed fork/clone or allocated PID.',
                              'Intervening allocation, FPU, credential, namespace and scheduler helpers remain unexecuted.',
                              'Captured parent context is not a binding to the main process.',
                              'Stops before notifier dispatch; no task publication, hardware response or pixels.']}
    output.mkdir(parents=True, exist_ok=False)
    (output / 'report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    for case in result['cases']:
        print(hex(case['clone_flags']), case['status'], len(case['trace']), case.get('boundary'))


if __name__ == '__main__':
    main()
