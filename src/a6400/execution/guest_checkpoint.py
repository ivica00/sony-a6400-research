"""High-speed checkpointing and state restoration for InterpreterProbe.

Enables instant (<0.5s) resume from arbitrary execution milestones (e.g. 50M, 88M, 100M)
instead of re-executing tens of millions of instructions from scratch.
"""

import pickle
import zlib
from pathlib import Path
from typing import Any, Dict

import unicorn
from unicorn import arm_const as arm

from src.a6400.execution.capped_log import CappedLog

ARM_CHECKPOINT_REGS = (
    arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2, arm.UC_ARM_REG_R3,
    arm.UC_ARM_REG_R4, arm.UC_ARM_REG_R5, arm.UC_ARM_REG_R6, arm.UC_ARM_REG_R7,
    arm.UC_ARM_REG_R8, arm.UC_ARM_REG_R9, arm.UC_ARM_REG_R10, arm.UC_ARM_REG_R11,
    arm.UC_ARM_REG_R12, arm.UC_ARM_REG_SP, arm.UC_ARM_REG_LR, arm.UC_ARM_REG_PC,
    arm.UC_ARM_REG_CPSR, arm.UC_ARM_REG_FPEXC, arm.UC_ARM_REG_C13_C0_3
)


def checkpoint_resume_state(probe):
    """Preserve a stopped, unanswered SVC as a retry, never a supplied reply."""
    status = probe.report.get('status')
    boundary = probe.report.get('boundary', {})
    result = {'status': status, 'boundary': boundary, 'retry_pc': None}
    if status not in ('syscall_boundary', 'blocked_uipc', 'unsupported_filesystem',
                      'unsupported_uipc_contract', 'unsupported_gles_contract',
                      'unsupported_stream_contract', 'unsupported_usb_contract', 'unsupported_kikilog_contract',
                      'unsupported_nflasha4_contract'):
        return result
    pc = probe.mu.reg_read(arm.UC_ARM_REG_PC)
    thumb = bool(probe.mu.reg_read(arm.UC_ARM_REG_CPSR) & 0x20)
    size = 2 if thumb else 4
    address = boundary.get('instruction_address', boundary.get('pc', pc) - size)
    if address not in (pc, pc - size):
        result['retry_error'] = 'stop_pc_does_not_match_boundary'
        return result
    expected = b'\x00\xdf' if thumb else b'\x00\x00\x00\xef'
    try:
        instruction = bytes(probe.mu.mem_read(address, size))
    except unicorn.UcError:
        instruction = None
    if instruction != expected:
        result['retry_error'] = 'boundary_is_not_verified_eabi_svc_zero'
        return result
    result['retry_pc'] = address
    result['r7'] = probe.mu.reg_read(arm.UC_ARM_REG_R7)
    return result


def save_checkpoint(probe, filepath: Path) -> int:
    """Serializes the exact Unicorn memory mappings, CPU context, and Python subsystem state."""
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # 1. Sync active thread registers and capture all ARM registers
    if hasattr(probe, 'threads') and probe.threads:
        probe.threads.save_context(probe.mu)
    regs = {r: probe.mu.reg_read(r) for r in ARM_CHECKPOINT_REGS}
    ctx_bytes = pickle.dumps(probe.mu.context_save())

    # 2. Unicorn Memory Mappings & Page Contents (compressed with zlib level 1)
    regions = []
    for begin, end, perms in probe.mu.mem_regions():
        size = end - begin + 1
        data = bytes(probe.mu.mem_read(begin, size))
        compressed = zlib.compress(data, level=1)
        regions.append({
            'begin': begin,
            'end': end,
            'perms': perms,
            'size': size,
            'data': compressed,
        })

    uipc_bytes = None
    if hasattr(probe, 'uipc') and probe.uipc:
        # Temporarily detach any dynamically patched local wrapper (e.g. patched_rcv_msg_tmo in experiment_ui_boot)
        patched_fn = probe.uipc.__dict__.pop('handle_rcv_msg_tmo', None)
        try:
            uipc_bytes = pickle.dumps(probe.uipc)
        finally:
            if patched_fn is not None:
                probe.uipc.handle_rcv_msg_tmo = patched_fn

    # 3. Python Subsystem State
    # A CappedLog keeps its totals and counts; a BootLogger wrapper must not be pickled (callback, stream, probe).
    raw_serviced = probe.report.get('serviced_syscalls', [])
    serviced_log = raw_serviced if isinstance(raw_serviced, CappedLog) else list(raw_serviced)
    subsystems: Dict[str, Any] = {
        'instructions': probe.instructions,
        'runtime': {
            'thread_timeslice': getattr(probe, 'thread_timeslice', 0),
            'timeslice_mark': getattr(probe, '_timeslice_mark', 0),
        },
        'signal_handlers': dict(probe.signal_handlers),
        'serviced_syscalls': serviced_log,
        'syscall_responses_supplied': probe.report.get('syscall_responses_supplied', 0),
        'loaded_modules': list(probe.report.get('loaded_modules', [])),
        'filesystem_fds': dict(probe.filesystem.fds),
        'filesystem_cache': dict(probe.filesystem.cache),
        'threads': pickle.dumps(probe.threads) if hasattr(probe, 'threads') and probe.threads else None,
        'sem': pickle.dumps(probe.sem) if hasattr(probe, 'sem') and probe.sem else None,
        'uipc': uipc_bytes,
        'heap': {
            'current': probe.heap.current,
            'start': probe.heap.start,
            'ceiling': probe.heap.ceiling,
        } if hasattr(probe, 'heap') and probe.heap else None,
        'mmap': {
            'next_address': probe.mmap.next_address,
            'mapped_pages': set(probe.mmap.mapped_pages),
            'page_backing': dict(probe.mmap.page_backing),
            'mappings': list(probe.mmap.mappings),
            'base_address': probe.mmap.base_address,
            'ceiling_address': probe.mmap.ceiling_address,
            'search_low_base': probe.mmap.search_low_base,
        } if hasattr(probe, 'mmap') and probe.mmap else None,
        'stream_mappings': list(probe.stream.mappings) if hasattr(probe, 'stream') and hasattr(probe.stream, 'mappings') else None,
        'stream': probe.stream.to_state() if getattr(probe, 'stream', None) is not None else None,
        'display': probe.display.to_state() if getattr(probe, 'display', None) is not None else None,
        'stat64': {
            'bytes': dict(probe.stat64.bytes),
            'read_fields': dict(probe.stat64.read_fields),
        } if hasattr(probe, 'stat64') else None,
        'uname': {
            'bytes': dict(probe.uname.bytes),
            'read_fields': dict(probe.uname.read_fields),
        } if hasattr(probe, 'uname') else None,
    }

    devices = {}
    for dev_attr in ('gpio', 'kikilog', 'usb_buspower', 'usb_event', 'usb_otgcore', 'hdmi', 'cec', 'mmca_char', 'pipes', 'fb', 'gles'):
        if hasattr(probe, dev_attr):
            val = getattr(probe, dev_attr)
            if val is not None:
                devices[dev_attr] = pickle.dumps(val)
    subsystems['devices'] = devices

    payload = {
        'version': 2,
        'context': ctx_bytes,
        'registers': regs,
        'regions': regions,
        'subsystems': subsystems,
        'resume_state': checkpoint_resume_state(probe),
    }

    raw_bundle = pickle.dumps(payload)
    filepath.write_bytes(raw_bundle)
    return len(raw_bundle)


def restore_checkpoint(probe, filepath: Path, *, exact=False) -> None:
    """Restores Unicorn memory mappings, CPU context, and subsystem states into an initialized probe."""
    filepath = Path(filepath)
    raw_bundle = filepath.read_bytes()
    payload = pickle.loads(raw_bundle)

    if payload.get('version') not in (1, 2):
        raise ValueError(f"Unsupported checkpoint version: {payload.get('version')}")
    if exact and payload.get('version') != 2:
        raise ValueError('Exact resume requires a version-2 checkpoint with recorded stop semantics; use a fresh boot')
    resume = payload.get('resume_state', {})
    if resume.get('retry_error'):
        raise ValueError('Checkpoint cannot safely resume: ' + resume['retry_error'])

    # 1. Unmap all current regions in probe.mu (if any)
    for begin, end, _ in list(probe.mu.mem_regions()):
        try:
            probe.mu.mem_unmap(begin, end - begin + 1)
        except unicorn.UcError:
            pass

    # 2. Restore memory regions and contents
    for reg in payload['regions']:
        begin = reg['begin']
        size = reg['size']
        perms = reg['perms']
        data = zlib.decompress(reg['data'])
        probe.mu.mem_map(begin, size, perms)
        probe.mu.mem_write(begin, data)

    if getattr(probe, 'null_page_policy', None) == 'read-zero':
        try:
            probe.mu.mem_protect(0, 4096, unicorn.UC_PROT_READ)
            probe.mu.mem_write(0, bytes(4096))
        except unicorn.UcError:
            pass

    # 3. Restore Unicorn CPU context and explicit ARM register state (with Thumb/CPSR handling)
    ctx = pickle.loads(payload['context'])
    probe.mu.context_restore(ctx)

    if 'registers' in payload:
        regs = payload['registers']
        for r in ARM_CHECKPOINT_REGS:
            if r not in (arm.UC_ARM_REG_PC, arm.UC_ARM_REG_CPSR):
                probe.mu.reg_write(r, regs[r])
        cpsr = regs[arm.UC_ARM_REG_CPSR]
        probe.mu.reg_write(arm.UC_ARM_REG_CPSR, cpsr)
        pc = regs[arm.UC_ARM_REG_PC]
        if cpsr & 0x20:  # Thumb mode requires LSB set when writing PC in Unicorn
            entry_pc = pc | 1
            probe.mu.reg_write(arm.UC_ARM_REG_PC, entry_pc)
        else:
            entry_pc = pc & ~1
            probe.mu.reg_write(arm.UC_ARM_REG_PC, entry_pc)
        probe.entry = entry_pc

    # 4. Restore Python Subsystem State
    sub = payload['subsystems']
    probe.instructions = sub['instructions']
    runtime = sub.get('runtime') or {}
    if runtime:
        if 'thread_timeslice' in runtime:
            probe.thread_timeslice = runtime['thread_timeslice']
        probe._timeslice_mark = runtime.get('timeslice_mark', probe.instructions)
    probe.signal_handlers = sub['signal_handlers']
    probe.report['serviced_syscalls'] = sub['serviced_syscalls']
    probe.report['syscall_responses_supplied'] = sub['syscall_responses_supplied']
    if 'loaded_modules' in sub:
        probe.report['loaded_modules'] = sub['loaded_modules']

    probe.filesystem.fds = sub['filesystem_fds']
    probe.filesystem.cache = sub['filesystem_cache']

    if sub.get('threads') and hasattr(probe, 'threads'):
        probe.threads = pickle.loads(sub['threads'])
    if sub.get('uipc') and hasattr(probe, 'uipc'):
        probe.uipc = pickle.loads(sub['uipc'])
    if sub.get('sem') and hasattr(probe, 'sem'):
        probe.sem = pickle.loads(sub['sem'])
    elif hasattr(probe, 'sem') and not getattr(probe, 'sem', None):
        probe.sem = GuestSem()

    if sub.get('heap') and hasattr(probe, 'heap'):
        probe.heap.current = sub['heap']['current']
        probe.heap.start = sub['heap']['start']
        probe.heap.ceiling = sub['heap']['ceiling']

    if sub.get('mmap') and hasattr(probe, 'mmap'):
        probe.mmap.next_address = sub['mmap']['next_address']
        probe.mmap.mapped_pages = set(sub['mmap']['mapped_pages'])
        probe.mmap.page_backing = dict(sub['mmap']['page_backing'])
        probe.mmap.mappings = list(sub['mmap']['mappings'])
        probe.mmap.base_address = sub['mmap']['base_address']
        probe.mmap.ceiling_address = sub['mmap']['ceiling_address']
        probe.mmap.search_low_base = sub['mmap']['search_low_base']

    if sub.get('stream_mappings') and hasattr(probe, 'stream') and hasattr(probe.stream, 'mappings'):
        probe.stream.mappings = sub['stream_mappings']

    if sub.get('stream') and getattr(probe, 'stream', None) is not None:
        probe.stream.from_state(sub['stream'])
    if sub.get('display') and getattr(probe, 'display', None) is not None:
        probe.display.from_state(sub['display'])
        if not probe.display.installed_ranges:
            probe._install_display_write_hooks()
    if getattr(probe, 'display', None) is not None and not probe.display.mappings:
        # Older checkpoints predate the persisted display/stream state.  The
        # mmap table still carries the verified device entries; use only those,
        # never an invented virtual address.  Register every /dev/stream
        # mapping so OSD A/B remain visible to the display contract.
        stream_entries = [entry for entry in getattr(probe.mmap, 'mappings', [])
                          if entry.get('device') == 'stream' and entry.get('address') is not None]
        for entry in stream_entries:
            probe.display.register_mapping(int(entry['address']), int(entry['length']),
                                           int(entry['physical_start']), 'stream')
        preferred = next((entry for entry in stream_entries
                          if entry.get('physical_start') == 0x202E0000), None)
        if preferred is not None and getattr(probe, 'stream', None) is not None and probe.stream.mapping is None:
            probe.stream.mapping = {'virtual_start': int(preferred['address']),
                                    'physical_start': int(preferred['physical_start']),
                                    'length': int(preferred['length']), 'pgoff': None,
                                    'prot': int(preferred.get('prot', 3))}
            probe.stream.mappings = [probe.stream.mapping]
        if stream_entries:
            probe._install_display_write_hooks()

    if sub.get('stat64') and hasattr(probe, 'stat64'):
        probe.stat64.bytes = sub['stat64']['bytes']
        probe.stat64.read_fields = sub['stat64']['read_fields']

    if sub.get('uname') and hasattr(probe, 'uname'):
        probe.uname.bytes = sub['uname']['bytes']
        probe.uname.read_fields = sub['uname']['read_fields']

    for dev_attr, dev_bytes in sub.get('devices', {}).items():
        setattr(probe, dev_attr, pickle.loads(dev_bytes))

    if getattr(probe, 'null_page_policy', None) == 'read-zero':
        try:
            probe.mu.mem_protect(0, 4096, unicorn.UC_PROT_READ)
        except unicorn.UcError:
            pass
        probe.mu.mem_write(0, bytes(4096))
        def _null_page_read_guard(uc, access, address, size, value, user_data):
            if address < 16:
                uc.mem_write(0, bytes(16))
        probe.mu.hook_add(unicorn.UC_HOOK_MEM_READ, _null_page_read_guard, begin=0, end=16)
        def _null_page_write_guard(uc, access, address, size, value, user_data):
            return True
        probe.mu.hook_add(unicorn.UC_HOOK_MEM_WRITE_PROT, _null_page_write_guard, begin=0, end=4095)
        def _null_page_keep_zero(uc, access, address, size, value, user_data):
            if address < 16:
                uc.mem_write(0, bytes(16))
        probe.mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, _null_page_keep_zero, begin=0, end=15)

    retry_pc = resume.get('retry_pc')
    if retry_pc is not None:
        thumb = bool(probe.mu.reg_read(arm.UC_ARM_REG_CPSR) & 0x20)
        probe.entry = retry_pc | int(thumb)
        probe.mu.reg_write(arm.UC_ARM_REG_PC, probe.entry)
        if getattr(probe, 'threads', None) is not None:
            probe.threads.save_context(probe.mu)
    if hasattr(probe, 'rearm_checkpoint_hooks'):
        probe.rearm_checkpoint_hooks()
    probe.report['checkpoint_resume'] = {'version': payload['version'], 'exact': exact,
                                         **resume}
