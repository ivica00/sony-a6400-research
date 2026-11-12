"""Execute original process code with explicit contracts; stop on unsupported requests."""
from collections import deque
import hashlib
import struct

import unicorn
from unicorn import arm_const as arm

from src.a6400.images.process_elf import map_image
from src.a6400.execution.process_entry import build_stack
from src.a6400.execution.guest_brk import GuestBrk, initial_break
from src.a6400.execution.guest_uname import GuestUname, UnverifiedIdentityData
from src.a6400.execution.guest_memory import cstring_preview, accessible
from src.a6400.execution.guest_stat64 import GuestStat64
from src.a6400.execution.guest_filesystem import GuestFilesystem, UnsupportedFilesystem
from src.a6400.execution.guest_mmap import GuestMmap, UnsupportedMmap
from src.a6400.execution.guest_kuser import GuestKuser
from src.a6400.execution.guest_uipc import GuestUipc, UnsupportedUipc
from src.a6400.execution.guarded_bytes import UnverifiedGuestData
from src.a6400.execution.guest_stdio import GuestStdio
from src.a6400.execution.guest_threads import GuestThreads, REGISTER_LIST, EXPECTED_PTHREAD_CLONE_FLAGS
from src.a6400.execution.guest_fb import GuestFramebuffer
from src.a6400.execution.guest_stream import GuestStream, UnsupportedStream
from src.a6400.execution.guest_gles import GuestGles, UnsupportedGles, GLES_LOCK_SEMAPHORE
from src.a6400.execution.guest_gpio import GuestGpio, UnsupportedGpio
from src.a6400.execution.guest_kikilog import UnsupportedKikilog
from src.a6400.execution.guest_usb_buspower import GuestUsbBusPower, UnsupportedUsbBusPower
from src.a6400.execution.guest_usb_event import GuestUsbEvent, UnsupportedUsbEvent
from src.a6400.execution.guest_usb_otgcore import GuestUsbOtgCore, UnsupportedUsbOtgCore
from src.a6400.execution.guest_nflasha4 import Nflasha4Dump, Nflasha4DumpError
from src.a6400.execution.guest_hdmi import GuestHdmi, UnsupportedHdmi
from src.a6400.execution.guest_cec import GuestCec, UnsupportedCec
from src.a6400.execution.guest_mmca_char import GuestMmcChar, UnsupportedMmcChar, MMC_CHAR_NODES
from src.a6400.execution.guest_pipe import GuestPipe, UnsupportedPipe, POLLNVAL, POLLERR, POLLHUP
from src.a6400.execution.guest_sem import GuestSem
from src.a6400.execution.guest_display import DisplayModel, display_contract
from src.a6400.execution.kernel_task_identity import UnsupportedKernelBinding


def summarize_loader_stop(serviced_syscalls, stderr_text, boundary=None):
    """Read-only summary of the guest dynamic-loader stop state."""
    undefined = None
    if 'undefined symbol:' in stderr_text:
        tail = stderr_text.split('undefined symbol:', 1)[1].strip()
        undefined = tail.split()[0] if tail else None
    exits = [event for event in serviced_syscalls
             if event.get('syscall') in ('exit', 'exit_group')]
    boundary_exit = None
    if boundary and boundary.get('r7') in (1, 248):
        arguments = boundary.get('arguments') or []
        boundary_exit = {
            'syscall': 'exit_group' if boundary['r7'] == 248 else 'exit',
            'status': arguments[0] if arguments else None,
        }
    libraries = {}
    for event in serviced_syscalls:
        path = event.get('path')
        if not path:
            path = (event.get('mapping') or {}).get('path')
        if not path or not any(name in path for name in
                               ('libObj.so', 'dataflowInfraFramework.so', 'ld-linux')):
            continue
        entry = {'syscall': event.get('syscall'), 'returned': event.get('returned')}
        if event.get('resolved_path'):
            entry['resolved_path'] = event['resolved_path']
        mapping = event.get('mapping') or {}
        for field in ('base', 'offset', 'size', 'sha256'):
            if field in mapping:
                entry[field] = mapping[field]
        libraries.setdefault(path, []).append(entry)
    return {
        'symbol_lookup_error': 'symbol lookup error' in stderr_text,
        'undefined_symbol': undefined,
        'last_exit': exits[-1] if exits else None,
        'boundary_exit': boundary_exit,
        'libraries': libraries,
    }


# ---------------------------------------------------------------------------
# USB dispatch observability (observe-only; E0332 follow-up).
#
# Evidence: the original `UsbControl::DispatchEvent` chain calls
# `MWF::ObjMsg::GetMessageId`, then `UsbControl::MsgId2EventId`, then
# `UFW::Fsm::DispatchEvent(this+0xF4, eventId, msg)` (E0323/E0324).  Live VAs
# are `resumed module base + ELF .dynsym st_value`; the module base is resolved
# from the resumed checkpoint's mmap mapping table at install time, never from
# a hardcoded live VA.  The hooks below only read registers/memory and append
# report records: guest execution is never changed.
# ---------------------------------------------------------------------------
MODULE_PAGE_SIZE = 0x1000
USB_CONTROL_DISPATCH_SYMBOLS = (
    {'function': 'UsbControl::ProcessMsg',
     'module': 'libUsbControl.so',
     'symbol': '_ZN10UsbControl10ProcessMsgEjPN3MWF6ObjMsgE',
     'arg_registers': (('this', arm.UC_ARM_REG_R0),
                       ('unsigned_arg', arm.UC_ARM_REG_R1),
                       ('msg', arm.UC_ARM_REG_R2)),
     'objmsg_argument': 'msg',
     'returns': None},
    {'function': 'MWF::ObjMsg::GetMessageId',
     'module': 'libMWF.so',
     'symbol': '_ZNK3MWF6ObjMsg12GetMessageIdEv',
     'arg_registers': (('objmsg', arm.UC_ARM_REG_R0),),
     'objmsg_argument': 'objmsg',
     'returns': 'message_id'},
    {'function': 'UsbControl::MsgId2EventId',
     'module': 'libUsbControl.so',
     'symbol': '_ZN10UsbControl13MsgId2EventIdEj',
     'arg_registers': (('this', arm.UC_ARM_REG_R0),
                       ('message_id', arm.UC_ARM_REG_R1)),
     'objmsg_argument': None,
     'returns': 'event_id'},
    {'function': 'UFW::Fsm::DispatchEvent',
     'module': 'libUsbControl.so',
     'symbol': '_ZN3UFW3Fsm13DispatchEventEiPv',
     'arg_registers': (('this', arm.UC_ARM_REG_R0),
                       ('event_id', arm.UC_ARM_REG_R1),
                       ('msg', arm.UC_ARM_REG_R2)),
     'objmsg_argument': 'msg',
     'returns': None},
)
# Evidence copies whose .dynsym values were used to decode the dispatch chain.
USB_CONTROL_DISPATCH_EVIDENCE_LIBS = {
    'libUsbControl.so': 'artifacts/hardware/live-libs/libUsbControl.so',
    'libMWF.so': 'artifacts/hardware/live-libs/libMWF.so',
}


def normalise_packet_hex(packet_hex):
    """Validate an explicit packet-hex injection payload.

    Accepts ``bytes``/``bytearray`` or a hex ``str`` (spaces, underscores and a
    ``0x`` prefix are tolerated).  Returns ``(payload_bytes, canonical_hex)``.
    Raises ValueError for empty, odd-length or non-hex input: an explicit
    packet override must never be silently truncated or zero-filled.
    """
    if packet_hex is None:
        raise ValueError('packet_hex must not be None')
    if isinstance(packet_hex, (bytes, bytearray)):
        data = bytes(packet_hex)
    elif isinstance(packet_hex, str):
        text = packet_hex.strip().replace(' ', '').replace('_', '')
        if text[:2].lower() == '0x':
            text = text[2:]
        try:
            data = bytes.fromhex(text)
        except ValueError as error:
            raise ValueError('packet_hex must be a hex string: %s' % (error,))
    else:
        raise ValueError('packet_hex must be bytes or a hex string')
    if not data:
        raise ValueError('packet_hex must not be empty')
    return data, data.hex()


def module_mapping_entries(module_name, mappings):
    """Return resumed mmap entries whose guest path basename is ``module_name``."""
    entries = []
    for entry in mappings or []:
        path = entry.get('path') if isinstance(entry, dict) else None
        if not path:
            continue
        if str(path).replace('\\', '/').rsplit('/', 1)[-1] == module_name:
            entries.append(entry)
    return entries


def resumed_module_base(module_name, mappings, load_segments):
    """Resolve a resumed shared-module load base from mmap entries + PT_LOAD rows.

    ``mappings`` are the checkpoint's ``probe.mmap.mappings`` dicts (guest path,
    address, file offset); ``load_segments`` are PT_LOAD rows with
    ``file_offset``/``vaddr``.  The base is the address the ELF's ``st_value``
    offsets are relative to: for every file-backed mapping the loader mapped
    ``base + (p_vaddr & ~PAGE)`` at file offset ``p_offset & ~PAGE``, so a
    single consistent base is recovered (and cross-checked across mappings).
    No live VA is assumed.
    """
    entries = module_mapping_entries(module_name, mappings)
    if not entries:
        raise ValueError('module_not_mapped')
    candidates = []
    for entry in entries:
        try:
            offset = int(entry.get('offset') or 0)
            address = int(entry['address'])
        except (KeyError, TypeError, ValueError):
            raise ValueError('mapping_entry_incomplete')
        segment = next((row for row in (load_segments or [])
                        if (int(row.get('file_offset', -1)) & ~(MODULE_PAGE_SIZE - 1))
                        == (offset & ~(MODULE_PAGE_SIZE - 1))), None)
        if segment is None:
            continue
        candidates.append({
            'base': address - (int(segment['vaddr']) & ~(MODULE_PAGE_SIZE - 1)),
            'mapping_address': address,
            'mapping_offset': offset,
            'segment_vaddr': int(segment['vaddr']),
            'segment_file_offset': int(segment['file_offset']),
        })
    if not candidates:
        raise ValueError('mapping_segment_unmatched')
    bases = {candidate['base'] for candidate in candidates}
    if len(bases) != 1:
        raise ValueError('inconsistent_module_base: %s' % (
            sorted(hex(item) for item in bases),))
    base = candidates[0]['base']
    if base % MODULE_PAGE_SIZE:
        raise ValueError('unaligned_module_base: 0x%08x' % (base,))
    return {'base': base, 'module': module_name,
            'path': entries[0].get('path'),
            'mappings': candidates}


def inspect_elf_load_and_symbols(elf_bytes, symbol_names):
    """Return ``(PT_LOAD rows, .dynsym values)`` for an ELF image's bytes.

    Observe-only static decode of the module the guest actually loaded; raises
    ValueError when the image has no readable ELF section/dynsym data.
    """
    import io
    try:
        from elftools.elf.elffile import ELFFile
    except ImportError as error:  # pragma: no cover - environment dependent
        raise ValueError('pyelftools_unavailable: %s' % (error,))
    elf = ELFFile(io.BytesIO(bytes(elf_bytes)))
    segments = []
    for segment in elf.iter_segments():
        if segment['p_type'] != 'PT_LOAD':
            continue
        segments.append({'file_offset': int(segment['p_offset']),
                         'vaddr': int(segment['p_vaddr']),
                         'file_size': int(segment['p_filesz']),
                         'memory_size': int(segment['p_memsz'])})
    if not segments:
        raise ValueError('elf_without_load_segments')
    section = elf.get_section_by_name('.dynsym')
    if section is None:
        raise ValueError('elf_without_dynsym')
    wanted = set(symbol_names)
    symbols = {}
    for symbol in section.iter_symbols():
        if symbol.name and symbol.name in wanted:
            symbols[symbol.name] = {
                'value': int(symbol['st_value']),
                'size': int(symbol['st_size']),
                'defined': symbol['st_shndx'] != 'SHN_UNDEF',
            }
    return segments, symbols


class InterpreterProbe:
    def __init__(self, syscall_policy='stop', uname_profile=None, filesystem=None, kuser_template=None,
                 madvise_policy='stop', backup_service_policy='unverified-ack',
                 graphics_service_policy='stop', null_page_policy='stop',
                 kmod_service_policy='stop',
                 media_service_policy='stop', hook_mode='instruction',
                 mmap_base=None, mmap_ceiling=None, mmap_search_low=None,
                 display_profile=None, grm_pool_policy='gl-common-only',
                 mmap_eof_policy='zero-fill'):
        if mmap_eof_policy not in ('zero-fill', 'sigbus'):
            raise ValueError('Unknown mmap EOF policy')
        self.mmap_eof_policy = mmap_eof_policy
        if null_page_policy not in ('stop', 'read-zero'):
            raise ValueError('Unknown null page policy')
        self.null_page_policy = null_page_policy
        if hook_mode not in ('instruction', 'fast'):
            raise ValueError('Unknown hook mode')
        self.hook_mode = hook_mode
        if backup_service_policy not in ('stop', 'unverified-ack', 'preset-backed'):
            raise ValueError('Unknown backup service policy')
        if graphics_service_policy not in ('stop', 'authentic-grm'):
            raise ValueError('Unknown graphics service policy')
        if kmod_service_policy not in ('stop', 'verified-image'):
            raise ValueError('Unknown kmod service policy')
        self.kmod_service_policy = kmod_service_policy
        if media_service_policy not in ('stop', 'authentic-sd'):
            raise ValueError('Unknown media service policy')
        self.media_service_policy = media_service_policy
        self.graphics_service_policy = graphics_service_policy
        if madvise_policy not in ('stop', 'private-anonymous-dontneed'):
            raise ValueError('Unknown madvise policy')
        if madvise_policy != 'stop' and syscall_policy not in ('mmap', 'kuser', 'uipc', 'threads'):
            raise ValueError('madvise requires a guest mmap policy')
        self.madvise_policy = madvise_policy
        # Opt-in deterministic timer preemption (E0473): 0 keeps the historical
        # cooperative scheduling; a positive value switches a running thread to
        # a runnable peer every N guest instructions.
        self.thread_timeslice = 0
        self._timeslice_mark = 0
        self._stop_instruction_limit = 0
        # Opt-in cooperative yield when a non-blocking UIPC poll finds no
        # message (safe syscall-boundary switch; no arbitrary preemption).
        self.thread_poll_yield = False
        # Opt-in observe-only hooks on the original UsbControl dispatch chain
        # (UsbControl::ProcessMsg / MWF::ObjMsg::GetMessageId /
        # UsbControl::MsgId2EventId / UFW::Fsm::DispatchEvent).  Disabled by
        # default and never changes registers or memory.
        self.trace_usbcontrol_dispatch = False
        self.usbcontrol_dispatch_max_hits = 2000
        self._usbcontrol_dispatch_installed = False
        self._usbcontrol_dispatch_pending = {}
        self._usbcontrol_dispatch_return_hooks = {}
        if syscall_policy not in ('stop', 'brk', 'brk-uname', 'files', 'metadata', 'mmap', 'kuser', 'uipc', 'threads'):
            raise ValueError('Unknown syscall policy')
        if syscall_policy in ('brk-uname', 'files', 'metadata', 'mmap', 'kuser', 'uipc', 'threads') and uname_profile is None:
            raise ValueError('The uname policy requires an explicit kernel-backed identity profile')
        if syscall_policy in ('files', 'metadata', 'mmap', 'kuser', 'uipc', 'threads') and filesystem is None:
            raise ValueError('The files policy requires an explicit image-backed namespace')
        self.syscall_policy = syscall_policy
        self.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
        self.mu.reg_write(arm.UC_ARM_REG_FPEXC, 0x40000000)
        self.report = {'schema_version': 1, 'status': 'not_started', 'camera_fidelity_validated': False,
                       'cpu': 'Cortex-A9: provisional experimental choice, not verified camera CPU',
                       'syscall_responses_supplied': 0,
                       'syscall_policy': syscall_policy, 'serviced_syscalls': [],
                       'assumptions': ['4 KiB pages; fixed interpreter/stack addresses; ASLR disabled.',
                                       'argv/environment are explicit experiment inputs; normal camera arguments are unknown.',
                                       'UID/GID zero, AT_SECURE=0, HWCAP=0, platform=v7l, clock tick=100 are experimental inputs.',
                                       'AT_RANDOM uses deterministic bytes for reproducibility, not camera entropy.',
                                       'No kernel, kuser helpers, VDSO, devices, IPC, or writable files are implemented.',
                                       'Optional brk contract: ASLR disabled; page-aligned initial break; 64 MiB growth ceiling, not recovered camera RLIMIT_DATA.']}
        self.instructions = 0
        self._progress_interval = 0
        self._on_progress = None
        self.display = None
        if display_profile is not None:
            profile = (display_profile if isinstance(display_profile, dict)
                       else display_contract(display_profile))
            self.display = DisplayModel(profile)
            self.report['display_contract'] = profile.get('name')
        self._pause_requested = False
        self._run_open = False
        self._usb_connect_record = None
        self._usb_connect_at = 0
        self._usb_connect_attempts = 0
        if madvise_policy != 'stop':
            self.report['assumptions'].append('Optional MADV_DONTNEED: only owned private anonymous pages; eager zeroing models later zero-fill reads, not RSS, physical reclaim or timing.')
        self.prepared = False
        self.prepare_attempted = False
        self.tail = deque(maxlen=32)
        self.signal_handlers = {}
        if self.hook_mode == 'fast':
            self.mu.hook_add(unicorn.UC_HOOK_BLOCK, self._block)
            for it_addr in (0x40004e4c, 0x50259c24, 0x50034e32, 0x50034e6a, 0x4000a6f4,
                            0x5026ebc4, 0x5026ec26, 0x54194e4e,
                            0x50259bf2, 0x50259bfc, 0x50259c00, 0x54194e56,
                            0x5026ed06, 0x5026ecfc):
                self.mu.hook_add(unicorn.UC_HOOK_CODE, self._it_workaround, begin=it_addr, end=it_addr)
            self.mu.hook_add(unicorn.UC_HOOK_CODE, self._ld_fixup_workaround,
                             begin=0x4000a6f4, end=0x4000a6f4)
        else:
            self.mu.hook_add(unicorn.UC_HOOK_CODE, self._code)
        self.mu.hook_add(unicorn.UC_HOOK_INTR, self._interrupt)
        self.mu.hook_add(unicorn.UC_HOOK_MEM_INVALID, self._memory)
        self.mu.hook_add(unicorn.UC_HOOK_INSN_INVALID, self._invalid_insn)
        if syscall_policy in ('brk-uname', 'files', 'metadata', 'mmap', 'kuser', 'uipc', 'threads'):
            self.uname = GuestUname(self.mu, uname_profile, self._identity_boundary)
            self.report['uname_profile'] = uname_profile
            self.report['assumptions'].append('uname uses image-backed compiled defaults and default Linux personality; reads of nodename, machine, or domainname stop execution.')
        if syscall_policy in ('metadata', 'mmap', 'kuser', 'uipc', 'threads'):
            known = ('st_dev',) if syscall_policy in ('mmap', 'kuser', 'uipc', 'threads') else ()
            regular_rdev = filesystem.get('regular_inode_rdev', False)
            self.stat64 = GuestStat64(self.mu, self._identity_boundary, self._after_host_write,
                                      known_fields=known, regular_inode_rdev=regular_rdev,
                                      readonly_image_times=filesystem.get('readonly_image_times', False))
            if filesystem.get('readonly_image_times', False):
                self.report['assumptions'].append('Optional read-only ext2 image timestamps: select preserved image inode times under read-only mount records; no remount, writes or runtime overlay state supplied. This is not a camera mount observation.')
                self.report['inode_timestamp_policy'] = 'readonly-ext2-image'
            if regular_rdev:
                self.report['assumptions'].append('Optional regular-inode st_rdev: zero from original inode initialization and ext2 regular-file semantics; special nodes and runtime timestamps remain guarded.')
                self.report['inode_rdev_policy'] = 'regular-image-inodes'
            if syscall_policy == 'metadata':
                self.report['assumptions'].append('Partial ARM EABI stat64 uses image inode metadata; device numbers and runtime timestamps are guarded and cannot be consumed.')
            else:
                self.report['assumptions'].append('Partial ARM EABI stat64 uses image inode metadata and verified major 252 device numbers; timestamps remain guarded.')
        if syscall_policy in ('files', 'metadata', 'mmap', 'kuser', 'uipc', 'threads'):
            self.filesystem = GuestFilesystem(self.mu, filesystem['nodes'], filesystem['content_loader'],
                                              before_read=self._before_host_read,
                                              after_write=self._after_host_write,
                                              stat_contract=getattr(self, 'stat64', None),
                                              urandom_open=filesystem.get('urandom_open', False),
                                              urandom_entropy_policy=filesystem.get('urandom_entropy_policy', 'stop'),
                                              tmp_overlay=filesystem.get('tmp_overlay', 'stop'),
                                              proc_overlay=filesystem.get('proc_overlay', 'stop'),
                                              setting_overlay=filesystem.get('setting_overlay', 'stop'),
                                              **({'unknown_roots': filesystem['unknown_roots']}
                                                 if 'unknown_roots' in filesystem else {}))
        if filesystem and filesystem.get('urandom_open'):
            if filesystem.get('urandom_entropy_policy') == 'deterministic':
                self.report['assumptions'].append('Optional urandom-entropy deterministic: static image node 1:9 open and deterministic 4-byte stack canary entropy supplied; not physical hardware randomness.')
                self.report['urandom_entropy_policy'] = 'deterministic'
            else:
                self.report['assumptions'].append('Optional urandom-open: static image node 1:9 and compiled driver registration assumed available; entropy reads stop without supplying bytes.')
        if syscall_policy in ('mmap', 'kuser', 'uipc', 'threads'):
            mmap_kwargs = {'after_write': self._after_host_write, 'eof_policy': self.mmap_eof_policy}
            if mmap_base is not None:
                mmap_kwargs['base_address'] = mmap_base
            if mmap_ceiling is not None:
                mmap_kwargs['ceiling_address'] = mmap_ceiling
            if mmap_search_low is not None:
                mmap_kwargs['search_low_base'] = mmap_search_low
            self.mmap = GuestMmap(self.mu, self.filesystem, **mmap_kwargs)
            self.report['mmap_eof_policy'] = self.mmap_eof_policy
            self.report['assumptions'].append('Optional mmap contract: ARM EABI mmap2/mprotect/munmap allocate page-aligned guest memory from verified files or anonymous pages.')
        if syscall_policy in ('kuser', 'uipc', 'threads'):
            if kuser_template is None:
                raise ValueError('The kuser policy requires a verified kuser helper template')
            self.kuser = GuestKuser(self.mu, kuser_template)
            self.report['assumptions'].append('ARM Linux high vectors page at 0xffff0000 with kernel helper template (version 5) and set_tls contract.')
        if syscall_policy in ('uipc', 'threads'):
            if grm_pool_policy not in ('gl-common-only', 'captured-e0044'):
                raise ValueError('Unknown GRM pool policy')
            uipc_options = {'backup_service_policy': backup_service_policy,
                            'graphics_service_policy': graphics_service_policy,
                            'media_service_policy': media_service_policy}
            if graphics_service_policy == 'authentic-grm' and grm_pool_policy != 'gl-common-only':
                from src.a6400.execution.grm_service import GrmMaService
                uipc_options['grm_service'] = GrmMaService(pool_policy=grm_pool_policy)
            self.uipc = GuestUipc(**uipc_options)
            self.report['media_service_policy'] = media_service_policy
            self.report['backup_service_policy'] = backup_service_policy
            self.report['graphics_service_policy'] = graphics_service_policy
            self.report['grm_pool_policy'] = grm_pool_policy
            if graphics_service_policy == 'authentic-grm':
                self.report['assumptions'].append('Graphics service: authentic-grm verified gl_common pool and allocation.')
            self.report['assumptions'].append('Other synchronous UIPC acknowledgements remain experimental transport responses; recipient execution and service semantics are not established.')
            if backup_service_policy == 'stop':
                self.report['assumptions'].append('Backup service: stop before replying to queue 0x003e014d; runtime settings are unsupplied.')
            elif backup_service_policy == 'preset-backed':
                self.report['assumptions'].append('Backup service: preset-backed verified BK4 preset; authentic operations and RAM mutations.')
            else:
                self.report['assumptions'].append('Backup service: historical unverified acknowledgement of queue 0x003e014d; no recipient executes and zero-initialized reply fields are not camera data.')
            self.stdio = GuestStdio()
            self.fb = GuestFramebuffer()
            self.pipes = GuestPipe()
            self.sem = GuestSem()
            if filesystem.get('stream_profile') is not None:
                self.stream = GuestStream(self.mu, self.mmap, filesystem['stream_profile'],
                                          self._identity_boundary, self._after_host_write)
                self.report['assumptions'].append('Optional image-driver /dev/stream: selected compiled 249:7 registration/reset; ioctl reports modeled mapping delta; physical contents remain unsupplied and guarded. Single mapping, no aliases or DMA.')
            self.report['assumptions'].append('/dev/uipc character device contract (commands connect, valloc, snd_sync_msg, free, reg_msg_queue_cb, snd_sync_direct), /dev/fb0 framebuffer contract (FBIOGET/PUT_VSCREENINFO, FBIOGET_FSCREENINFO, mmap), and standard I/O streams backed by /dev/console.')
        if syscall_policy == 'threads':
            self.threads = GuestThreads(initial_tid=1000)
            self.report['thread_context_contract'] = 'clone copies general-register syscall-return context; guest libc owns thread dispatch/exit; hardware/software TLS restored; VFP state not yet isolated'
            self.report['assumptions'].append('Linux ARM NPTL multithreading: sys_clone, sys_futex (WAIT/WAKE), sys_gettid, sys_prctl (PR_SET_NAME), sched_setscheduler, sched_setaffinity, and cooperative thread scheduling.')

    def prepare(self, application, interpreter, argv, interpreter_bias=0x40000000,
                stack_bottom=0x7fe00000, stack_size=0x100000, environment=None):
        if self.prepare_attempted:
            raise ValueError('Use a fresh probe for each preparation attempt')
        self.prepare_attempted = True
        if application['type'] != 'ET_EXEC' or interpreter['type'] != 'ET_DYN':
            raise ValueError('This experiment requires ET_EXEC application and ET_DYN interpreter')
        environment = list(environment or [])
        app = map_image(self.mu, application, 0)
        linker = map_image(self.mu, interpreter, interpreter_bias)
        self.mu.mem_map(stack_bottom, stack_size, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
        stack = build_stack(stack_bottom, stack_size, argv, environment, app, interpreter_bias)
        self.mu.mem_write(stack_bottom, stack['data'])
        # Start in user mode, not Unicorn's default privileged context.
        self.mu.reg_write(arm.UC_ARM_REG_CPSR, 0x10)
        self.mu.reg_write(arm.UC_ARM_REG_SP, stack['sp'])
        self.mu.reg_write(arm.UC_ARM_REG_R0, 0)
        # Older ARM start_thread seeds r1/r2 from stack words 1/2; libc treats
        # these as undefined. r0 is zero after the successful execve return.
        _, initial_r1, initial_r2 = struct.unpack_from('<3I', stack['data'], stack['sp'] - stack_bottom)
        self.mu.reg_write(arm.UC_ARM_REG_R1, initial_r1)
        self.mu.reg_write(arm.UC_ARM_REG_R2, initial_r2)
        self.entry = linker['entry']
        self.report.update(interpreter_mapping=linker, application_mapping=app,
                           stack={'bottom': stack_bottom, 'size': stack_size, 'sp': stack['sp'],
                                  'initial_r1': initial_r1, 'initial_r2': initial_r2,
                                  'auxv': stack['auxv'], 'argc': stack['argc'],
                                  'argv': stack['argv'], 'environment': stack['environment']},
                           entry=self.entry)
        if self.syscall_policy in ('brk', 'brk-uname', 'files', 'metadata', 'mmap', 'kuser', 'uipc', 'threads'):
            self.heap = GuestBrk(self.mu, initial_break(application))
            self.report['heap'] = {'initial': self.heap.start, 'ceiling': self.heap.ceiling}
        if hasattr(self, 'mmap'):
            for mapping in app['mappings']:
                self.mmap.register_range(mapping['address'], mapping['size'])
            for mapping in linker['mappings']:
                self.mmap.register_range(mapping['address'], mapping['size'])
            self.mmap.register_range(stack_bottom, stack_size)
        if hasattr(self, 'kuser'):
            self.kuser.map_page()
        if self.null_page_policy == 'read-zero':
            self.mu.mem_map(0, 4096, unicorn.UC_PROT_READ)
            self.mu.mem_write(0, bytes(4096))

            def _null_page_read_guard(uc, access, address, size, value, user_data):
                if address < 16:
                    uc.mem_write(0, bytes(16))
            self.mu.hook_add(unicorn.UC_HOOK_MEM_READ, _null_page_read_guard, begin=0, end=16)

            def _null_page_write_guard(uc, access, address, size, value, user_data):
                return True
            self.mu.hook_add(unicorn.UC_HOOK_MEM_WRITE_PROT, _null_page_write_guard, begin=0, end=4095)

            def _null_page_keep_zero(uc, access, address, size, value, user_data):
                if address < 16:
                    uc.mem_write(0, bytes(16))
            self.mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, _null_page_keep_zero, begin=0, end=15)
        self.prepared = True

    def _it_workaround(self, uc, address, size, user_data):
        # Live-build-specific repairs are signature-guarded so extracted runs are
        # byte-for-byte unaffected when the live instruction is not present.
        guarded = (
            (0x54194E4E, 0x54194E4C, b'\x03\x4b\x04\x4a'),
            (0x54194E56, 0x54194E4C, b'\x03\x4b\x04\x4a'),
            (0x50259BFC, 0x50259BFC, b'\xdf\xf8\x94\x24'),
            (0x5026ED06, 0x5026ED06, b'\x70\xbd'),
            (0x5026ECFC, 0x5026ECF6, b'\x84\xbf\x1c\x60\x22\x46'),
        )
        for guarded_address, signature_address, signature in guarded:
            if address == guarded_address:
                try:
                    current = bytes(uc.mem_read(signature_address, len(signature)))
                except Exception:
                    return
                if current != signature:
                    return
                break
        if self.syscall_policy in ('mmap', 'kuser', 'uipc', 'threads'):
            cpsr = uc.reg_read(arm.UC_ARM_REG_CPSR)
            if cpsr & ((3 << 25) | (0x3f << 10)):
                uc.reg_write(arm.UC_ARM_REG_CPSR, cpsr & ~((3 << 25) | (0x3f << 10)))
        if address == 0x50259BFC:
            # Live libc 8.2.6.0 top-split (`ldr.w r2,[pc,#0x494]`): Unicorn can
            # skip this 4-byte literal load after an IT latch, leaving the stale
            # top-chunk size instead of &main_arena and tagging a main-arena
            # chunk NON_MAIN_ARENA.  Only repair when the live signature (F8DF
            # 2494) is present, so extracted-build libc is unaffected.
            try:
                signature = bytes(uc.mem_read(0x50259BFC, 4))
            except Exception:
                return
            if signature == b'\xdf\xf8\x94\x24':
                try:
                    literal = int.from_bytes(bytes(uc.mem_read(0x5025A094, 4)), 'little')
                except Exception:
                    return
                uc.reg_write(arm.UC_ARM_REG_R2, literal)
                self.report['live_libc_it_repair_hits'] = self.report.get('live_libc_it_repair_hits', 0) + 1
        if address == 0x54194E56:
            # Live libObj 8.2.6.0 helper: if the 16-bit literal load at +0x104E4E
            # was skipped entirely (Unicorn IT latch, hook can be bypassed),
            # repair r2 from the guest literal before the faulting
            # `ldr r3,[r3,r2]`.  Signature-guarded to the live helper only.
            try:
                signature = bytes(uc.mem_read(0x54194E4C, 4))
            except Exception:
                return
            if signature == b'\x03\x4b\x04\x4a':
                try:
                    literal = int.from_bytes(bytes(uc.mem_read(0x54194E60, 4)), 'little')
                except Exception:
                    return
                if uc.reg_read(arm.UC_ARM_REG_R2) != literal:
                    uc.reg_write(arm.UC_ARM_REG_R2, literal)
                self.report['live_libobj_it_repair56_hits'] = self.report.get('live_libobj_it_repair56_hits', 0) + 1
        if address == 0x54194E4E:
            # Live libObj 8.2.6.0 (sha256 e88b7e0f...) helper at +0x104E4C:
            # Unicorn can skip the 16-bit `ldr r2,[pc,#0x10]` after an IT block,
            # leaving a stale caller r2.  Only repair when the live signature is
            # present, so extracted-build runs are unaffected.
            try:
                signature = bytes(uc.mem_read(0x54194E4C, 4))
            except Exception:
                return
            if signature == b'\x03\x4b\x04\x4a':
                try:
                    literal = int.from_bytes(bytes(uc.mem_read(0x54194E60, 4)), 'little')
                except Exception:
                    return
                uc.reg_write(arm.UC_ARM_REG_R2, literal)
                self.report['live_libobj_it_repair_hits'] = self.report.get('live_libobj_it_repair_hits', 0) + 1

    def _arm_relocated_libc_repair(self, event):
        """Arm the libc top-split IT-latch repair at whatever base libc was mapped.

        The fixed-address repair in _it_workaround only covers base 0x50200000. Same byte
        signature guard; the hook sits on the instruction AFTER the literal load and only
        writes r2 when it differs from the literal, counting every such skip.
        """
        mapping = event.get('mapping') or {}
        base = event.get('returned')
        if (self.hook_mode != 'fast' or mapping.get('offset') != 0 or base == 0x50200000
                or not str(mapping.get('path', '')).endswith('/libc-2.11.2.so')):
            return
        try:
            if bytes(self.mu.mem_read(base + 0x59bfc, 4)) != bytes.fromhex('dff89424'):
                return
            literal = int.from_bytes(bytes(self.mu.mem_read(base + 0x5a094, 4)), 'little')
        except unicorn.UcError:
            return

        def repair(uc, address, size, user_data):
            cpsr = uc.reg_read(arm.UC_ARM_REG_CPSR)
            if cpsr & ((3 << 25) | (0x3f << 10)):
                uc.reg_write(arm.UC_ARM_REG_CPSR, cpsr & ~((3 << 25) | (0x3f << 10)))
            if uc.reg_read(arm.UC_ARM_REG_R2) != literal:
                uc.reg_write(arm.UC_ARM_REG_R2, literal)
                self.report['relocated_libc_it_repair_skips'] = self.report.get('relocated_libc_it_repair_skips', 0) + 1
            self.report['relocated_libc_it_repair_hits'] = self.report.get('relocated_libc_it_repair_hits', 0) + 1

        self.mu.hook_add(unicorn.UC_HOOK_CODE, repair, begin=base + 0x59c00, end=base + 0x59c00)
        self.report['relocated_libc_it_repair'] = {'base': base, 'hook': base + 0x59c00, 'literal': literal}

    def _ld_fixup_workaround(self, uc, address, size, user_data):
        """Make _dl_fixup's unconditional `mov r4,r0` explicit.

        Unicorn can skip the 16-bit move after a Thumb-2 IT block, leaving
        r4=1 instead of the link_map and making the lazy lookup search an
        empty scope.  The original instruction is an unconditional move, so
        repeating it here is a no-op when Unicorn executes it and repairs the
        known IT-latch skip otherwise.
        """
        if self.syscall_policy in ('mmap', 'kuser', 'uipc', 'threads'):
            uc.reg_write(arm.UC_ARM_REG_R4, uc.reg_read(arm.UC_ARM_REG_R0))

    def _maybe_preempt(self, uc):
        """Deterministic timer-preemption model for the cooperative scheduler.

        Real Linux preempts a running thread on the timer tick even when it keeps
        issuing non-blocking syscalls. Without this, a UIPC poll loop can
        monopolise the interpreter and never schedule runnable peers (E0473).
        Opt-in: `thread_timeslice` = 0 disables it and preserves baselines.
        """
        timeslice = getattr(self, 'thread_timeslice', 0)
        threads = getattr(self, 'threads', None)
        if not timeslice or threads is None:
            return
        if self.report.get('status') != 'running':
            return
        if self.instructions - getattr(self, '_timeslice_mark', 0) < timeslice:
            return
        current_tid = threads.current_tid
        current = threads.threads.get(current_tid)
        if current is None or current.state != 'running':
            return
        next_tid = threads.get_next_runnable_tid()
        if next_tid is None:
            return
        self._timeslice_mark = self.instructions
        threads.save_context(uc)
        current.state = 'runnable'
        self.report['thread_preemptions'] = self.report.get('thread_preemptions', 0) + 1
        events = self.report.setdefault('thread_preemption_events', [])
        if len(events) < 256:
            events.append({'at': self.instructions, 'from': current_tid, 'to': next_tid})
        threads.restore_context(uc, next_tid, getattr(self, 'kuser', None))

    def _block(self, uc, address, size, user_data):
        insn_est = max(1, size // 2)
        self.instructions += insn_est
        if self._pause_requested:
            self._pause_check(uc)
        if self._progress_interval and self.instructions % self._progress_interval < insn_est:
            self._on_progress(self)
        self.tail.append((address, size))
        if self._stop_instruction_limit and self.instructions >= self._stop_instruction_limit:
            self._stop_hit = True
            self.report['stop_instruction_hit'] = self.instructions
            uc.emu_stop()
            return
        self._maybe_preempt(uc)

    def _code(self, uc, address, size, user_data):
        self.instructions += 1
        if self._pause_requested:
            self._pause_check(uc)
        if self._progress_interval and self.instructions % self._progress_interval == 0:
            self._on_progress(self)
        self.tail.append((address, size))
        if self._stop_instruction_limit and self.instructions >= self._stop_instruction_limit:
            self._stop_hit = True
            self.report['stop_instruction_hit'] = self.instructions
            uc.emu_stop()
            return
        self._maybe_preempt(uc)
        # Workaround for emulator bug where a Thumb-2 IT block with mixed 16/32-bit instructions
        # leaves leftover IT bits in CPSR, corrupting subsequent non-IT instructions.
        if address in (0x40004e4c, 0x50259c24, 0x50034e32, 0x50034e6a, 0x4000a6f4,
                       0x5026ebc4, 0x5026ec26) and self.syscall_policy in ('mmap', 'kuser', 'uipc', 'threads'):
            cpsr = uc.reg_read(arm.UC_ARM_REG_CPSR)
            if cpsr & ((3 << 25) | (0x3f << 10)):
                uc.reg_write(arm.UC_ARM_REG_CPSR, cpsr & ~((3 << 25) | (0x3f << 10)))
        if address == 0x4000a6f4 and self.syscall_policy in ('mmap', 'kuser', 'uipc', 'threads'):
            uc.reg_write(arm.UC_ARM_REG_R4, uc.reg_read(arm.UC_ARM_REG_R0))

    def _pause_check(self, uc):
        if self._pause_requested and self.report.get('status') == 'running':
            self._pause_requested = False
            self.report['status'] = 'paused'
            uc.emu_stop()

    def _display_write(self, uc, access, address, size, value, user_data):
        if self.display is None:
            return
        self.display.note_write(address, size, uc.reg_read(arm.UC_ARM_REG_PC),
                                getattr(getattr(self, 'threads', None), 'current_tid', None),
                                self.instructions)

    def _install_display_write_hooks(self):
        """Watch only mapped display-surface ranges; execution is unchanged."""
        if self.display is None:
            return
        installed = set(self.display.installed_ranges)
        for start, end in self.display.all_surface_ranges():
            if (start, end) in installed:
                continue
            self.mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, self._display_write,
                             begin=start, end=end - 1)
            self.display.installed_ranges.append((start, end))

    def _gles_bar_read(self, uc, access, address, size, value, user_data):
        """Observe-only BAR read counter; never changes execution."""
        virtual, _length = user_data
        counts = self.report.setdefault('gles_bar_reads', {})
        key = str(int(address - virtual))
        counts[key] = counts.get(key, 0) + 1

    def _gles_bar_write(self, uc, access, address, size, value, user_data):
        """Observe guest BAR writes and mirror them into the device image."""
        virtual, _length = user_data
        offset = int(address - virtual)
        writes = self.report.setdefault('gles_bar_writes', [])
        if len(writes) < 4096:
            writes.append({'offset': offset, 'size': size, 'value': value & 0xffffffff,
                           'tid': getattr(getattr(self, 'threads', None), 'current_tid', None),
                           'pc': uc.reg_read(arm.UC_ARM_REG_PC)})
        bar = getattr(getattr(self, 'gles', None), 'bar', None)
        if bar is not None and 0 <= offset < len(bar):
            width = min(size, len(bar) - offset)
            try:
                raw = int(value).to_bytes(size, 'little', signed=False)[:width]
            except OverflowError:
                return
            bar[offset:offset + width] = raw
        gles = getattr(self, 'gles', None)
        if gles is not None and getattr(gles, 'engine_model', False):
            if offset in (0x16C, 0x170) and (value & 0xffffffff):
                if gles.complete_engine_command('bar-write'):
                    try:
                        uc.mem_write(virtual + 0x1000, b'\x00\x00\x00\x00')
                        uc.mem_write(virtual + 0xC18, b'\x00\x00\x00\x00')
                    except Exception:
                        pass
                    woken = []
                    threads = getattr(self, 'threads', None)
                    if threads is not None:
                        for fd, desc in list(getattr(self.filesystem, 'fds', {}).items()):
                            if desc.get('device') == 'dmpgles2':
                                woken.extend(threads.handle_fd_wake(fd))
                    self.report.setdefault('gles_engine_events', []).append({
                        'offset': offset, 'value': value & 0xffffffff,
                        'completions': gles.engine_completions, 'woken': sorted(set(woken)),
                        'instruction': self.instructions})
            elif offset == 0x34:
                # guest ack/status write: consume the event word
                gles.dev_a8 = 0
            elif offset == 0x1C:
                gles.dev_a8 &= ~0x04000000
            elif offset == 0x1000:
                gles.dev_a8 &= ~0x80000000
            elif offset == 0xC18:
                gles.dev_a8 &= ~0x40000000

    def install_gles_bar_hooks(self, virtual, length):
        if not hasattr(self, '_gles_bar_hook_ranges'):
            self._gles_bar_hook_ranges = []
        if (virtual, length) in self._gles_bar_hook_ranges:
            return
        self._gles_bar_hook_ranges.append((virtual, length))
        self.mu.hook_add(unicorn.UC_HOOK_MEM_READ, self._gles_bar_read,
                         begin=virtual, end=virtual + length - 1,
                         user_data=(virtual, length))
        self.mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, self._gles_bar_write,
                         begin=virtual, end=virtual + length - 1,
                         user_data=(virtual, length))

    def discover_resumed_gles_bar(self):
        """Find the resumed dmpgles2 device range and bind it to GuestGles.

        Old checkpoints predate GuestGles.bar_virtual; the mmap bookkeeping
        still records the device pages, so the BAR VA can be reconstructed
        without touching guest state.
        """
        page_info = getattr(getattr(self, 'mmap', None), 'page_backing', {})
        pages = sorted(page for page, info in page_info.items()
                       if info.get('device') == 'dmpgles2')
        if not pages:
            return []
        ranges = []
        start = previous = pages[0]
        for page in pages[1:]:
            if page != previous + 0x1000:
                ranges.append((start, previous + 0x1000 - start))
                start = page
            previous = page
        ranges.append((start, previous + 0x1000 - start))
        self.report['gles_bar_resumed_ranges'] = [[virtual, length] for virtual, length in ranges]
        gles = getattr(self, 'gles', None)
        if gles is not None and ranges:
            gles.bar_virtual, length = ranges[0]
            gles.bar_length = min(length, len(getattr(gles, 'bar', b'\x00' * 0x4000)))
        return ranges

    def install_resumed_gles_bar_hooks(self):
        """Install observe-only BAR hooks on a resumed dmpgles2 device range."""
        ranges = self.discover_resumed_gles_bar()
        for virtual, length in ranges:
            self.install_gles_bar_hooks(virtual, length)
        return ranges

    def capture_display(self, key=None):
        """Read one display frame from guest memory; never writes guest state."""
        if self.display is None:
            return None
        return self.display.read_frame(lambda address, size: bytes(self.mu.mem_read(address, size)),
                                       key=key, instruction=self.instructions)

    def inject_usb_event(self, record):
        """Inject one verified /dev/usb/event record and wake blocked readers."""
        if not record:
            raise ValueError('USB event record must not be empty')
        if getattr(self, 'usb_event', None) is None:
            raise ValueError('No USB event device is bound')
        result = self.usb_event.inject_record(bytes(record))
        filesystem = getattr(self, 'filesystem', None)
        fd = None
        if filesystem is not None:
            fd = next((number for number, entry in filesystem.fds.items()
                       if entry.get('device') == 'usb_event'), None)
        woken = []
        if fd is not None and getattr(self, 'threads', None) is not None:
            woken = list(self.threads.handle_fd_wake(fd) or [])
        entry = {'instruction': self.instructions, 'fd': fd, 'woken': woken,
                 **(result if isinstance(result, dict) else {'accepted': bool(result)})}
        self.report.setdefault('usb_event_injection', []).append(entry)
        return entry

    def arm_usb_connect_event(self, record, at_instruction=0):
        """Arm one verified record for delivery once the event device is open."""
        if not record:
            raise ValueError('USB event record must not be empty')
        self._usb_connect_record = bytes(record)
        self._usb_connect_at = int(at_instruction)
        self._usb_connect_attempts = 0
        if self._progress_interval == 0:
            self._progress_interval = 1_000_000
        original = self._on_progress

        def wrapped(probe):
            if original is not None:
                original(probe)
            probe._maybe_inject_usb_connect()

        self._on_progress = wrapped
        return self

    def _maybe_inject_usb_connect(self):
        record = self._usb_connect_record
        if record is None or self.instructions < self._usb_connect_at:
            return None
        if getattr(self, 'usb_event', None) is None or not getattr(self.usb_event, 'owners', {}):
            return None
        self._usb_connect_attempts += 1
        try:
            result = self.inject_usb_event(record)
        except Exception as error:
            self.report['usb_event_injection_error'] = {'reason': str(error),
                                                        'attempts': self._usb_connect_attempts}
            self._usb_connect_record = None
            return None
        if result.get('accepted'):
            self._usb_connect_record = None
        elif self._usb_connect_attempts >= 64:
            self.report['usb_event_injection_error'] = {
                'reason': result.get('reason', 'record_not_accepted'),
                'attempts': self._usb_connect_attempts}
            self._usb_connect_record = None
        return result

    def inject_uipc_setconfig_objmsg(self, queue, wake_uaddr=None, packet_hex=None):
        """Inject the labelled emulated inbound SETCONFIG ObjMsg (E0328).

        Allocates the ObjMsg image inside the UIPC pool, then enqueues a
        4-byte envelope whose word0 points at it (the ABI returned by
        UsbControl::MsgReceiver::RcvMsg, E0324).  The object layout is
        evidence-derived (E0323/E0324); the param map is zeroed, so this is an
        explicitly labelled experiment, not a captured kernel message.

        With ``packet_hex`` (bytes or a hex string) the envelope payload is the
        supplied packet instead of the ObjMsg pointer: the message is still
        allocated large enough for those bytes and the ledger records the
        packet bytes/hash/provenance.  Default behaviour (``None``) is
        unchanged.
        """
        import struct as _struct

        from src.a6400.execution.mwf_objmsg import (
            build_setconfig_objmsg_image,
        )
        if getattr(self, 'uipc', None) is None:
            raise ValueError('No UIPC device is initialized')
        packet = None
        packet_text = None
        if packet_hex is not None:
            packet, packet_text = normalise_packet_hex(packet_hex)
        obj = self.uipc.allocate_message(0x80, memory_writer=self._uipc_write)
        image = build_setconfig_objmsg_image(obj)
        self.mu.mem_write(obj, image)
        envelope_size = len(packet) if packet is not None else 4
        envelope = self.uipc.allocate_message(envelope_size, memory_writer=self._uipc_write)
        if packet is not None:
            self.mu.mem_write(envelope, packet)
        else:
            self.mu.mem_write(envelope, _struct.pack('<I', obj))
        self.uipc.enqueue_message(queue, envelope)
        woken = []
        if getattr(self, 'threads', None) is not None:
            woken = list(self.threads.handle_uipc_wake(queue) or [])
            if self.uipc.kernel_pool_options and self.uipc.callback_ready():
                woken.extend(self.threads.handle_uipc_wake(-1) or [])
        futex_woken = 0
        if wake_uaddr is not None and getattr(self, 'threads', None) is not None:
            futex_woken, _details = self.threads.handle_futex_wake(wake_uaddr, 1)
        entry = {
            'instruction': self.instructions,
            'queue': queue,
            'wake_uaddr': wake_uaddr,
            'futex_woken': futex_woken,
            'objmsg': obj,
            'body': obj + 0x20,
            'envelope': envelope,
            'woken': woken,
            'source': 'emulated-setconfig-objmsg',
            'category': 0x6103,
            'message_id': 0x0A4001,
            'param_map': 'zeroed (E0325 boundary)',
            'provenance': 'ObjMsg/body layout from E0323/E0324; not a captured '
                          'kernel message',
        }
        if packet is not None:
            entry.update({
                'packet_hex': packet_text,
                'packet_size': len(packet),
                'packet_sha256': hashlib.sha256(packet).hexdigest(),
                'envelope_size': envelope_size,
                'payload_mode': 'explicit-packet-hex',
                'provenance': entry['provenance'] +
                              '; envelope payload is an explicit packet_hex '
                              'override (labelled experiment; not a captured '
                              'kernel message)',
            })
        self.report.setdefault('uipc_objmsg_injection', []).append(entry)
        return entry

    def inject_local_queue_objmsg(self, queue_object_addr, waiter_addr=None,
                                     guest_alloc=False, libosal_base=None,
                                     libmwf_base=0x53660000):
        """Post the labelled SETCONFIG ObjMsg through the libosal LOCAL queue.

        Opt-in, evidence-supplied addresses: the queue object and (optional)
        one-shot WAIT_CB record must come from the resumed checkpoint. The
        write plan is produced by the pure ``local_queue_post`` planner (E0330/
        E0335); this method only applies the planned words and performs the
        single futex wake. It does not enqueue into the kernel queue list.
        """
        import struct as _struct

        from src.a6400.execution.local_queue_post import (
            plan_local_post,
            render_post_plan,
        )
        from src.a6400.execution.mwf_objmsg import build_setconfig_objmsg_image
        if getattr(self, 'uipc', None) is None:
            raise ValueError('No UIPC device is initialized')
        reader = lambda addr, size: bytes(self.mu.mem_read(addr, size))
        alloc_plans = []
        if guest_alloc:
            from src.a6400.execution.guest_osal_alloc import (
                inspect_guest_allocator,
                plan_message_alloc,
                render_alloc_plan,
            )
            if libosal_base is None:
                raise ValueError('guest_alloc requires the resumed libosal_uipc base')
            alloc_plans.append(inspect_guest_allocator(reader, libosal_base))
            obj_plan = plan_message_alloc(reader, libosal_base, 0x80)
            for addr, data in obj_plan['writes']:
                self.mu.mem_write(addr, data)
            alloc_plans.append(obj_plan)
            obj = obj_plan['message']['payload']
            self.mu.mem_write(obj, build_setconfig_objmsg_image(
                obj, libmwf_base=libmwf_base))
            # Teardown safety: ParamMap::Clear frees the map array, and the
            # parameter object may be owned by the map.  Allocate both from the
            # guest allocator and patch the ObjMsg body to point at them, so no
            # in-image pointer is ever freed by the original teardown.
            param_plan = plan_message_alloc(reader, libosal_base, 0x10)
            for addr, data in param_plan['writes']:
                self.mu.mem_write(addr, data)
            alloc_plans.append(param_plan)
            param = param_plan['message']['payload']
            self.mu.mem_write(param, _struct.pack(
                '<II', 0, (int(libmwf_base) + 0x4067C) & 0xffffffff))
            array_plan = plan_message_alloc(reader, libosal_base, 0x10)
            for addr, data in array_plan['writes']:
                self.mu.mem_write(addr, data)
            alloc_plans.append(array_plan)
            param_array = array_plan['message']['payload']
            self.mu.mem_write(param_array, _struct.pack('<II', 0x1006, param))
            self.mu.mem_write(obj + 0x34, _struct.pack('<I', param_array))
            # Teardown free-hook is available but disabled by default: suppressing
            # libc free() on the in-image/OSAL objects faults earlier than the
            # original invalid-free boundary (E0694). Keep the labelled boundary.
            env_plan = plan_message_alloc(reader, libosal_base, 4)
            for addr, data in env_plan['writes']:
                self.mu.mem_write(addr, data)
            alloc_plans.append(env_plan)
            envelope = env_plan['message']['payload']
            self.mu.mem_write(envelope, _struct.pack('<I', obj))
        else:
            obj = self.uipc.allocate_message(0x80, memory_writer=self._uipc_write)
            self.mu.mem_write(obj, build_setconfig_objmsg_image(
                obj, libmwf_base=libmwf_base))
            envelope = self.uipc.allocate_message(4, memory_writer=self._uipc_write)
            self.mu.mem_write(envelope, _struct.pack('<I', obj))
        plan = plan_local_post(reader, queue_object_addr, envelope,
                               waiter_addr=waiter_addr)
        def _jsonable_plan(value):
            if isinstance(value, (bytes, bytearray)):
                return bytes(value).hex()
            if isinstance(value, dict):
                return {key: _jsonable_plan(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [_jsonable_plan(item) for item in value]
            return value

        applied = []
        for addr, data in plan['writes']:
            try:
                self.mu.mem_write(addr, data)
            except Exception:
                self._uipc_write(addr, data)
            applied.append({'addr': addr, 'bytes_hex': bytes(data).hex()})
        wake = plan.get('wake') or {}
        futex_woken = 0
        if wake.get('futex_uaddr') is not None and getattr(self, 'threads', None) is not None:
            futex_woken, _details = self.threads.handle_futex_wake(
                wake['futex_uaddr'], 1)
        entry = {
            'instruction': self.instructions,
            'source': 'emulated-local-queue-setconfig-objmsg',
            'objmsg': obj,
            'body': obj + 0x20,
            'envelope': envelope,
            'queue_object': queue_object_addr,
            'waiter': waiter_addr,
            'writes': applied,
            'wake': wake,
            'futex_woken': futex_woken,
            'guest_alloc': bool(guest_alloc),
            'libosal_base': libosal_base,
            'libmwf_base': libmwf_base,
            'alloc_plans': _jsonable_plan(alloc_plans),
            'alloc_rendered': [line for plan in alloc_plans
                               for line in (render_alloc_plan(plan)
                                            if plan.get('kind') == 'guest-osal-message-alloc'
                                            else [])],
            'plan': _jsonable_plan(plan),
            'plan_rendered': render_post_plan(plan),
            'category': 0x6103,
            'message_id': 0x0A4001,
            'provenance': 'local-queue post plan from E0330/E0335; addresses '
                          'supplied from the resumed checkpoint; not a captured '
                          'sender execution',
        }
        self.report.setdefault('local_queue_objmsg_injection', []).append(entry)
        return entry

    def install_suppressed_free_hook(self, addresses):
        """Observe-only guard that suppresses libc free() on emulator-owned objects.

        The labelled SETCONFIG run allocates ObjMsg/ParamMap/Param objects from
        the guest allocator; the original teardown (operator delete / ParamMap
        clear) may still call libc free on those objects and abort with
        ``free(): invalid pointer`` (E0337/E0691). This opt-in hook matches only
        the explicitly supplied addresses and returns from free() without
        releasing them, recording every suppression; all other free() calls run
        the original code unchanged.
        """
        addresses = {int(value) for value in addresses}
        entries = module_mapping_entries('libc-2.11.2.so',
                                         getattr(getattr(self, 'mmap', None),
                                                 'mappings', None))
        bases = set()
        zero_offset = set()
        for entry in entries:
            try:
                address = int(entry['address'])
                offset = int(entry.get('offset') or 0)
            except (KeyError, TypeError, ValueError):
                continue
            bases.add(address - offset)
            if offset == 0:
                zero_offset.add(address)
        if len(bases) == 1:
            base = bases.pop()
        elif len(zero_offset) == 1:
            base = zero_offset.pop()
        else:
            self.report['suppressed_free_hook'] = {
                'available': False, 'reason': 'libc_base_unresolved',
                'mapping_count': len(entries), 'entries': entries,
                'candidate_bases': sorted(bases),
                'zero_offset_bases': sorted(zero_offset)}
            return {'available': False, 'reason': 'libc_base_unresolved'}
        free_address = (base + 0x5B99C) & ~1
        suppressed = []
        probe = self

        def on_free(uc, address, size, user_data):
            try:
                pointer = uc.reg_read(arm.UC_ARM_REG_R0)
            except Exception:
                return
            if pointer not in addresses:
                return
            try:
                lr = uc.reg_read(arm.UC_ARM_REG_LR)
            except Exception:
                return
            thumb_return = bool(lr & 1)
            cpsr = uc.reg_read(arm.UC_ARM_REG_CPSR)
            cpsr = (cpsr | 0x20) if thumb_return else (cpsr & ~0x20)
            suppressed.append({'instruction': probe.instructions,
                               'tid': probe.threads.current_tid
                               if getattr(probe, 'threads', None) else None,
                               'pointer': pointer, 'pc': address,
                               'lr': lr, 'thumb_return': thumb_return})
            uc.reg_write(arm.UC_ARM_REG_CPSR, cpsr)
            uc.reg_write(arm.UC_ARM_REG_R0, 0)
            uc.reg_write(arm.UC_ARM_REG_PC, lr & ~1)

        self.mu.hook_add(unicorn.UC_HOOK_CODE, on_free,
                         begin=free_address, end=free_address + 4)
        info = {'available': True, 'libc_base': base,
                'free_address': free_address,
                'free_symbol_offset': 0x5B99C,
                'suppressed_addresses': sorted(addresses),
                'evidence': 'live libc-2.11.2.so .dynsym free=0x5B99C; '
                            'hook suppresses free only for labelled emulator '
                            'objects'}
        self.report['suppressed_free_hook'] = info
        self._suppressed_free_records = suppressed
        return info

    def inject_uipc_message(self, queue, payload, source=None):
        """Queue one explicit UIPC message and wake the target queue waiters."""
        if getattr(self, 'uipc', None) is None:
            raise ValueError('No UIPC device is initialized')
        if not payload:
            raise ValueError('UIPC injection payload must not be empty')
        payload = bytes(payload)
        message = self.uipc.allocate_message(len(payload), memory_writer=self._uipc_write)
        self.mu.mem_write(message, payload)
        self.uipc.enqueue_message(queue, message)
        woken = []
        if getattr(self, 'threads', None) is not None:
            woken = list(self.threads.handle_uipc_wake(queue) or [])
            if self.uipc.kernel_pool_options and self.uipc.callback_ready():
                woken.extend(self.threads.handle_uipc_wake(-1) or [])
        entry = {'instruction': self.instructions, 'queue': queue, 'size': len(payload),
                 'sha256': hashlib.sha256(payload).hexdigest(), 'msg_ptr': message,
                 'woken': woken, 'source': source}
        self.report.setdefault('uipc_injection', []).append(entry)
        return entry

    # ------------------------------------------------------------------
    # Observe-only UsbControl dispatch tracing (E0332 follow-up).
    # ------------------------------------------------------------------
    def _usbcontrol_dispatch_module_image(self, module_name, entries):
        """Return ``(elf_bytes, provenance)`` for a module the guest loaded.

        Prefers the bytes the guest actually read (restored checkpoint
        filesystem cache); falls back to the hash-recorded live-libs evidence
        copy for checkpoints that predate the cache or lack the file.
        """
        path = entries[0].get('path') if entries else None
        cache = getattr(getattr(self, 'filesystem', None), 'cache', None) or {}
        if path and path in cache:
            raw = bytes(cache[path])
            return raw, {'source': 'guest_filesystem_cache', 'path': path,
                         'sha256': hashlib.sha256(raw).hexdigest()}
        relative = USB_CONTROL_DISPATCH_EVIDENCE_LIBS.get(module_name)
        if relative:
            try:
                from project_paths import PROJECT_ROOT
                artifact = PROJECT_ROOT / relative
                raw = artifact.read_bytes()
            except Exception as error:
                raise ValueError('module_bytes_unavailable: %s' % (error,))
            return raw, {'source': 'live-libs-evidence-artifact',
                         'path': str(artifact),
                         'sha256': hashlib.sha256(raw).hexdigest()}
        raise ValueError('module_bytes_unavailable')

    def _resolve_usbcontrol_dispatch_symbols(self):
        """Resolve every dispatch function from the resumed module base + dynsym."""
        mappings = getattr(getattr(self, 'mmap', None), 'mappings', None) or []
        by_module = {}
        for spec in USB_CONTROL_DISPATCH_SYMBOLS:
            by_module.setdefault(spec['module'], []).append(spec)
        resolved = {}
        for module_name, specs in by_module.items():
            entries = module_mapping_entries(module_name, mappings)
            if not entries:
                for spec in specs:
                    resolved[spec['function']] = {
                        'available': False, 'module': module_name,
                        'symbol': spec['symbol'], 'reason': 'module_not_mapped'}
                continue
            try:
                elf_bytes, provenance = self._usbcontrol_dispatch_module_image(
                    module_name, entries)
                load_segments, symbol_values = inspect_elf_load_and_symbols(
                    elf_bytes, [spec['symbol'] for spec in specs])
                base_info = resumed_module_base(module_name, entries, load_segments)
            except Exception as error:
                for spec in specs:
                    resolved[spec['function']] = {
                        'available': False, 'module': module_name,
                        'symbol': spec['symbol'], 'reason': str(error)}
                continue
            for spec in specs:
                symbol = symbol_values.get(spec['symbol'])
                if symbol is None:
                    reason = 'symbol_not_in_dynsym'
                elif not symbol.get('defined'):
                    reason = 'undefined_symbol'
                elif not int(symbol.get('value') or 0):
                    reason = 'symbol_value_zero'
                else:
                    reason = None
                if reason is not None:
                    resolved[spec['function']] = {
                        'available': False, 'module': module_name,
                        'symbol': spec['symbol'], 'reason': reason}
                    continue
                value = int(symbol['value'])
                resolved[spec['function']] = {
                    'available': True, 'module': module_name,
                    'symbol': spec['symbol'], 'symbol_value': value,
                    'thumb': bool(value & 1),
                    'address': (int(base_info['base']) + value) & ~1,
                    'base': int(base_info['base']),
                    'module_path': base_info.get('path'),
                    'mapping_count': len(base_info['mappings']),
                    'symbol_source': provenance['source'],
                    'symbol_source_sha256': provenance['sha256'],
                }
        return resolved

    def install_usbcontrol_dispatch_hooks(self, resolution=None, max_hits=None):
        """Install observe-only hooks on the original UsbControl dispatch chain.

        Requires the opt-in ``trace_usbcontrol_dispatch`` attribute.  Live VAs
        are resolved from the resumed module base plus the loaded module's
        ``.dynsym`` (never a hardcoded live VA).  A missing module/symbol is
        recorded as ``{'available': False, 'reason': ...}`` in
        ``report['usbcontrol_dispatch_hooks']['functions']`` and the run
        continues without a fault.  ``resolution`` may supply a pre-resolved
        function table (unit tests / controlled experiments).  Hits are
        appended to ``report['usbcontrol_dispatch_trace']``.
        """
        if not getattr(self, 'trace_usbcontrol_dispatch', False):
            return {'enabled': False, 'reason': 'trace_usbcontrol_dispatch is False'}
        if getattr(self, '_usbcontrol_dispatch_installed', False):
            return self.report.get('usbcontrol_dispatch_hooks', {'enabled': True})
        limit = int(max_hits if max_hits is not None
                    else getattr(self, 'usbcontrol_dispatch_max_hits', 2000))
        if limit <= 0:
            raise ValueError('max_hits must be positive')
        self._usbcontrol_dispatch_installed = True
        self._usbcontrol_dispatch_limit = limit
        self._usbcontrol_dispatch_pending = {}
        self._usbcontrol_dispatch_return_hooks = {}
        self.report.setdefault('usbcontrol_dispatch_trace', [])
        functions = {}
        if resolution is None:
            resolution = self._resolve_usbcontrol_dispatch_symbols()
        for spec in USB_CONTROL_DISPATCH_SYMBOLS:
            label = spec['function']
            info = dict(resolution.get(label) or
                        {'available': False, 'reason': 'resolution_missing'})
            if info.get('available'):
                address = int(info['address'])
                try:
                    self.mu.hook_add(unicorn.UC_HOOK_CODE,
                                     self._usbcontrol_dispatch_hit,
                                     begin=address, end=address,
                                     user_data={'spec': spec, 'info': info})
                except Exception as error:
                    info = dict(info, available=False,
                                reason='hook_install_failed: %s' % (error,))
            functions[label] = info
        config = {
            'enabled': True,
            'observe_only': True,
            'max_hits': limit,
            'functions': functions,
            'evidence': 'libUsbControl.so / libMWF.so .dynsym offsets plus the '
                        'resumed module base from the checkpoint mmap table; no '
                        'hardcoded live VA',
        }
        self.report['usbcontrol_dispatch_hooks'] = config
        return config

    @staticmethod
    def _usbcontrol_dispatch_read_objmsg(uc, pointer):
        """Read ObjMsg body/category/message id when mapped; never writes."""
        if not pointer:
            return None
        try:
            body = struct.unpack('<I', bytes(uc.mem_read(int(pointer), 4)))[0]
            if not body:
                return {'pointer': int(pointer), 'body_pointer': 0}
            category, message_id = struct.unpack(
                '<II', bytes(uc.mem_read(int(body) + 4, 8)))
        except Exception:
            return None
        return {'pointer': int(pointer), 'body_pointer': int(body),
                'category_id': int(category), 'message_id': int(message_id)}

    def _usbcontrol_dispatch_record_error(self, function, error):
        errors = self.report.setdefault('usbcontrol_dispatch_errors', [])
        if len(errors) < 32:
            errors.append({'function': function, 'instruction': self.instructions,
                           'error': str(error)})

    def _usbcontrol_dispatch_hit(self, uc, address, size, user_data):
        """Observe-only record of one dispatch-function entry; changes nothing."""
        spec = user_data.get('spec', {}) if isinstance(user_data, dict) else {}
        function = spec.get('function')
        try:
            entry = {
                'function': function,
                'instruction': self.instructions,
                'tid': getattr(getattr(self, 'threads', None), 'current_tid', None),
                'pc': address,
                'args': {name: uc.reg_read(register)
                         for name, register in spec.get('arg_registers', ())},
            }
            objmsg_argument = spec.get('objmsg_argument')
            if objmsg_argument:
                fields = self._usbcontrol_dispatch_read_objmsg(
                    uc, entry['args'].get(objmsg_argument))
                if fields is not None:
                    entry['objmsg'] = fields
            trace = self.report.setdefault('usbcontrol_dispatch_trace', [])
            if len(trace) >= getattr(self, '_usbcontrol_dispatch_limit', 0):
                hooks = self.report.get('usbcontrol_dispatch_hooks')
                if isinstance(hooks, dict):
                    hooks['truncated'] = True
                return
            trace.append(entry)
            if spec.get('returns'):
                self._usbcontrol_dispatch_arm_return(uc, spec, entry)
        except Exception as error:
            self._usbcontrol_dispatch_record_error(function, error)

    def _usbcontrol_dispatch_arm_return(self, uc, spec, entry):
        """Arm a return-address hook that stores the caller-visible r0.

        The hook stays registered per return address (call sites are few); it
        pops the matching pending entry on return and is a no-op when no call
        is in flight, so later execution of the same address cannot alias a
        hit onto the wrong call.
        """
        return_address = int(uc.reg_read(arm.UC_ARM_REG_LR)) & ~1
        if not return_address:
            return
        pending = self._usbcontrol_dispatch_pending.setdefault(return_address, [])
        pending.append({'spec': spec, 'entry': entry})
        if return_address in self._usbcontrol_dispatch_return_hooks:
            return
        try:
            handle = self.mu.hook_add(unicorn.UC_HOOK_CODE,
                                      self._usbcontrol_dispatch_return,
                                      begin=return_address, end=return_address)
        except Exception as error:
            pending.pop()
            self._usbcontrol_dispatch_record_error(spec.get('function'), error)
            return
        self._usbcontrol_dispatch_return_hooks[return_address] = handle

    def _usbcontrol_dispatch_return(self, uc, address, size, user_data):
        """Record the r0 return value of an armed dispatch-function call."""
        record = None
        try:
            pending = self._usbcontrol_dispatch_pending.get(address)
            if not pending:
                return
            record = pending.pop()
            value = int(uc.reg_read(arm.UC_ARM_REG_R0))
            returns = {'value': value}
            field = record['spec'].get('returns')
            if field:
                returns[field] = value
            record['entry']['returns'] = returns
        except Exception as error:
            self._usbcontrol_dispatch_record_error(
                (record or {}).get('spec', {}).get('function'), error)

    def install_write_watch(self, begin, end, limit=20000):
        """Observe-only write watch over a guest range (bounded record list).

        Used to find which guest code writes malloc metadata in the heap
        (E0507 heap-corruption diagnosis). Execution is unchanged.
        """
        self.report['write_watch_config'] = {'begin': begin, 'end': end, 'limit': limit}
        records = []

        def hook(uc, access, address, size, value, user_data):
            if len(records) >= limit:
                return
            records.append({
                'instruction': self.instructions,
                'tid': getattr(self.threads, 'current_tid', None),
                'address': address,
                'size': size,
                'value': value,
                'pc': uc.reg_read(arm.UC_ARM_REG_PC),
                'lr': uc.reg_read(arm.UC_ARM_REG_LR),
            })
            self.report['write_watch'] = records

        self.mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, hook, begin=begin, end=end)
        return records

    def install_instruction_stop(self, limit):
        """Observe-only hard stop once the absolute instruction count reaches limit.

        Implemented inside the existing fast/progress hooks (no extra guest
        hook) so the execution trajectory and instruction accounting stay
        identical to a normal run; only the stop point changes.
        """
        if limit <= 0:
            raise ValueError('stop-instruction limit must be positive')
        self._stop_instruction_limit = limit
        self.report['stop_instruction_config'] = {'limit': limit}
        return limit

    def install_allocator_audit(self, malloc_va=0x5025B3C8, free_va=0x5025B8D4,
                                limit=5000, heap_begin=0x15000, heap_end=0x200000):
        """Observe-only glibc allocator audit (E0550).

        Logs malloc requests and validates free() chunk headers so the first
        inconsistent chunk/bin state can be attributed to a specific call.
        Execution is unchanged; records are bounded.
        """
        events = []
        self.report['allocator_audit_config'] = {'malloc_va': malloc_va, 'free_va': free_va,
                                                 'limit': limit, 'heap_begin': heap_begin,
                                                 'heap_end': heap_end}

        def record(entry):
            if len(events) < limit:
                events.append(entry)
            self.report['allocator_audit'] = events

        def malloc_hook(uc, address, size, user_data):
            record({'op': 'malloc', 'size': uc.reg_read(arm.UC_ARM_REG_R0),
                    'tid': getattr(self.threads, 'current_tid', None),
                    'lr': uc.reg_read(arm.UC_ARM_REG_LR),
                    'instruction': self.instructions})

        def free_hook(uc, address, size, user_data):
            ptr = uc.reg_read(arm.UC_ARM_REG_R0)
            entry = {'op': 'free', 'ptr': ptr,
                     'tid': getattr(self.threads, 'current_tid', None),
                     'lr': uc.reg_read(arm.UC_ARM_REG_LR),
                     'instruction': self.instructions}
            try:
                raw = bytes(uc.mem_read(ptr - 8, 8))
                prev_size, chunk_size = struct.unpack('<II', raw)
                entry['prev_size'] = prev_size
                entry['chunk_size'] = chunk_size
                size_bits = chunk_size & ~7
                entry['size_bits'] = size_bits
                entry['prev_inuse'] = chunk_size & 1
                entry['mmapped'] = chunk_size & 2
                anomalies = []
                if ptr & 7:
                    anomalies.append('misaligned_user_ptr')
                if size_bits < 0x10:
                    anomalies.append('size_too_small')
                if size_bits > 0x1000000:
                    anomalies.append('size_too_large')
                if not (heap_begin <= ptr - 8 < heap_end) and not (chunk_size & 2):
                    anomalies.append('outside_heap')
                if ptr - 8 + size_bits > heap_end + 0x10000:
                    anomalies.append('chunk_beyond_heap')
                if anomalies:
                    entry['anomalies'] = anomalies
            except Exception as error:
                entry['read_error'] = str(error)
                entry['anomalies'] = ['chunk_header_unreadable']
            record(entry)

        self.mu.hook_add(unicorn.UC_HOOK_CODE, malloc_hook, begin=malloc_va, end=malloc_va)
        self.mu.hook_add(unicorn.UC_HOOK_CODE, free_hook, begin=free_va, end=free_va)
        return events

    def install_trace_address(self, address, stack_words=16, when_r2=None, when_r0=None, max_hits=1):
        """Observe-only stop at one guest address and record the last instructions.

        When ``when_r2``/``when_r0`` is set, only a hit whose r2/r0 register
        equals that value is recorded (used to pick out a specific write()
        length or malloc size on a shared libc entry point). With
        ``max_hits > 1`` several matching hits are recorded and the run stops
        at the last requested hit.
        """
        records = []
        self.report['trace_address_config'] = {'address': address, 'observe_only': True,
                                               'max_hits': max_hits}
        if when_r2 is not None:
            self.report['trace_address_config']['when_r2'] = when_r2
        if when_r0 is not None:
            self.report['trace_address_config']['when_r0'] = when_r0

        def hook(uc, hook_address, size, user_data):
            if when_r2 is not None and uc.reg_read(arm.UC_ARM_REG_R2) != when_r2:
                return
            if when_r0 is not None and uc.reg_read(arm.UC_ARM_REG_R0) != when_r0:
                return
            sp = uc.reg_read(arm.UC_ARM_REG_SP)
            try:
                raw_stack = bytes(uc.mem_read(sp, stack_words * 4))
            except unicorn.UcError:
                raw_stack = b''
            words = list(struct.unpack('<' + 'I' * (len(raw_stack) // 4), raw_stack))
            record = {
                'instruction': self.instructions,
                'address': hook_address,
                'tid': getattr(self.threads, 'current_tid', None),
                'registers': {name: uc.reg_read(register) for name, register in
                              (('r0', arm.UC_ARM_REG_R0), ('r1', arm.UC_ARM_REG_R1),
                               ('r2', arm.UC_ARM_REG_R2), ('r3', arm.UC_ARM_REG_R3),
                               ('r4', arm.UC_ARM_REG_R4), ('r5', arm.UC_ARM_REG_R5),
                               ('r6', arm.UC_ARM_REG_R6), ('r7', arm.UC_ARM_REG_R7),
                               ('r8', arm.UC_ARM_REG_R8), ('r9', arm.UC_ARM_REG_R9),
                               ('r10', arm.UC_ARM_REG_R10), ('r11', arm.UC_ARM_REG_R11),
                               ('r12', arm.UC_ARM_REG_R12), ('sp', arm.UC_ARM_REG_SP),
                               ('lr', arm.UC_ARM_REG_LR), ('pc', arm.UC_ARM_REG_PC))},
                'last_instructions': list(self.tail),
                'stack_words': words,
            }
            records.append(record)
            self.report['trace_address'] = record
            hits = self.report.setdefault('trace_address_hits', [])
            if len(hits) < 64:
                hits.append(record)
            if len(records) >= max_hits:
                uc.emu_stop()

        self.mu.hook_add(unicorn.UC_HOOK_CODE, hook, begin=address, end=address + 4)
        return records

    def _interrupt(self, uc, interrupt, user_data):
        pc = uc.reg_read(arm.UC_ARM_REG_PC)
        thumb = bool(uc.reg_read(arm.UC_ARM_REG_CPSR) & 0x20)
        size = 2 if thumb else 4
        raw = bytes(uc.mem_read(pc - size, size))
        instruction = int.from_bytes(raw, 'little')
        svc = interrupt == 2 and ((thumb and instruction & 0xff00 == 0xdf00) or
                                  (not thumb and instruction & 0x0f000000 == 0x0f000000))
        immediate = instruction & (0xff if thumb else 0xffffff)
        number = uc.reg_read(arm.UC_ARM_REG_R7)
        if svc and (number == 0xf0005 or (not thumb and instruction == 0xef9f0005)) and self.syscall_policy in ('kuser', 'uipc', 'threads'):
            tls_val = uc.reg_read(arm.UC_ARM_REG_R0)
            self.kuser.set_tls(tls_val)
            if hasattr(self, 'threads') and 1000 in self.threads.threads:
                self.threads.threads[1000].tls_val = tls_val
            uc.reg_write(arm.UC_ARM_REG_R0, 0)
            event = {'syscall': 'set_tls', 'r7': 0xf0005, 'tls': tls_val, 'returned': 0,
                     'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
            self.report['serviced_syscalls'].append(event)
            self.report['syscall_responses_supplied'] += 1
            return
        if svc and immediate == 0 and self.syscall_policy in ('brk', 'brk-uname', 'files', 'metadata', 'mmap', 'kuser', 'uipc', 'threads') and number == 45:
            event = self.heap.request(uc.reg_read(arm.UC_ARM_REG_R0))
            event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
            self.report['serviced_syscalls'].append(event)
            self.report['syscall_responses_supplied'] += 1
            uc.reg_write(arm.UC_ARM_REG_R0, event['returned'])
            return
        if svc and immediate == 0 and self.syscall_policy in ('brk-uname', 'files', 'metadata', 'mmap', 'kuser', 'uipc', 'threads') and number == 122:
            event = self.uname.request(uc.reg_read(arm.UC_ARM_REG_R0))
            if event['returned'] == 0 and hasattr(self, 'stat64'):
                self.stat64.forget_range(event['buffer'], 390)
            event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
            self.report['serviced_syscalls'].append(event)
            self.report['syscall_responses_supplied'] += 1
            uc.reg_write(arm.UC_ARM_REG_R0, event['returned'])
            return
        if svc and immediate == 0 and self.syscall_policy in ('uipc', 'threads'):
            if number in (3, 4, 19, 118, 146, 148, 180, 181, 197):
                stream_fd = uc.reg_read(arm.UC_ARM_REG_R0)
                if self.filesystem.fds.get(stream_fd, {}).get('device') == 'nflasha4':
                    policy = getattr(self, 'nflasha4_device_policy', 'stop')
                    dump = getattr(self, 'nflasha4_dump', None)
                    if policy == 'observed-dump' and isinstance(dump, Nflasha4Dump):
                        entry = self.filesystem.fds[stream_fd]
                        if number == 19:
                            raw_offset = uc.reg_read(arm.UC_ARM_REG_R1)
                            offset = raw_offset - 0x100000000 if raw_offset & 0x80000000 else raw_offset
                            whence = uc.reg_read(arm.UC_ARM_REG_R2)
                            current = entry.get('offset', 0)
                            if whence == 0:
                                new_offset = offset
                            elif whence == 1:
                                new_offset = current + offset
                            elif whence == 2:
                                new_offset = dump.size + offset
                            else:
                                self.report['serviced_syscalls'].append({
                                    'syscall': 'lseek', 'fd': stream_fd, 'offset': offset,
                                    'whence': whence, 'returned': -22,
                                    'path': '/dev/nflasha4', 'policy': 'observed-dump'})
                                uc.reg_write(arm.UC_ARM_REG_R0, 0xffffffea)
                                return
                            if new_offset < 0 or new_offset > 0x7fffffff:
                                uc.reg_write(arm.UC_ARM_REG_R0, 0xffffffea)
                                return
                            entry['offset'] = new_offset
                            self.report['serviced_syscalls'].append({
                                'syscall': 'lseek', 'fd': stream_fd, 'offset': offset,
                                'whence': whence, 'returned': new_offset,
                                'path': '/dev/nflasha4', 'policy': 'observed-dump'})
                            self.report['syscall_responses_supplied'] += 1
                            uc.reg_write(arm.UC_ARM_REG_R0, new_offset)
                            return
                        if number == 3:
                            buf = uc.reg_read(arm.UC_ARM_REG_R1)
                            count = uc.reg_read(arm.UC_ARM_REG_R2)
                            offset = entry.get('offset', 0)
                            try:
                                data = dump.read(offset, count)
                            except Nflasha4DumpError as error:
                                self.report.update(status='unsupported_nflasha4_contract', boundary={
                                    'reason': str(error), 'fd': stream_fd,
                                    'path': '/dev/nflasha4', 'offset': offset, 'count': count,
                                    'pc': pc, 'r7': number, 'instruction_address': pc - size})
                                uc.emu_stop()
                                return
                            try:
                                if data:
                                    uc.mem_write(buf, data)
                                ret = len(data)
                            except unicorn.UcError:
                                ret = -14  # -EFAULT: no guest output buffer written.
                            if ret > 0:
                                entry['offset'] = offset + ret
                            self.report['serviced_syscalls'].append({
                                'syscall': 'read', 'fd': stream_fd, 'offset': offset,
                                'count': count, 'returned': ret,
                                'path': '/dev/nflasha4', 'policy': 'observed-dump'})
                            self.report['syscall_responses_supplied'] += 1
                            uc.reg_write(arm.UC_ARM_REG_R0, ret)
                            return
                        if number in (118, 148):
                            try:
                                ret = dump.flush_result(bool(entry.get('dirty')))
                            except Nflasha4DumpError as error:
                                self.report.update(status='unsupported_nflasha4_contract', boundary={
                                    'reason': str(error), 'number': number,
                                    'fd': stream_fd, 'path': '/dev/nflasha4',
                                    'pc': pc, 'r7': number, 'instruction_address': pc - size})
                                uc.emu_stop()
                                return
                            self.report['serviced_syscalls'].append({
                                'syscall': 'fdatasync' if number == 148 else 'fsync',
                                'fd': stream_fd, 'returned': ret,
                                'path': '/dev/nflasha4', 'policy': 'observed-dump',
                                'dirty': bool(entry.get('dirty'))})
                            self.report['syscall_responses_supplied'] += 1
                            uc.reg_write(arm.UC_ARM_REG_R0, ret)
                            return
                        if number in (4, 146, 180, 181):
                            self.report.update(status='unsupported_nflasha4_contract', boundary={
                                'reason': 'nflasha4_write_not_supplied', 'number': number,
                                'fd': stream_fd, 'path': '/dev/nflasha4',
                                'pc': pc, 'r7': number, 'instruction_address': pc - size})
                            uc.emu_stop()
                            return
                        self.report.update(status='unsupported_nflasha4_contract', boundary={
                            'reason': 'nflasha4_file_operation_not_supplied',
                            'number': number, 'fd': stream_fd, 'path': '/dev/nflasha4',
                            'pc': pc, 'r7': number, 'instruction_address': pc - size})
                        uc.emu_stop()
                        return
                    if number == 19:
                        raw_offset = uc.reg_read(arm.UC_ARM_REG_R1)
                        offset = raw_offset - 0x100000000 if raw_offset & 0x80000000 else raw_offset
                        whence = uc.reg_read(arm.UC_ARM_REG_R2)
                        entry = self.filesystem.fds[stream_fd]
                        current = entry.get('offset', 0)
                        if whence == 0:
                            new_offset = offset
                        elif whence in (1, 2):
                            new_offset = current + offset
                        else:
                            self.report['serviced_syscalls'].append({
                                'syscall': 'lseek', 'fd': stream_fd, 'offset': offset,
                                'whence': whence, 'returned': -22,
                                'path': '/dev/nflasha4', 'policy': 'position-only observation'})
                            uc.reg_write(arm.UC_ARM_REG_R0, 0xffffffea)
                            return
                        if new_offset < 0 or new_offset > 0x7fffffff:
                            uc.reg_write(arm.UC_ARM_REG_R0, 0xffffffea)
                            return
                        entry['offset'] = new_offset
                        self.report['serviced_syscalls'].append({
                            'syscall': 'lseek', 'fd': stream_fd, 'offset': offset,
                            'whence': whence, 'returned': new_offset,
                            'path': '/dev/nflasha4', 'policy': 'position-only observation'})
                        self.report['syscall_responses_supplied'] += 1
                        uc.reg_write(arm.UC_ARM_REG_R0, new_offset)
                        return
                    self.report.update(status='unsupported_nflasha4_contract', boundary={
                        'reason': 'nflasha4_file_operation_not_supplied',
                        'number': number, 'fd': stream_fd, 'path': '/dev/nflasha4',
                        'pc': pc, 'r7': number, 'instruction_address': pc - size})
                    uc.emu_stop()
                    return
                if self.filesystem.fds.get(stream_fd, {}).get('device') == 'stream':
                    self._stream_boundary(UnsupportedStream('stream_file_operation_not_supported',
                                                           number=number, fd=stream_fd), pc, number)
                    return
                if self.filesystem.fds.get(stream_fd, {}).get('device') == 'stream2':
                    self._stream_boundary(UnsupportedStream('stream2_file_operation_not_supported',
                                                           number=number, fd=stream_fd,
                                                           device='/dev/stream2'), pc, number)
                    return
            if number == 3:
                fd = uc.reg_read(arm.UC_ARM_REG_R0)
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'tty':
                    self.report.update(status='unsupported_tty_contract', boundary={
                        'reason': 'tty_read_not_supplied', 'path': '/dev/tty',
                        'pc': pc, 'r7': number})
                    uc.emu_stop()
                    return
            if number == 3:  # sys_read on device fds
                fd = uc.reg_read(arm.UC_ARM_REG_R0)
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'usb_event':
                    buf = uc.reg_read(arm.UC_ARM_REG_R1)
                    count = uc.reg_read(arm.UC_ARM_REG_R2)
                    owner_id = self.filesystem.fds[fd].get('owner_id')
                    try:
                        bytes_read = self.usb_event.read(owner_id, count, lambda data: uc.mem_write(buf, data))
                    except UnsupportedUsbEvent as error:
                        self.report.update(status='unsupported_usb_event_contract', boundary={
                            **error.details, 'fd': fd, 'pc': pc, 'r7': number, 'instruction_address': pc - size})
                        uc.emu_stop()
                        return
                    if bytes_read is None:
                        if self.syscall_policy == 'threads':
                            self.threads.save_context(uc)
                            self.threads.threads[self.threads.current_tid].regs[arm.UC_ARM_REG_PC] = pc - size
                            next_tid, event = self.threads.handle_fd_wait(fd, 'read', pc - size)
                            event.update(pc=pc, instruction_address=pc - size, thumb=thumb, path='/dev/usb/event')
                            self.report['serviced_syscalls'].append(event)
                            if next_tid is not None:
                                self.threads.restore_context(uc, next_tid, getattr(self, 'kuser', None))
                            else:
                                self.report.update(status='blocked_read', boundary=event)
                                uc.emu_stop()
                            return
                        else:
                            self.report.update(status='blocked_read', boundary={'fd': fd, 'path': '/dev/usb/event', 'pc': pc})
                            uc.emu_stop()
                            return
                    else:
                        ret = bytes_read
                        event = {'syscall': 'read', 'r7': 3, 'fd': fd, 'count': count, 'returned': ret,
                                 'path': '/dev/usb/event', 'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                        self.report['serviced_syscalls'].append(event)
                        self.report['syscall_responses_supplied'] += 1
                        uc.reg_write(arm.UC_ARM_REG_R0, ret)
                        return
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'pipe':
                    buf = uc.reg_read(arm.UC_ARM_REG_R1)
                    count = uc.reg_read(arm.UC_ARM_REG_R2)
                    entry = self.filesystem.fds[fd]
                    pipe_id = entry.get('pipe_id')
                    try:
                        data = self.pipes.read(pipe_id, count)
                    except UnsupportedPipe as error:
                        self.report.update(status='unsupported_pipe_contract', boundary={
                            **error.details, 'fd': fd, 'pc': pc, 'r7': number, 'instruction_address': pc - size})
                        uc.emu_stop()
                        return
                    if data is None:
                        if self.syscall_policy == 'threads':
                            self.threads.save_context(uc)
                            self.threads.threads[self.threads.current_tid].regs[arm.UC_ARM_REG_PC] = pc - size
                            next_tid, event = self.threads.handle_fd_wait(fd, 'read', pc - size)
                            event.update(pc=pc, instruction_address=pc - size, thumb=thumb, path=entry.get('path'))
                            self.report['serviced_syscalls'].append(event)
                            if next_tid is not None:
                                self.threads.restore_context(uc, next_tid, getattr(self, 'kuser', None))
                            else:
                                self.report.update(status='blocked_read', boundary=event)
                                uc.emu_stop()
                            return
                        else:
                            self.report.update(status='blocked_read', boundary={'fd': fd, 'path': entry.get('path'), 'pc': pc})
                            uc.emu_stop()
                            return
                    if data:
                        try:
                            self._uipc_write(buf, data)
                        except UnsupportedUipc as error:
                            self.report.update(status='unsupported_pipe_contract', boundary={
                                **error.details, 'fd': fd, 'pc': pc, 'r7': number})
                            uc.emu_stop()
                            return
                    ret = len(data)
                    event = {'syscall': 'read', 'r7': 3, 'fd': fd, 'count': count, 'returned': ret,
                             'path': entry.get('path'), 'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
            if number == 4:
                fd = uc.reg_read(arm.UC_ARM_REG_R0)
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'tty':
                    tty = getattr(self, 'tty', None)
                    if tty is None:
                        self.report.update(status='unsupported_tty_contract', boundary={
                            'reason': 'tty_device_not_supplied', 'path': '/dev/tty',
                            'pc': pc, 'r7': number})
                        uc.emu_stop()
                        return
                    from src.a6400.execution.guest_tty import UnsupportedTtyError
                    try:
                        data = bytes(uc.mem_read(
                            uc.reg_read(arm.UC_ARM_REG_R1),
                            uc.reg_read(arm.UC_ARM_REG_R2)))
                    except unicorn.UcError:
                        ret = (-14) & 0xffffffff
                    else:
                        try:
                            ret = tty.write(
                                self.filesystem.fds[fd].get('owner_id'), data,
                                tid=self.threads.current_tid)
                        except UnsupportedTtyError as error:
                            self.report.update(status='unsupported_tty_contract', boundary={
                                **error.details, 'path': '/dev/tty',
                                'pc': pc, 'r7': number})
                            uc.emu_stop()
                            return
                    self.report['serviced_syscalls'].append({
                        'syscall': 'write', 'r7': 4, 'fd': fd, 'path': '/dev/tty',
                        'returned': ret, 'policy': 'log-sink', 'pc': pc,
                        'instruction_address': pc - size, 'thumb': thumb})
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
            if number == 4:  # write on pipe fds
                fd = uc.reg_read(arm.UC_ARM_REG_R0)
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'pipe':
                    buf = uc.reg_read(arm.UC_ARM_REG_R1)
                    count = uc.reg_read(arm.UC_ARM_REG_R2)
                    entry = self.filesystem.fds[fd]
                    pipe_id = entry.get('pipe_id')
                    try:
                        data = self._uipc_read(buf, count)
                        ret = self.pipes.write(pipe_id, data)
                    except (UnsupportedUipc, UnsupportedPipe) as error:
                        self.report.update(status='unsupported_pipe_contract', boundary={
                            **error.details, 'fd': fd, 'pc': pc, 'r7': number, 'instruction_address': pc - size})
                        uc.emu_stop()
                        return
                    except UnverifiedGuestData as error:
                        self._identity_boundary(error.details)
                        return
                    read_fd = entry.get('peer_fd')
                    if read_fd is not None and hasattr(self, 'threads'):
                        self.threads.handle_fd_wake(read_fd)
                    event = {'syscall': 'write', 'r7': 4, 'fd': fd, 'count': count, 'returned': ret,
                             'path': entry.get('path'), 'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') in ('hdmi', 'cec'):
                    buf = uc.reg_read(arm.UC_ARM_REG_R1)
                    count = uc.reg_read(arm.UC_ARM_REG_R2)
                    entry = self.filesystem.fds[fd]
                    dev_name = entry.get('device')
                    drv = self.hdmi if dev_name == 'hdmi' else self.cec
                    try:
                        data = self._uipc_read(buf, count)
                        ret = drv.write(entry.get('owner_id'), data)
                    except (UnsupportedUipc, UnsupportedHdmi, UnsupportedCec) as error:
                        self.report.update(status=f'unsupported_{dev_name}_contract', boundary={
                            **error.details, 'fd': fd, 'pc': pc, 'r7': number, 'instruction_address': pc - size})
                        uc.emu_stop()
                        return
                    except UnverifiedGuestData as error:
                        self._identity_boundary(error.details)
                        return
                    event = {'syscall': 'write', 'r7': 4, 'fd': fd, 'count': count, 'returned': ret,
                             'path': entry.get('path'), 'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
            if number in (4, 146):  # write / writev on stdio
                fd = uc.reg_read(arm.UC_ARM_REG_R0)
                if (number == 146 and fd in self.filesystem.fds
                        and self.filesystem.fds[fd].get('device') == 'tty'):
                    tty = getattr(self, 'tty', None)
                    iov_ptr = uc.reg_read(arm.UC_ARM_REG_R1)
                    iovcnt = uc.reg_read(arm.UC_ARM_REG_R2)
                    if tty is None:
                        self.report.update(status='unsupported_tty_contract', boundary={
                            'reason': 'tty_device_not_supplied', 'path': '/dev/tty',
                            'pc': pc, 'r7': number})
                        uc.emu_stop()
                        return
                    from src.a6400.execution.guest_tty import UnsupportedTtyError
                    if iovcnt > 16:
                        self.report.update(status='unsupported_tty_contract', boundary={
                            'reason': 'tty_writev_iovcnt_too_large', 'iovcnt': iovcnt,
                            'path': '/dev/tty', 'pc': pc, 'r7': number})
                        uc.emu_stop()
                        return
                    try:
                        raw = bytes(uc.mem_read(iov_ptr, 8 * iovcnt))
                        chunks = []
                        total = 0
                        for index in range(iovcnt):
                            base, length = struct.unpack_from('<II', raw, 8 * index)
                            total += length
                            if total > 0x10000:
                                raise UnsupportedTtyError(
                                    'tty_writev_too_large', total=total)
                            chunks.append(bytes(uc.mem_read(base, length)))
                        ret = tty.write(
                            self.filesystem.fds[fd].get('owner_id'),
                            b''.join(chunks), tid=self.threads.current_tid)
                    except unicorn.UcError:
                        ret = (-14) & 0xffffffff
                    except UnsupportedTtyError as error:
                        self.report.update(status='unsupported_tty_contract', boundary={
                            **error.details, 'path': '/dev/tty', 'pc': pc, 'r7': number})
                        uc.emu_stop()
                        return
                    self.report['serviced_syscalls'].append({
                        'syscall': 'writev', 'r7': 146, 'fd': fd,
                        'path': '/dev/tty', 'iovcnt': iovcnt, 'returned': ret,
                        'policy': 'log-sink', 'pc': pc,
                        'instruction_address': pc - size, 'thumb': thumb})
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if self.stdio.is_stdio_fd(fd):
                    if number == 4:
                        buf = uc.reg_read(arm.UC_ARM_REG_R1)
                        count = uc.reg_read(arm.UC_ARM_REG_R2)
                        try:
                            data = self._stream_host_read(buf, count) if hasattr(self, 'stream') else bytes(uc.mem_read(buf, count))
                        except UnverifiedGuestData as error:
                            self._identity_boundary(error.details)
                            return
                        except UnsupportedStream as error:
                            self._stream_boundary(error, pc, number)
                            return
                        ret = self.stdio.handle_write(fd, data)
                        event = {'syscall': 'write', 'r7': 4, 'fd': fd, 'count': count, 'returned': ret,
                                 'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                    else:
                        iov_ptr = uc.reg_read(arm.UC_ARM_REG_R1)
                        iovcnt = uc.reg_read(arm.UC_ARM_REG_R2)
                        try:
                            reader = self._stream_host_read if hasattr(self, 'stream') else lambda a, s: bytes(uc.mem_read(a, s))
                            ret = self.stdio.handle_writev(reader, fd, iov_ptr, iovcnt)
                        except UnverifiedGuestData as error:
                            self._identity_boundary(error.details)
                            return
                        except UnsupportedStream as error:
                            self._stream_boundary(error, pc, number)
                            return
                        event = {'syscall': 'writev', 'r7': 146, 'fd': fd, 'iovcnt': iovcnt, 'returned': ret,
                                 'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
            if number == 197:  # fstat64 on stdio
                fd = uc.reg_read(arm.UC_ARM_REG_R0)
                buf = uc.reg_read(arm.UC_ARM_REG_R1)
                if self.stdio.is_stdio_fd(fd):
                    ret = self.stdio.handle_fstat64(lambda a, d: uc.mem_write(a, d), fd, buf)
                    event = {'syscall': 'fstat64', 'r7': 197, 'fd': fd, 'buf': buf, 'returned': ret,
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return

                elif fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'fb0':
                    ret = self.fb.handle_fstat64(lambda a, d: uc.mem_write(a, d), buf)
                    event = {'syscall': 'fstat64', 'r7': 197, 'fd': fd, 'buf': buf, 'returned': ret,
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb, 'path': '/dev/fb0'}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                elif fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'mem':
                    stat_bytes = bytearray(104)
                    st_dev = 0x0101
                    st_rdev = 0x0101
                    st_ino = 1001
                    st_mode = 0o20640
                    struct.pack_into('<Q', stat_bytes, 0, st_dev)
                    struct.pack_into('<I', stat_bytes, 12, 0)
                    struct.pack_into('<I', stat_bytes, 16, st_ino)
                    struct.pack_into('<I', stat_bytes, 20, st_mode)
                    struct.pack_into('<I', stat_bytes, 24, 1)
                    struct.pack_into('<I', stat_bytes, 28, 0)
                    struct.pack_into('<I', stat_bytes, 32, 0)
                    struct.pack_into('<Q', stat_bytes, 36, st_rdev)
                    struct.pack_into('<q', stat_bytes, 48, 0)
                    struct.pack_into('<I', stat_bytes, 56, 4096)
                    struct.pack_into('<q', stat_bytes, 64, 0)
                    uc.mem_write(buf, bytes(stat_bytes))
                    ret = 0
                    event = {'syscall': 'fstat64', 'r7': 197, 'fd': fd, 'buf': buf, 'returned': ret,
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb, 'path': '/dev/mem'}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
            if number == 5:  # open for /dev/uipc or /dev/fb0
                path_ptr = uc.reg_read(arm.UC_ARM_REG_R0)
                flags = uc.reg_read(arm.UC_ARM_REG_R1)
                preview = cstring_preview(uc, path_ptr)
                if preview.get('status') == 'terminated' and preview.get('value') == '/dev/dmpgles2':
                    try:
                        self._uipc_read(path_ptr, len(b'/dev/dmpgles2\0'))
                    except UnverifiedGuestData as error:
                        self._identity_boundary(error.details)
                        return
                    except UnsupportedUipc as error:
                        self.report.update(status='unsupported_gles_contract', boundary={
                            **error.details, 'pc': pc, 'r7': number})
                        uc.emu_stop()
                        return
                    if not hasattr(self, 'gles') or self.gles is None:
                        self.report.update(status='unsupported_gles_contract', boundary={
                            'reason': 'gles_kernel_process_binding_not_supplied',
                            'path': '/dev/dmpgles2', 'flags': flags, 'pc': pc, 'r7': number,
                            'instruction_address': pc - size,
                            'guest_tid': self.threads.current_tid if hasattr(self, 'threads') else None,
                            'guest_tgid': self.threads.process_id if hasattr(self, 'threads') else None})
                        uc.emu_stop()
                        return
                    caller_pid = self.threads.current_tid if hasattr(self, 'threads') else None
                    caller_tgid = self.threads.process_id if hasattr(self, 'threads') else None
                    ranges = []
                    if 'stack' in self.report and self.report['stack']:
                        ranges.append((self.report['stack']['bottom'], self.report['stack']['size']))
                    if hasattr(self, 'mmap') and self.mmap:
                        ranges.extend((m['address'], m['length']) for m in self.mmap.mappings)
                    try:
                        owner = self.gles.open(flags, caller_pid, caller_tgid, ranges)
                    except (UnsupportedKernelBinding, UnsupportedGles) as error:
                        self.report.update(status='unsupported_gles_contract', boundary={
                            **error.details, 'path': '/dev/dmpgles2', 'flags': flags,
                            'pc': pc, 'r7': number, 'instruction_address': pc - size,
                            'guest_tid': caller_pid, 'guest_tgid': caller_tgid})
                        uc.emu_stop()
                        return
                    fd = next((candidate for candidate in range(3, 259) if candidate not in self.filesystem.fds), None)
                    if fd is None:
                        ret = 0xffffffe8
                    else:
                        ret = fd
                        self.filesystem.fds[fd] = {'path': '/dev/dmpgles2', 'device': 'dmpgles2', 'flags': flags,
                                                   'owner_id': owner['owner_id'], 'device_number': [self.gles.major, self.gles.minor]}
                    event = {'syscall': 'open', 'r7': 5, 'path': '/dev/dmpgles2', 'fd': fd, 'returned': ret,
                             'flags': flags, 'device_number': [self.gles.major, self.gles.minor],
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if (preview.get('status') == 'terminated' and preview.get('value') == '/dev/usb/kikilog'
                        and getattr(self, 'kikilog', None) is not None):
                    node = self.filesystem.nodes.get('/dev/usb/kikilog', {})
                    if (node.get('kind') != 'special' or node.get('mode', 0) & 0xf000 != 0x2000
                            or node.get('stat_metadata', {}).get('device_number') != {'major': 248, 'minor': 10}):
                        self.report.update(status='unsupported_kikilog_contract', boundary={
                            'reason': 'kikilog_image_node_identity_mismatch', 'pc': pc, 'r7': number})
                        uc.emu_stop()
                        return
                    fd = next((candidate for candidate in range(3, 259) if candidate not in self.filesystem.fds), None)
                    try:
                        owner = None if fd is None else self.kikilog.open(flags, self.threads.current_tid,
                                                                         self.threads.process_id)
                    except UnsupportedKikilog as error:
                        self.report.update(status='unsupported_kikilog_contract', boundary={
                            **error.details, 'pc': pc, 'r7': number})
                        uc.emu_stop()
                        return
                    if fd is not None:
                        self.filesystem.fds[fd] = {'path': '/dev/usb/kikilog', 'device': 'kikilog',
                                                   'owner_id': owner, 'flags': flags, 'device_number': [248, 10]}
                    ret = fd if fd is not None else (-24) & 0xffffffff
                    self.report['serviced_syscalls'].append({'syscall': 'open', 'r7': 5, 'fd': fd,
                        'path': '/dev/usb/kikilog', 'flags': flags, 'returned': ret, 'pc': pc,
                        'instruction_address': pc - size, 'thumb': thumb, 'source': self.kikilog.source_sha256})
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if preview.get('status') == 'terminated' and preview.get('value') == '/dev/tty':
                    try:
                        self._uipc_read(path_ptr, len(b'/dev/tty\0'))
                    except UnverifiedGuestData as error:
                        self._identity_boundary(error.details)
                        return
                    except UnsupportedUipc as error:
                        self.report.update(status='unsupported_tty_contract', boundary={
                            **error.details, 'pc': pc, 'r7': number})
                        uc.emu_stop()
                        return
                    tty = getattr(self, 'tty', None)
                    if tty is None:
                        self.report.update(status='unsupported_tty_contract', boundary={
                            'reason': 'tty_device_not_supplied', 'path': '/dev/tty',
                            'flags': flags, 'pc': pc, 'r7': number,
                            'instruction_address': pc - size})
                        uc.emu_stop()
                        return
                    from src.a6400.execution.guest_tty import UnsupportedTtyError
                    fd = next((candidate for candidate in range(3, 259) if candidate not in self.filesystem.fds), None)
                    if fd is None:
                        ret = (-24) & 0xffffffff
                    else:
                        try:
                            owner = tty.open(flags, self.threads.current_tid,
                                             self.threads.process_id)
                        except UnsupportedTtyError as error:
                            self.report.update(status='unsupported_tty_contract', boundary={
                                **error.details, 'path': '/dev/tty', 'flags': flags,
                                'pc': pc, 'r7': number})
                            uc.emu_stop()
                            return
                        ret = fd
                        self.filesystem.fds[fd] = {
                            'path': '/dev/tty', 'device': 'tty', 'flags': flags,
                            'owner_id': owner}
                    event = {'syscall': 'open', 'r7': 5, 'path': '/dev/tty',
                             'fd': fd, 'returned': ret, 'flags': flags,
                             'policy': 'log-sink', 'pc': pc,
                             'instruction_address': pc - size, 'thumb': thumb}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if preview.get('status') == 'terminated' and preview.get('value') == '/dev/gpio':
                    try:
                        self._uipc_read(path_ptr, len(b'/dev/gpio\0'))
                    except UnverifiedGuestData as error:
                        self._identity_boundary(error.details)
                        return
                    except UnsupportedUipc as error:
                        self.report.update(status='unsupported_gpio_contract', boundary={
                            **error.details, 'pc': pc, 'r7': number})
                        uc.emu_stop()
                        return
                    if not hasattr(self, 'gpio') or self.gpio is None:
                        self.report.update(status='unsupported_gpio_contract', boundary={
                            'reason': 'gpio_device_not_supplied',
                            'path': '/dev/gpio', 'flags': flags, 'pc': pc, 'r7': number,
                            'instruction_address': pc - size,
                            'guest_tid': self.threads.current_tid if hasattr(self, 'threads') else None,
                            'guest_tgid': self.threads.process_id if hasattr(self, 'threads') else None})
                        uc.emu_stop()
                        return
                    caller_pid = self.threads.current_tid if hasattr(self, 'threads') else None
                    caller_tgid = self.threads.process_id if hasattr(self, 'threads') else None
                    try:
                        owner = self.gpio.open(flags, caller_pid, caller_tgid)
                    except UnsupportedGpio as error:
                        self.report.update(status='unsupported_gpio_contract', boundary={
                            **error.details, 'path': '/dev/gpio', 'flags': flags,
                            'pc': pc, 'r7': number, 'instruction_address': pc - size,
                            'guest_tid': caller_pid, 'guest_tgid': caller_tgid})
                        uc.emu_stop()
                        return
                    fd = next((candidate for candidate in range(3, 259) if candidate not in self.filesystem.fds), None)
                    if fd is None:
                        ret = 0xffffffe8
                    else:
                        ret = fd
                        self.filesystem.fds[fd] = {'path': '/dev/gpio', 'device': 'gpio', 'flags': flags,
                                                   'owner_id': owner['owner_id'], 'device_number': [self.gpio.major, self.gpio.minor]}
                    event = {'syscall': 'open', 'r7': 5, 'path': '/dev/gpio', 'fd': fd, 'returned': ret,
                             'flags': flags, 'device_number': [self.gpio.major, self.gpio.minor],
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if preview.get('status') == 'terminated' and preview.get('value') == '/dev/usb/otgcore':
                    try:
                        self._uipc_read(path_ptr, len(b'/dev/usb/otgcore\0'))
                    except UnverifiedGuestData as error:
                        self._identity_boundary(error.details)
                        return
                    except UnsupportedUipc as error:
                        self.report.update(status='unsupported_usb_otgcore_contract', boundary={
                            **error.details, 'pc': pc, 'r7': number})
                        uc.emu_stop()
                        return
                    if not hasattr(self, 'usb_otgcore') or self.usb_otgcore is None:
                        self.report.update(status='unsupported_usb_otgcore_contract', boundary={
                            'reason': 'usb_otgcore_device_not_supplied',
                            'path': '/dev/usb/otgcore', 'flags': flags, 'pc': pc, 'r7': number,
                            'instruction_address': pc - size,
                            'guest_tid': self.threads.current_tid if hasattr(self, 'threads') else None,
                            'guest_tgid': self.threads.process_id if hasattr(self, 'threads') else None})
                        uc.emu_stop()
                        return
                    caller_pid = self.threads.current_tid if hasattr(self, 'threads') else None
                    caller_tgid = self.threads.process_id if hasattr(self, 'threads') else None
                    try:
                        owner = self.usb_otgcore.open(flags, caller_pid, caller_tgid)
                    except UnsupportedUsbOtgCore as error:
                        self.report.update(status='unsupported_usb_otgcore_contract', boundary={
                            **error.details, 'path': '/dev/usb/otgcore', 'flags': flags,
                            'pc': pc, 'r7': number, 'instruction_address': pc - size,
                            'guest_tid': caller_pid, 'guest_tgid': caller_tgid})
                        uc.emu_stop()
                        return
                    fd = next((candidate for candidate in range(3, 259) if candidate not in self.filesystem.fds), None)
                    if fd is None:
                        ret = 0xffffffe8
                    else:
                        ret = fd
                        self.filesystem.fds[fd] = {'path': '/dev/usb/otgcore', 'device': 'usb_otgcore', 'flags': flags,
                                                   'owner_id': owner['owner_id'], 'device_number': [self.usb_otgcore.major, self.usb_otgcore.minor]}
                    event = {'syscall': 'open', 'r7': 5, 'path': '/dev/usb/otgcore', 'fd': fd, 'returned': ret,
                             'flags': flags, 'device_number': [self.usb_otgcore.major, self.usb_otgcore.minor],
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if preview.get('status') == 'terminated' and preview.get('value') == '/dev/hdmi':
                    try:
                        self._uipc_read(path_ptr, len(b'/dev/hdmi\0'))
                    except UnverifiedGuestData as error:
                        self._identity_boundary(error.details)
                        return
                    except UnsupportedUipc as error:
                        self.report.update(status='unsupported_hdmi_contract', boundary={
                            **error.details, 'pc': pc, 'r7': number})
                        uc.emu_stop()
                        return
                    if not hasattr(self, 'hdmi') or self.hdmi is None:
                        self.report.update(status='unsupported_hdmi_contract', boundary={
                            'reason': 'hdmi_device_not_supplied',
                            'path': '/dev/hdmi', 'flags': flags, 'pc': pc, 'r7': number,
                            'instruction_address': pc - size,
                            'guest_tid': self.threads.current_tid if hasattr(self, 'threads') else None,
                            'guest_tgid': self.threads.process_id if hasattr(self, 'threads') else None})
                        uc.emu_stop()
                        return
                    caller_pid = self.threads.current_tid if hasattr(self, 'threads') else None
                    caller_tgid = self.threads.process_id if hasattr(self, 'threads') else None
                    try:
                        owner = self.hdmi.open(flags, caller_pid, caller_tgid)
                    except UnsupportedHdmi as error:
                        self.report.update(status='unsupported_hdmi_contract', boundary={
                            **error.details, 'path': '/dev/hdmi', 'flags': flags,
                            'pc': pc, 'r7': number, 'instruction_address': pc - size,
                            'guest_tid': caller_pid, 'guest_tgid': caller_tgid})
                        uc.emu_stop()
                        return
                    fd = next((candidate for candidate in range(3, 259) if candidate not in self.filesystem.fds), None)
                    if fd is None:
                        ret = 0xffffffe8
                    else:
                        ret = fd
                        self.filesystem.fds[fd] = {'path': '/dev/hdmi', 'device': 'hdmi', 'flags': flags,
                                                   'owner_id': owner['owner_id'], 'device_number': [self.hdmi.major, self.hdmi.minor]}
                    event = {'syscall': 'open', 'r7': 5, 'path': '/dev/hdmi', 'fd': fd, 'returned': ret,
                             'flags': flags, 'device_number': [self.hdmi.major, self.hdmi.minor],
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if preview.get('status') == 'terminated' and preview.get('value') == '/dev/cec':
                    try:
                        self._uipc_read(path_ptr, len(b'/dev/cec\0'))
                    except UnverifiedGuestData as error:
                        self._identity_boundary(error.details)
                        return
                    except UnsupportedUipc as error:
                        self.report.update(status='unsupported_cec_contract', boundary={
                            **error.details, 'pc': pc, 'r7': number})
                        uc.emu_stop()
                        return
                    if not hasattr(self, 'cec') or self.cec is None:
                        self.report.update(status='unsupported_cec_contract', boundary={
                            'reason': 'cec_device_not_supplied',
                            'path': '/dev/cec', 'flags': flags, 'pc': pc, 'r7': number,
                            'instruction_address': pc - size,
                            'guest_tid': self.threads.current_tid if hasattr(self, 'threads') else None,
                            'guest_tgid': self.threads.process_id if hasattr(self, 'threads') else None})
                        uc.emu_stop()
                        return
                    caller_pid = self.threads.current_tid if hasattr(self, 'threads') else None
                    caller_tgid = self.threads.process_id if hasattr(self, 'threads') else None
                    try:
                        owner = self.cec.open(flags, caller_pid, caller_tgid)
                    except UnsupportedCec as error:
                        self.report.update(status='unsupported_cec_contract', boundary={
                            **error.details, 'path': '/dev/cec', 'flags': flags,
                            'pc': pc, 'r7': number, 'instruction_address': pc - size,
                            'guest_tid': caller_pid, 'guest_tgid': caller_tgid})
                        uc.emu_stop()
                        return
                    fd = next((candidate for candidate in range(3, 259) if candidate not in self.filesystem.fds), None)
                    if fd is None:
                        ret = 0xffffffe8
                    else:
                        ret = fd
                        self.filesystem.fds[fd] = {'path': '/dev/cec', 'device': 'cec', 'flags': flags,
                                                   'owner_id': owner['owner_id'], 'device_number': [self.cec.major, self.cec.minor]}
                    event = {'syscall': 'open', 'r7': 5, 'path': '/dev/cec', 'fd': fd, 'returned': ret,
                             'flags': flags, 'device_number': [self.cec.major, self.cec.minor],
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if preview.get('status') == 'terminated' and preview.get('value') in MMC_CHAR_NODES:
                    node_path = preview['value']
                    try:
                        self._uipc_read(path_ptr, len(node_path.encode('ascii')) + 1)
                    except UnverifiedGuestData as error:
                        self._identity_boundary(error.details)
                        return
                    except UnsupportedUipc as error:
                        self.report.update(status='unsupported_mmca_char_contract', boundary={
                            **error.details, 'pc': pc, 'r7': number})
                        uc.emu_stop()
                        return
                    if not hasattr(self, 'mmca_char') or self.mmca_char is None:
                        self.report.update(status='unsupported_mmca_char_contract', boundary={
                            'reason': 'mmca_char_device_not_supplied',
                            'path': node_path, 'flags': flags, 'pc': pc, 'r7': number,
                            'instruction_address': pc - size,
                            'guest_tid': self.threads.current_tid if hasattr(self, 'threads') else None,
                            'guest_tgid': self.threads.process_id if hasattr(self, 'threads') else None})
                        uc.emu_stop()
                        return
                    caller_pid = self.threads.current_tid if hasattr(self, 'threads') else None
                    caller_tgid = self.threads.process_id if hasattr(self, 'threads') else None
                    try:
                        owner = self.mmca_char.open(flags, caller_pid, caller_tgid, path=node_path)
                    except UnsupportedMmcChar as error:
                        self.report.update(status='unsupported_mmca_char_contract', boundary={
                            **error.details, 'path': node_path, 'flags': flags,
                            'pc': pc, 'r7': number, 'instruction_address': pc - size,
                            'guest_tid': caller_pid, 'guest_tgid': caller_tgid})
                        uc.emu_stop()
                        return
                    fd = next((candidate for candidate in range(3, 259) if candidate not in self.filesystem.fds), None)
                    dev_num = [owner['major'], owner['minor']]
                    if fd is None:
                        ret = 0xffffffe8
                    else:
                        ret = fd
                        self.filesystem.fds[fd] = {'path': node_path, 'device': 'mmca_char', 'flags': flags,
                                                   'owner_id': owner['owner_id'], 'device_number': dev_num}
                    event = {'syscall': 'open', 'r7': 5, 'path': node_path, 'fd': fd, 'returned': ret,
                             'flags': flags, 'device_number': dev_num,
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if (preview.get('status') == 'terminated' and preview.get('value') == '/dev/sata'
                        and hasattr(self, 'mmca_char') and self.mmca_char is not None):
                    try:
                        self._uipc_read(path_ptr, len(b'/dev/sata\0'))
                    except UnverifiedGuestData as error:
                        self._identity_boundary(error.details)
                        return
                    except UnsupportedUipc as error:
                        self.report.update(status='unsupported_mmca_char_contract', boundary={
                            **error.details, 'pc': pc, 'r7': number})
                        uc.emu_stop()
                        return
                    ret = 0xfffffffa  # -ENXIO: major 249 has no sata driver on ILCE-6400
                    event = {'syscall': 'open', 'r7': 5, 'path': '/dev/sata', 'fd': None, 'returned': ret,
                             'flags': flags, 'device_number': [249, 2],
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if preview.get('status') == 'terminated' and preview.get('value') == '/dev/usb/event':
                    try:
                        self._uipc_read(path_ptr, len(b'/dev/usb/event\0'))
                    except UnverifiedGuestData as error:
                        self._identity_boundary(error.details)
                        return
                    except UnsupportedUipc as error:
                        self.report.update(status='unsupported_usb_event_contract', boundary={
                            **error.details, 'pc': pc, 'r7': number})
                        uc.emu_stop()
                        return
                    if not hasattr(self, 'usb_event') or self.usb_event is None:
                        self.report.update(status='unsupported_usb_event_contract', boundary={
                            'reason': 'usb_event_device_not_supplied',
                            'path': '/dev/usb/event', 'flags': flags, 'pc': pc, 'r7': number,
                            'instruction_address': pc - size,
                            'guest_tid': self.threads.current_tid if hasattr(self, 'threads') else None,
                            'guest_tgid': self.threads.process_id if hasattr(self, 'threads') else None})
                        uc.emu_stop()
                        return
                    caller_pid = self.threads.current_tid if hasattr(self, 'threads') else None
                    caller_tgid = self.threads.process_id if hasattr(self, 'threads') else None
                    try:
                        owner = self.usb_event.open(flags, caller_pid, caller_tgid)
                    except UnsupportedUsbEvent as error:
                        self.report.update(status='unsupported_usb_event_contract', boundary={
                            **error.details, 'path': '/dev/usb/event', 'flags': flags,
                            'pc': pc, 'r7': number, 'instruction_address': pc - size,
                            'guest_tid': caller_pid, 'guest_tgid': caller_tgid})
                        uc.emu_stop()
                        return
                    fd = next((candidate for candidate in range(3, 259) if candidate not in self.filesystem.fds), None)
                    if fd is None:
                        ret = 0xffffffe8
                    else:
                        ret = fd
                        self.filesystem.fds[fd] = {'path': '/dev/usb/event', 'device': 'usb_event', 'flags': flags,
                                                   'owner_id': owner['owner_id'], 'device_number': [self.usb_event.major, self.usb_event.minor]}
                    event = {'syscall': 'open', 'r7': 5, 'path': '/dev/usb/event', 'fd': fd, 'returned': ret,
                             'flags': flags, 'device_number': [self.usb_event.major, self.usb_event.minor],
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if preview.get('status') == 'terminated' and preview.get('value') == '/dev/usb/buspwr':
                    try:
                        self._uipc_read(path_ptr, len(b'/dev/usb/buspwr\0'))
                    except UnverifiedGuestData as error:
                        self._identity_boundary(error.details)
                        return
                    except UnsupportedUipc as error:
                        self.report.update(status='unsupported_usb_buspower_contract', boundary={
                            **error.details, 'pc': pc, 'r7': number})
                        uc.emu_stop()
                        return
                    if not hasattr(self, 'usb_buspower') or self.usb_buspower is None:
                        self.report.update(status='unsupported_usb_buspower_contract', boundary={
                            'reason': 'usb_buspower_device_not_supplied',
                            'path': '/dev/usb/buspwr', 'flags': flags, 'pc': pc, 'r7': number,
                            'instruction_address': pc - size,
                            'guest_tid': self.threads.current_tid if hasattr(self, 'threads') else None,
                            'guest_tgid': self.threads.process_id if hasattr(self, 'threads') else None})
                        uc.emu_stop()
                        return
                    caller_pid = self.threads.current_tid if hasattr(self, 'threads') else None
                    caller_tgid = self.threads.process_id if hasattr(self, 'threads') else None
                    try:
                        owner = self.usb_buspower.open(flags, caller_pid, caller_tgid)
                    except UnsupportedUsbBusPower as error:
                        self.report.update(status='unsupported_usb_buspower_contract', boundary={
                            **error.details, 'path': '/dev/usb/buspwr', 'flags': flags,
                            'pc': pc, 'r7': number, 'instruction_address': pc - size,
                            'guest_tid': caller_pid, 'guest_tgid': caller_tgid})
                        uc.emu_stop()
                        return
                    fd = next((candidate for candidate in range(3, 259) if candidate not in self.filesystem.fds), None)
                    if fd is None:
                        ret = 0xffffffe8
                    else:
                        ret = fd
                        self.filesystem.fds[fd] = {'path': '/dev/usb/buspwr', 'device': 'usb_buspower', 'flags': flags,
                                                   'owner_id': owner['owner_id'], 'device_number': [self.usb_buspower.major, self.usb_buspower.minor]}
                    event = {'syscall': 'open', 'r7': 5, 'path': '/dev/usb/buspwr', 'fd': fd, 'returned': ret,
                             'flags': flags, 'device_number': [self.usb_buspower.major, self.usb_buspower.minor],
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if hasattr(self, 'stream') and preview.get('value') == '/dev/stream':
                    try:
                        self.filesystem._path(path_ptr)  # Bounds and provenance, not just diagnostic preview.
                        self.stream.open(flags)
                    except UnverifiedGuestData as error:
                        self._identity_boundary(error.details)
                        return
                    except UnsupportedStream as error:
                        self._stream_boundary(error, pc, number)
                        return
                    fd = next((candidate for candidate in range(3, 259) if candidate not in self.filesystem.fds), None)
                    if fd is None:
                        ret = 0xffffffe8  # -EMFILE; no descriptor is created.
                    else:
                        ret = fd
                        self.filesystem.fds[fd] = {'path': '/dev/stream', 'device': 'stream', 'flags': flags,
                                                   'device_number': [249, 7], 'offset': 0}
                    event = {'syscall': 'open', 'r7': 5, 'path': '/dev/stream', 'fd': fd, 'returned': ret,
                             'flags': flags, 'device_number': [249, 7], 'pc': pc,
                             'instruction_address': pc - size, 'thumb': thumb}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if (preview.get('value') == '/dev/stream2'
                        and getattr(self, 'stream2_device_policy', 'stop') == 'open-only'):
                    try:
                        self.filesystem._path(path_ptr)  # Bounds and provenance.
                    except UnverifiedGuestData as error:
                        self._identity_boundary(error.details)
                        return
                    if flags not in (0x1002, 0x21002):
                        self._stream_boundary(UnsupportedStream(
                            'stream2_open_flags_not_supported', flags=flags,
                            device='/dev/stream2'), pc, number)
                        return
                    fd = next((candidate for candidate in range(3, 259)
                               if candidate not in self.filesystem.fds), None)
                    if fd is None:
                        ret = 0xffffffe8  # -EMFILE
                    else:
                        ret = fd
                        self.filesystem.fds[fd] = {
                            'path': '/dev/stream2', 'device': 'stream2', 'flags': flags,
                            'device_number': [249, 8], 'offset': 0}
                    event = {'syscall': 'open', 'r7': 5, 'path': '/dev/stream2', 'fd': fd,
                             'returned': ret, 'flags': flags, 'device_number': [249, 8],
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb,
                             'policy': 'open-only; ioctl/mmap remains a boundary'}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if (preview.get('value') == '/dev/nflasha4'
                        and getattr(self, 'nflasha4_device_policy', 'stop') in ('open-only', 'observed-dump')):
                    try:
                        self.filesystem._path(path_ptr)  # Bounds and provenance.
                    except UnverifiedGuestData as error:
                        self._identity_boundary(error.details)
                        return
                    policy = getattr(self, 'nflasha4_device_policy', 'stop')
                    if policy == 'observed-dump' and getattr(self, 'nflasha4_dump', None) is None:
                        self.report.update(status='unsupported_nflasha4_contract', boundary={
                            'reason': 'nflasha4_dump_identity_missing', 'path': '/dev/nflasha4',
                            'pc': pc, 'r7': number, 'instruction_address': pc - size})
                        uc.emu_stop()
                        return
                    if flags != 2:
                        self.report.update(status='unsupported_nflasha4_contract', boundary={
                            'reason': 'nflasha4_open_flags_not_supported', 'path': '/dev/nflasha4',
                            'flags': flags, 'pc': pc, 'r7': number,
                            'instruction_address': pc - size})
                        uc.emu_stop()
                        return
                    node = getattr(self.filesystem, 'nodes', {}).get('/dev/nflasha4', {})
                    metadata = node.get('stat_metadata') or {}
                    device_number = metadata.get('device_number')
                    if isinstance(device_number, dict):
                        device_number = [device_number.get('major'), device_number.get('minor')]
                    fd = next((candidate for candidate in range(3, 259)
                               if candidate not in self.filesystem.fds), None)
                    if fd is None:
                        ret = 0xffffffe8  # -EMFILE
                    else:
                        ret = fd
                        self.filesystem.fds[fd] = {
                            'path': '/dev/nflasha4', 'device': 'nflasha4', 'flags': flags,
                            'device_number': device_number, 'offset': 0, 'dirty': False}
                    event = {'syscall': 'open', 'r7': 5, 'path': '/dev/nflasha4', 'fd': fd,
                             'returned': ret, 'flags': flags, 'device_number': device_number,
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb,
                             'policy': ('observed-dump: reads served from the captured MPR image; '
                                        'only ioctl 0x80014123 answered; writes/mmap/other ioctls remain boundaries'
                                        if policy == 'observed-dump' else
                                        'open-only; internal flash data/ioctl/mmap remains a boundary')}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if preview.get('status') == 'terminated' and preview.get('value') == '/dev/uipc':
                    fd = next((candidate for candidate in range(3, 259) if candidate not in self.filesystem.fds), None)
                    self.filesystem.fds[fd] = {'path': '/dev/uipc', 'device': 'uipc', 'flags': flags, 'data': b''}
                    event = {'syscall': 'open', 'r7': 5, 'path': '/dev/uipc', 'fd': fd, 'returned': fd,
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, fd)
                    return
                if preview.get('status') == 'terminated' and preview.get('value') == '/dev/fb0':
                    fd = next((candidate for candidate in range(3, 259) if candidate not in self.filesystem.fds), None)
                    self.filesystem.fds[fd] = {'path': '/dev/fb0', 'device': 'fb0', 'flags': flags, 'data': b''}
                    event = {'syscall': 'open', 'r7': 5, 'path': '/dev/fb0', 'fd': fd, 'returned': fd,
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, fd)
                    return
                if preview.get('status') == 'terminated' and preview.get('value') == '/dev/mem':
                    fd = next((candidate for candidate in range(3, 259) if candidate not in self.filesystem.fds), None)
                    self.filesystem.fds[fd] = {'path': '/dev/mem', 'device': 'mem', 'flags': flags, 'data': b'',
                                               'device_number': [1, 1]}
                    event = {'syscall': 'open', 'r7': 5, 'path': '/dev/mem', 'fd': fd, 'returned': fd,
                             'flags': flags, 'device_number': [1, 1],
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, fd)
                    return
            if number == 54:  # ioctl
                fd = uc.reg_read(arm.UC_ARM_REG_R0)
                cmd = uc.reg_read(arm.UC_ARM_REG_R1)
                arg = uc.reg_read(arm.UC_ARM_REG_R2)
                if self.filesystem.fds.get(fd, {}).get('device') == 'kikilog':
                    try:
                        ret = self.kikilog.ioctl(self.filesystem.fds[fd]['owner_id'], cmd, arg)
                    except UnsupportedKikilog as error:
                        self.report.update(status='unsupported_kikilog_contract', boundary={
                            **error.details, 'fd': fd, 'pc': pc, 'r7': number,
                            'instruction_address': pc - size})
                        uc.emu_stop()
                        return
                    self.report['serviced_syscalls'].append({'syscall': 'ioctl', 'r7': 54,
                        'fd': fd, 'cmd': cmd, 'arg': arg, 'returned': ret, 'pc': pc,
                        'instruction_address': pc - size, 'thumb': thumb, 'device': 'kikilog',
                        'policy': self.kikilog.policy})
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret & 0xffffffff)
                    return
                if (getattr(getattr(self, 'uipc', None), 'pool_options_policy', '') == 'kernel-e0301'
                        and self.filesystem.fds.get(fd, {}).get('device') == 'urandom' and cmd == 0x5401):
                    # E0301: urandom_fops+0x20 -> original random_ioctl;
                    # ARM execution of TCGETS returns -EINVAL, no output copy.
                    ret = (-22) & 0xffffffff
                    self.report['serviced_syscalls'].append({
                        'syscall': 'ioctl', 'r7': 54, 'fd': fd, 'cmd': cmd, 'arg': arg,
                        'returned': ret, 'pc': pc, 'instruction_address': pc - size,
                        'thumb': thumb, 'device': 'urandom', 'source': 'original-kernel-e0301'})
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'tty':
                    self.report.update(status='unsupported_tty_contract', boundary={
                        'reason': 'tty_ioctl_not_supplied', 'path': '/dev/tty',
                        'cmd': cmd, 'arg': arg, 'pc': pc, 'r7': number})
                    uc.emu_stop()
                    return
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'dmpgles2':
                    owner_id = self.filesystem.fds[fd].get('owner_id')
                    try:
                        ret = self.gles.ioctl(
                            owner_id, cmd, arg,
                            lambda addr, sz: bytes(uc.mem_read(addr, sz)),
                            lambda addr, data: uc.mem_write(addr, data),
                            tid=(self.threads.current_tid
                                 if getattr(self, 'threads', None) is not None else None),
                        )
                    except UnsupportedGles as error:
                        self.report.update(status='unsupported_gles_contract', boundary={
                            **error.details, 'fd': fd, 'cmd': cmd, 'arg': arg,
                            'pc': pc, 'r7': number, 'instruction_address': pc - size})
                        uc.emu_stop()
                        return
                    event_pending = (cmd == 0xC0048203
                                     and getattr(self.gles, 'decoded_semantics', False)
                                     and getattr(self.gles, 'engine_model', False))
                    if (ret is None and (cmd == 0xC004820D or event_pending)
                            and getattr(self, 'threads', None) is not None):
                        # Kernel wait: completion wait 0xC004820D or event wait
                        # 0xC0048203 (handler 0xAD0 on dev+0x4C). Park the caller
                        # and retry after the corresponding wake; no fabricated
                        # timeout or status is injected.
                        self.threads.save_context(uc)
                        current = self.threads.threads[self.threads.current_tid]
                        current.regs[arm.UC_ARM_REG_PC] = pc - size
                        wait_op = 'gles_event' if event_pending else 'gles_wait'
                        next_tid, wait_event = self.threads.handle_fd_wait(fd, wait_op, pc - size)
                        reason = ('gles_event_wait_blocked' if event_pending
                                  else 'gles_wait_completion_blocked')
                        event = {'syscall': 'ioctl', 'r7': 54, 'fd': fd, 'cmd': cmd, 'arg': arg,
                                 'returned': None, 'pc': pc, 'instruction_address': pc - size,
                                 'thumb': thumb, 'device': 'dmpgles2',
                                 'reason': reason, **wait_event}
                        self.report['serviced_syscalls'].append(event)
                        self.report['syscall_responses_supplied'] += 1
                        if next_tid is not None:
                            self.threads.restore_context(uc, next_tid, getattr(self, 'kuser', None))
                        else:
                            self.report.update(status='blocked_gles_wait', boundary=dict(event))
                            uc.reg_write(arm.UC_ARM_REG_PC, (pc - size) | int(thumb))
                            uc.emu_stop()
                        return
                    event = {'syscall': 'ioctl', 'r7': 54, 'fd': fd, 'cmd': cmd, 'arg': arg, 'returned': ret,
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb, 'device': 'dmpgles2'}
                    if (cmd == 0xC004820E and getattr(self.gles, 'decoded_semantics', False)
                            and getattr(self, 'threads', None) is not None):
                        woken = self.threads.handle_fd_wake(fd)
                        if woken:
                            event['woken_tids'] = woken
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    if self.threads and cmd == GLES_LOCK_SEMAPHORE:
                        next_tid = self.threads.get_next_runnable_tid()
                        if next_tid is not None:
                            self.threads.save_context(uc)
                            self.threads.threads[self.threads.current_tid].state = 'runnable'
                            self.threads.restore_context(uc, next_tid, getattr(self, 'kuser', None))
                    return
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'gpio':
                    owner_id = self.filesystem.fds[fd].get('owner_id')
                    try:
                        ret = self.gpio.ioctl(
                            owner_id, cmd, arg,
                            lambda addr, sz: bytes(uc.mem_read(addr, sz)),
                            lambda addr, data: uc.mem_write(addr, data)
                        )
                    except UnsupportedGpio as error:
                        self.report.update(status='unsupported_gpio_contract', boundary={
                            **error.details, 'fd': fd, 'cmd': cmd, 'arg': arg,
                            'pc': pc, 'r7': number, 'instruction_address': pc - size})
                        uc.emu_stop()
                        return
                    event = {'syscall': 'ioctl', 'r7': 54, 'fd': fd, 'cmd': cmd, 'arg': arg, 'returned': ret,
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb, 'device': 'gpio'}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'usb_event':
                    owner_id = self.filesystem.fds[fd].get('owner_id')
                    try:
                        ret = self.usb_event.ioctl(
                            owner_id, cmd, arg,
                            lambda addr, sz: bytes(uc.mem_read(addr, sz)),
                            lambda addr, data: uc.mem_write(addr, data)
                        )
                    except UnsupportedUsbEvent as error:
                        self.report.update(status='unsupported_usb_event_contract', boundary={
                            **error.details, 'fd': fd, 'cmd': cmd, 'arg': arg,
                            'pc': pc, 'r7': number, 'instruction_address': pc - size})
                        uc.emu_stop()
                        return
                    event = {'syscall': 'ioctl', 'r7': 54, 'fd': fd, 'cmd': cmd, 'arg': arg, 'returned': ret,
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb, 'device': 'usb_event'}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'usb_buspower':
                    owner_id = self.filesystem.fds[fd].get('owner_id')
                    try:
                        ret = self.usb_buspower.ioctl(
                            owner_id, cmd, arg,
                            lambda addr, sz: bytes(uc.mem_read(addr, sz)),
                            lambda addr, data: uc.mem_write(addr, data)
                        )
                    except UnsupportedUsbBusPower as error:
                        self.report.update(status='unsupported_usb_buspower_contract', boundary={
                            **error.details, 'fd': fd, 'cmd': cmd, 'arg': arg,
                            'pc': pc, 'r7': number, 'instruction_address': pc - size})
                        uc.emu_stop()
                        return
                    event = {'syscall': 'ioctl', 'r7': 54, 'fd': fd, 'cmd': cmd, 'arg': arg, 'returned': ret,
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb, 'device': 'usb_buspower'}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'usb_otgcore':
                    owner_id = self.filesystem.fds[fd].get('owner_id')
                    try:
                        ret = self.usb_otgcore.ioctl(
                            owner_id, cmd, arg,
                            lambda addr, sz: bytes(uc.mem_read(addr, sz)),
                            lambda addr, data: uc.mem_write(addr, data)
                        )
                    except UnsupportedUsbOtgCore as error:
                        self.report.update(status='unsupported_usb_otgcore_contract', boundary={
                            **error.details, 'fd': fd, 'cmd': cmd, 'arg': arg,
                            'pc': pc, 'r7': number, 'instruction_address': pc - size})
                        uc.emu_stop()
                        return
                    event = {'syscall': 'ioctl', 'r7': 54, 'fd': fd, 'cmd': cmd, 'arg': arg, 'returned': ret,
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb, 'device': 'usb_otgcore'}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'hdmi':
                    owner_id = self.filesystem.fds[fd].get('owner_id')
                    try:
                        ret = self.hdmi.ioctl(
                            owner_id, cmd, arg,
                            lambda addr, sz: bytes(uc.mem_read(addr, sz)),
                            lambda addr, data: uc.mem_write(addr, data)
                        )
                    except UnsupportedHdmi as error:
                        self.report.update(status='unsupported_hdmi_contract', boundary={
                            **error.details, 'fd': fd, 'cmd': cmd, 'arg': arg,
                            'pc': pc, 'r7': number, 'instruction_address': pc - size})
                        uc.emu_stop()
                        return
                    event = {'syscall': 'ioctl', 'r7': 54, 'fd': fd, 'cmd': cmd, 'arg': arg, 'returned': ret,
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb, 'device': 'hdmi'}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'cec':
                    owner_id = self.filesystem.fds[fd].get('owner_id')
                    try:
                        ret = self.cec.ioctl(
                            owner_id, cmd, arg,
                            lambda addr, sz: bytes(uc.mem_read(addr, sz)),
                            lambda addr, data: uc.mem_write(addr, data)
                        )
                    except UnsupportedCec as error:
                        self.report.update(status='unsupported_cec_contract', boundary={
                            **error.details, 'fd': fd, 'cmd': cmd, 'arg': arg,
                            'pc': pc, 'r7': number, 'instruction_address': pc - size})
                        uc.emu_stop()
                        return
                    event = {'syscall': 'ioctl', 'r7': 54, 'fd': fd, 'cmd': cmd, 'arg': arg, 'returned': ret,
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb, 'device': 'cec'}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'mmca_char':
                    owner_id = self.filesystem.fds[fd].get('owner_id')
                    try:
                        ret = self.mmca_char.ioctl(
                            owner_id, cmd, arg,
                            lambda addr, sz: bytes(uc.mem_read(addr, sz)),
                            lambda addr, data: uc.mem_write(addr, data)
                        )
                    except UnsupportedMmcChar as error:
                        self.report.update(status='unsupported_mmca_char_contract', boundary={
                            **error.details, 'fd': fd, 'cmd': cmd, 'arg': arg,
                            'pc': pc, 'r7': number, 'instruction_address': pc - size})
                        uc.emu_stop()
                        return
                    event = {'syscall': 'ioctl', 'r7': 54, 'fd': fd, 'cmd': cmd, 'arg': arg, 'returned': ret,
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb, 'device': 'mmca_char'}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'nflasha4':
                    policy = getattr(self, 'nflasha4_device_policy', 'stop')
                    dump = getattr(self, 'nflasha4_dump', None)
                    if policy == 'observed-dump' and isinstance(dump, Nflasha4Dump):
                        try:
                            erased = dump.ioctl_erased_state(cmd)
                        except Nflasha4DumpError as error:
                            self.report.update(status='unsupported_nflasha4_contract', boundary={
                                'reason': str(error), 'cmd': cmd, 'arg': arg,
                                'fd': fd, 'path': '/dev/nflasha4', 'pc': pc, 'r7': number,
                                'instruction_address': pc - size})
                            uc.emu_stop()
                            return
                        try:
                            uc.mem_write(arg, bytes([erased]))
                            ret = 0  # __put_user_1 success
                        except unicorn.UcError:
                            ret = -14  # -EFAULT from __put_user_1; no output written.
                        self.report['serviced_syscalls'].append({
                            'syscall': 'ioctl', 'fd': fd, 'cmd': cmd, 'arg': arg,
                            'returned': ret, 'device': 'nflasha4',
                            'path': '/dev/nflasha4', 'policy': 'observed-dump',
                            'erased_state_byte': erased if ret == 0 else None,
                            'pc': pc, 'instruction_address': pc - size, 'thumb': thumb})
                        self.report['syscall_responses_supplied'] += 1
                        uc.reg_write(arm.UC_ARM_REG_R0, ret)
                        return
                    try:
                        observation = bytes(uc.mem_read(arg, 4)).hex()
                    except unicorn.UcError:
                        observation = None
                    self.report.update(status='unsupported_nflasha4_contract', boundary={
                        'reason': 'nflasha4_ioctl_not_supplied', 'cmd': cmd, 'arg': arg,
                        'fd': fd, 'path': '/dev/nflasha4', 'pc': pc, 'r7': number,
                        'instruction_address': pc - size,
                        'buffer_hex': observation,
                        'lr': uc.reg_read(arm.UC_ARM_REG_LR),
                        'sp': uc.reg_read(arm.UC_ARM_REG_SP),
                        'guest_tid': self.threads.current_tid if hasattr(self, 'threads') else None})
                    uc.emu_stop()
                    return
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'stream2':
                    self._stream_boundary(UnsupportedStream(
                        'stream2_ioctl_not_supplied', cmd=cmd, arg=arg,
                        device='/dev/stream2'), pc, number)
                    return
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'stream':
                    try:
                        ret = self.stream.ioctl(cmd, arg)
                    except UnsupportedStream as error:
                        self._stream_boundary(error, pc, number)
                        return
                    event = {'syscall': 'ioctl', 'r7': 54, 'fd': fd, 'cmd': cmd, 'arg': arg,
                             'returned': ret, 'device': 'stream', 'pc': pc,
                             'instruction_address': pc - size, 'thumb': thumb}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'uipc':
                    try:
                        queue = (struct.unpack('<I', self._uipc_read(arg, 4))[0]
                                 if cmd in (0x80000007, 0x80000004) else None)
                        ret = self.uipc.handle_ioctl(self._uipc_read, self._uipc_write, cmd, arg,
                                                     tid=self.threads.current_tid if hasattr(self, 'threads') else None)
                    except UnverifiedGuestData as error:
                        self._identity_boundary(error.details)
                        return
                    except UnsupportedUipc as error:
                        self.report.update(status='unsupported_uipc_contract', boundary={
                            **error.details, 'pc': pc, 'r7': number, 'cmd': cmd, 'arg': arg})
                        uc.emu_stop()
                        return
                    if ret is None and cmd in (0x80000007, 0x8000000d) and self.syscall_policy == 'threads' and (cmd == 0x80000007 or self.uipc.kernel_pool_options):
                        if cmd == 0x8000000d:
                            queue = -1  # Internal scheduler key for callback waiters.
                        else:
                            self.report['uipc_rcv_timeout_policy'] = 'block_until_message_no_virtual_deadline'
                        self.threads.save_context(uc)
                        self.threads.threads[self.threads.current_tid].regs[arm.UC_ARM_REG_PC] = pc - size
                        next_tid, event = self.threads.handle_uipc_wait(queue, pc - size)
                        event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
                        if cmd == 0x8000000d:
                            event['cmd'] = 'UIPC_CMD_WAIT_CB'
                        self.report['serviced_syscalls'].append(event)
                        if next_tid is not None:
                            self.threads.restore_context(uc, next_tid, getattr(self, 'kuser', None))
                        else:
                            self.report.update(status='blocked_uipc', boundary=event)
                            uc.reg_write(arm.UC_ARM_REG_PC, (pc - size) | int(thumb))
                            uc.emu_stop()
                        return
                    if ret is not None:
                        event = {'syscall': 'ioctl', 'r7': 54, 'fd': fd, 'cmd': cmd, 'arg': arg, 'returned': ret,
                                 'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                        if (getattr(self, 'thread_poll_yield', False) and ret == -1022
                                and cmd in (0x80000007, 0x8000000d) and hasattr(self, 'threads')
                                and self.threads.current_tid in self.threads.threads):
                            # Cooperative yield at a syscall boundary when a
                            # non-blocking UIPC poll returns "no message": this
                            # lets runnable peers run without arbitrary timer
                            # preemption (E0473-safe point, avoids mid-atomic
                            # switches under ldrex/strex lock sequences).
                            uc.reg_write(arm.UC_ARM_REG_R0, ret)
                            self.threads.save_context(uc)
                            current = self.threads.threads[self.threads.current_tid]
                            current.state = 'runnable'
                            next_tid = self.threads.get_next_runnable_tid()
                            if next_tid is not None:
                                self.report['poll_yields'] = self.report.get('poll_yields', 0) + 1
                                event['poll_yield_to'] = next_tid
                                self.threads.restore_context(
                                    uc, next_tid, getattr(self, 'kuser', None))
                            else:
                                current.state = 'running'
                            self.report['serviced_syscalls'].append(event)
                            self.report['syscall_responses_supplied'] += 1
                            return
                        if self.syscall_policy == 'threads' and ret == 0:
                            woken = []
                            if cmd == 0x80000004:
                                woken.extend(self.threads.handle_uipc_wake(queue))
                                if self.uipc.kernel_pool_options and self.uipc.callback_ready():
                                    woken.extend(self.threads.handle_uipc_wake(-1))
                            elif (cmd == 0x80000008 and getattr(self.uipc, 'pool_options_policy', '') == 'kernel-e0301'
                                  and self.uipc.callback_ready()):
                                woken.extend(self.threads.handle_uipc_wake(-1))
                            # A service may enqueue a completion on a different
                            # reply queue during this ioctl. Wake its receivers
                            # only when an actual message is available.
                            for reply_queue in list(self.threads.uipc_waiters):
                                if self.uipc.message_queues.get(reply_queue):
                                    woken.extend(self.threads.handle_uipc_wake(reply_queue))
                            if woken or cmd == 0x80000004:
                                event['woken_tids'] = woken
                        self.report['serviced_syscalls'].append(event)
                        self.report['syscall_responses_supplied'] += 1
                        uc.reg_write(arm.UC_ARM_REG_R0, ret)
                        return
                elif fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'fb0':
                    ret = self.fb.handle_ioctl(
                        lambda addr, sz: bytes(uc.mem_read(addr, sz)),
                        lambda addr, data: uc.mem_write(addr, data),
                        cmd, arg
                    )
                    if ret is not None:
                        event = {'syscall': 'ioctl', 'r7': 54, 'fd': fd, 'cmd': cmd, 'arg': arg, 'returned': ret,
                                 'pc': pc, 'instruction_address': pc - size, 'thumb': thumb, 'device': 'fb0'}
                        self.report['serviced_syscalls'].append(event)
                        self.report['syscall_responses_supplied'] += 1
                        uc.reg_write(arm.UC_ARM_REG_R0, ret)
                        return
                elif self.stdio.is_stdio_fd(fd):
                    ret = self.stdio.handle_ioctl(fd, cmd, arg)
                    if ret is not None:
                        event = {'syscall': 'ioctl', 'r7': 54, 'fd': fd, 'cmd': cmd, 'arg': arg, 'returned': ret,
                                 'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                        self.report['serviced_syscalls'].append(event)
                        self.report['syscall_responses_supplied'] += 1
                        uc.reg_write(arm.UC_ARM_REG_R0, ret)
                        return
            if number == 221:  # fcntl64
                fd = uc.reg_read(arm.UC_ARM_REG_R0)
                cmd = uc.reg_read(arm.UC_ARM_REG_R1)
                arg = uc.reg_read(arm.UC_ARM_REG_R2)
                if cmd == 2:  # F_SETFD
                    if fd in self.filesystem.fds:
                        self.filesystem.fds[fd]['descriptor_flags'] = arg
                    ret = 0
                elif cmd == 1:  # F_GETFD
                    ret = self.filesystem.fds.get(fd, {}).get('descriptor_flags', 0)
                else:
                    ret = 0xffffffea  # -EINVAL
                event = {'syscall': 'fcntl64', 'r7': 221, 'fd': fd, 'cmd': cmd, 'arg': arg, 'returned': ret,
                         'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                uc.reg_write(arm.UC_ARM_REG_R0, ret)
                return
            if number == 192:  # mmap2 on /dev/uipc or /dev/fb0
                fd = uc.reg_read(arm.UC_ARM_REG_R4)
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'nflasha4':
                    self.report.update(status='unsupported_nflasha4_contract', boundary={
                        'reason': 'nflasha4_mmap_not_supplied', 'fd': fd,
                        'path': '/dev/nflasha4', 'pc': pc, 'r7': number,
                        'instruction_address': pc - size,
                        'arguments': [uc.reg_read(r) for r in (
                            arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2,
                            arm.UC_ARM_REG_R3, arm.UC_ARM_REG_R4, arm.UC_ARM_REG_R5)]})
                    uc.emu_stop()
                    return
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'stream2':
                    self._stream_boundary(UnsupportedStream(
                        'stream2_mmap_not_supplied', device='/dev/stream2'), pc, number)
                    return
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'stream':
                    args = [uc.reg_read(r) for r in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1,
                            arm.UC_ARM_REG_R2, arm.UC_ARM_REG_R3, arm.UC_ARM_REG_R4, arm.UC_ARM_REG_R5)]
                    try:
                        event = self.stream.mmap2(*args)
                    except UnsupportedStream as error:
                        self._stream_boundary(error, pc, number)
                        return
                    except UnsupportedMmap as error:
                        self.report.update(status='unsupported_mmap', boundary={**error.details, 'pc': pc, 'r7': number})
                        uc.emu_stop()
                        return
                    event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, event['returned'])
                    if (self.display is not None and 0 <= event['returned'] < 0x80000000
                            and self.stream.mapping):
                        self.display.register_mapping(
                            self.stream.mapping['virtual_start'],
                            self.stream.mapping['length'],
                            self.stream.mapping['physical_start'], 'stream')
                        self._install_display_write_hooks()
                    return
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'uipc':
                    addr = uc.reg_read(arm.UC_ARM_REG_R0)
                    length = uc.reg_read(arm.UC_ARM_REG_R1)
                    prot = uc.reg_read(arm.UC_ARM_REG_R2)
                    flags = uc.reg_read(arm.UC_ARM_REG_R3)
                    event = self.mmap.request_mmap2(addr, length, prot, flags | 0x20, -1, 0)
                    event.update(pc=pc, instruction_address=pc - size, thumb=thumb, path='/dev/uipc')
                    if 0 <= event['returned'] < 0x80000000:
                        self.mmap.mark_device_range(event['returned'], length, 'uipc')
                    self.uipc.pool_base = event['returned']
                    if 0 <= event['returned'] < 0x80000000:
                        self.uipc.initialize_pool_options(self._uipc_write)
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, event['returned'])
                    return
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'fb0':
                    addr = uc.reg_read(arm.UC_ARM_REG_R0)
                    length = uc.reg_read(arm.UC_ARM_REG_R1)
                    prot = uc.reg_read(arm.UC_ARM_REG_R2)
                    flags = uc.reg_read(arm.UC_ARM_REG_R3)
                    event = self.mmap.request_mmap2(addr, length, prot, flags | 0x20, -1, 0)
                    event.update(pc=pc, instruction_address=pc - size, thumb=thumb, path='/dev/fb0')
                    if 0 <= event['returned'] < 0x80000000:
                        self.mmap.mark_device_range(event['returned'], length, 'fb0')
                    self.fb.vram_base = event['returned']
                    self.fb.vram_length = length
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, event['returned'])
                    return
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'mem':
                    addr = uc.reg_read(arm.UC_ARM_REG_R0)
                    length = uc.reg_read(arm.UC_ARM_REG_R1)
                    prot = uc.reg_read(arm.UC_ARM_REG_R2)
                    flags = uc.reg_read(arm.UC_ARM_REG_R3)
                    pgoff = uc.reg_read(arm.UC_ARM_REG_R5)
                    phys_addr = pgoff * 4096
                    event = self.mmap.request_mmap2(addr, length, prot, flags | 0x20, -1, 0)
                    event.update(pc=pc, instruction_address=pc - size, thumb=thumb, path='/dev/mem',
                                 phys_addr=phys_addr, pgoff=pgoff)
                    if 0 <= event['returned'] < 0x80000000:
                        self.mmap.mark_device_range(event['returned'], length, 'mem')
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, event['returned'])
                    return
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'dmpgles2':
                    addr = uc.reg_read(arm.UC_ARM_REG_R0)
                    length = uc.reg_read(arm.UC_ARM_REG_R1)
                    prot = uc.reg_read(arm.UC_ARM_REG_R2)
                    flags = uc.reg_read(arm.UC_ARM_REG_R3)
                    pgoff = uc.reg_read(arm.UC_ARM_REG_R5)
                    owner_id = self.filesystem.fds[fd].get('owner_id')
                    try:
                        event = self.gles.mmap2(self.mmap, addr, length, prot, flags, pgoff, owner_id)
                    except UnsupportedGles as error:
                        self.report.update(status='unsupported_gles_contract', boundary={
                            **error.details, 'fd': fd, 'pc': pc, 'r7': number,
                            'instruction_address': pc - size, 'length': length, 'pgoff': pgoff})
                        uc.emu_stop()
                        return
                    event.update(pc=pc, instruction_address=pc - size, thumb=thumb, path='/dev/dmpgles2')
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, event['returned'])
                    if (0 <= event['returned'] < 0x80000000
                            and getattr(self.gles, 'bar_virtual', None) == event['returned']):
                        # Seed the observed BAR identity word and, when requested,
                        # install observe-only access hooks for the resumed replay.
                        seed = bytes(self.gles.bar[:max(0, int(self.gles.bar_length))])
                        if seed:
                            uc.mem_write(event['returned'], seed)
                        if getattr(self, 'gles_bar_trace', False) and self.gles.bar_length > 0:
                            self.install_gles_bar_hooks(event['returned'], self.gles.bar_length)
                    return
        if svc and immediate == 0 and self.syscall_policy in ('mmap', 'kuser', 'uipc', 'threads'):
            if number == 125 and hasattr(self, 'stream') and self.stream.mapping:
                address = uc.reg_read(arm.UC_ARM_REG_R0)
                length = uc.reg_read(arm.UC_ARM_REG_R1)
                prot = uc.reg_read(arm.UC_ARM_REG_R2)
                mapping = self.stream.mapping
                if (prot & unicorn.UC_PROT_EXEC and address < mapping['virtual_start'] + mapping['length']
                        and mapping['virtual_start'] < address + length):
                    self._stream_boundary(UnsupportedStream('stream_executable_mapping_not_supported'), pc, number)
                    return
            if number == 220 and self.madvise_policy == 'private-anonymous-dontneed':
                args = [uc.reg_read(r) for r in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2)]
                try:
                    event = self.mmap.request_madvise(*args)
                except UnsupportedMmap as error:
                    self.report.update(status='unsupported_memory_contract',
                                       boundary={**error.details, 'pc': pc, 'r7': number, 'arguments': args})
                    uc.emu_stop()
                    return
                event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                uc.reg_write(arm.UC_ARM_REG_R0, event['returned'])
                return
            if number == 192:  # mmap2
                args = [uc.reg_read(r) for r in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2,
                                                 arm.UC_ARM_REG_R3, arm.UC_ARM_REG_R4, arm.UC_ARM_REG_R5)]
                try:
                    event = self.mmap.request_mmap2(*args)
                except UnsupportedMmap as error:
                    self.report.update(status='unsupported_mmap',
                                       boundary={**error.details, 'pc': pc, 'r7': number, 'arguments': args})
                    uc.emu_stop()
                    return
                self._arm_relocated_libc_repair(event)
                event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                uc.reg_write(arm.UC_ARM_REG_R0, event['returned'])
                return
            if number == 125:  # mprotect
                args = [uc.reg_read(r) for r in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2)]
                try:
                    event = self.mmap.request_mprotect(*args)
                except UnsupportedMmap as error:
                    self.report.update(status='unsupported_mmap',
                                       boundary={**error.details, 'pc': pc, 'r7': number, 'arguments': args})
                    uc.emu_stop()
                    return
                event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                uc.reg_write(arm.UC_ARM_REG_R0, event['returned'])
                return
            if number == 91:  # munmap
                args = [uc.reg_read(r) for r in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1)]
                try:
                    event = self.mmap.request_munmap(*args)
                except UnsupportedMmap as error:
                    self.report.update(status='unsupported_mmap',
                                       boundary={**error.details, 'pc': pc, 'r7': number, 'arguments': args})
                    uc.emu_stop()
                    return
                event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                uc.reg_write(arm.UC_ARM_REG_R0, event['returned'])
                return
        if svc and immediate == 0 and self.syscall_policy in ('files', 'metadata', 'mmap', 'kuser', 'uipc', 'threads') and number in ((3, 5, 6, 19, 33, 39, 195, 197, 217) if self.syscall_policy in ('metadata', 'mmap', 'kuser', 'uipc', 'threads') else (3, 5, 6, 19, 33, 39, 195, 217)):
            args = [uc.reg_read(r) for r in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2)]
            try:
                event = self.filesystem.request(number, args)
            except UnverifiedIdentityData as error:
                self._identity_boundary(error.details)
                return
            except UnsupportedFilesystem as error:
                self.report.update(status='unsupported_filesystem',
                                   boundary={**error.details, 'pc': pc, 'r7': number, 'arguments': args})
                uc.emu_stop()
                return
            event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
            self.report['serviced_syscalls'].append(event)
            self.report['syscall_responses_supplied'] += 1
            uc.reg_write(arm.UC_ARM_REG_R0, event['returned'])
            return
        if svc and immediate == 0 and self.syscall_policy in ('kuser', 'uipc', 'threads'):
            if number == 256:  # set_tid_address
                tidptr = uc.reg_read(arm.UC_ARM_REG_R0)
                pid = self.threads.current_tid if hasattr(self, 'threads') else 1000
                uc.reg_write(arm.UC_ARM_REG_R0, pid)
                event = {'syscall': 'set_tid_address', 'r7': 256, 'tidptr': tidptr, 'returned': pid,
                         'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                return
            if number == 338:  # set_robust_list
                head = uc.reg_read(arm.UC_ARM_REG_R0)
                len_ = uc.reg_read(arm.UC_ARM_REG_R1)
                ret = 0 if len_ == 12 else 0xffffffea
                uc.reg_write(arm.UC_ARM_REG_R0, ret)
                event = {'syscall': 'set_robust_list', 'r7': 338, 'head': head, 'len': len_, 'returned': ret,
                         'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                return
            if number == 174:  # rt_sigaction
                signum = uc.reg_read(arm.UC_ARM_REG_R0)
                act = uc.reg_read(arm.UC_ARM_REG_R1)
                oldact = uc.reg_read(arm.UC_ARM_REG_R2)
                sigsetsize = uc.reg_read(arm.UC_ARM_REG_R3)
                ret = 0 if sigsetsize == 8 else 0xffffffea
                old_info = self.signal_handlers.get(signum)
                if oldact != 0 and sigsetsize == 8:
                    if old_info:
                        raw_old = struct.pack('<III', old_info['handler'], old_info['flags'],
                                              old_info['restorer']) + old_info['mask']
                    else:
                        raw_old = b'\x00' * 20
                    uc.mem_write(oldact, raw_old[:20])
                if act != 0 and sigsetsize == 8:
                    raw_act = bytes(uc.mem_read(act, 20))
                    handler, flags, restorer = struct.unpack('<III', raw_act[:12])
                    mask = raw_act[12:20]
                    self.signal_handlers[signum] = {
                        'handler': handler, 'flags': flags, 'restorer': restorer, 'mask': mask
                    }
                uc.reg_write(arm.UC_ARM_REG_R0, ret)
                event = {'syscall': 'rt_sigaction', 'r7': 174, 'signum': signum, 'act': act, 'oldact': oldact,
                         'sigsetsize': sigsetsize, 'returned': ret,
                         'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                if act != 0 and signum in self.signal_handlers:
                    event['registered_handler'] = self.signal_handlers[signum]['handler']
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                return
            if number == 175:  # rt_sigprocmask
                how = uc.reg_read(arm.UC_ARM_REG_R0)
                set_ = uc.reg_read(arm.UC_ARM_REG_R1)
                oldset = uc.reg_read(arm.UC_ARM_REG_R2)
                sigsetsize = uc.reg_read(arm.UC_ARM_REG_R3)
                ret = 0 if sigsetsize == 8 else 0xffffffea
                uc.reg_write(arm.UC_ARM_REG_R0, ret)
                event = {'syscall': 'rt_sigprocmask', 'r7': 175, 'how': how, 'set': set_, 'oldset': oldset,
                         'sigsetsize': sigsetsize, 'returned': ret,
                         'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                return
            if number == 191:  # ugetrlimit
                resource = uc.reg_read(arm.UC_ARM_REG_R0)
                rlim_addr = uc.reg_read(arm.UC_ARM_REG_R1)
                if resource == 3:  # RLIMIT_STACK
                    stack_limit = 8 * 1024 * 1024
                    uc.mem_write(rlim_addr, struct.pack('<II', stack_limit, 0xffffffff))
                    ret = 0
                else:
                    ret = 0xffffffea  # -EINVAL
                uc.reg_write(arm.UC_ARM_REG_R0, ret)
                event = {'syscall': 'ugetrlimit', 'r7': 191, 'resource': resource, 'rlim_addr': rlim_addr,
                         'returned': ret, 'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                return
        if svc and immediate == 0 and self.syscall_policy == 'threads':
            if number == 120:  # sys_clone
                flags = uc.reg_read(arm.UC_ARM_REG_R0)
                child_stack = uc.reg_read(arm.UC_ARM_REG_R1)
                parent_tidptr = uc.reg_read(arm.UC_ARM_REG_R2)
                tls_val = uc.reg_read(arm.UC_ARM_REG_R3)
                child_tidptr = uc.reg_read(arm.UC_ARM_REG_R4)
                if flags != EXPECTED_PTHREAD_CLONE_FLAGS or not accessible(uc, parent_tidptr, 4, unicorn.UC_PROT_WRITE):
                    self.report.update(status='unsupported_thread_contract', boundary={
                        'reason': 'clone_flags_or_parent_tid_write_unsupported', 'pc': pc,
                        'flags': flags, 'parent_tidptr': parent_tidptr})
                    uc.emu_stop()
                    return
                tid, event = self.threads.handle_clone(
                    flags, child_stack, parent_tidptr, tls_val, child_tidptr,
                    uc.mem_read, uc.mem_write,
                    syscall_registers={register: uc.reg_read(register) for register in REGISTER_LIST}
                )
                self._after_host_write(parent_tidptr, 4)
                uc.reg_write(arm.UC_ARM_REG_R0, tid)
                event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                return
            if number == 224:  # sys_gettid
                tid, event = self.threads.handle_gettid()
                uc.reg_write(arm.UC_ARM_REG_R0, tid)
                event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                return
            if number == 172:  # sys_prctl
                option = uc.reg_read(arm.UC_ARM_REG_R0)
                arg2 = uc.reg_read(arm.UC_ARM_REG_R1)
                ret, event = self.threads.handle_prctl(option, arg2, uc.mem_read)
                uc.reg_write(arm.UC_ARM_REG_R0, ret)
                event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                return
            if number in (159, 160) and self.uipc.kernel_pool_options:
                # E0300: original kernel functions and tables at 0x603c9a44/5c.
                policy = uc.reg_read(arm.UC_ARM_REG_R0)
                values = (0, 159, 159, 0, -22, 0) if number == 159 else (0, 1, 1, 0, -22, 0)
                ret = values[policy] if policy < len(values) else -22
                self.report['serviced_syscalls'].append({
                    'syscall': 'sched_get_priority_max' if number == 159 else 'sched_get_priority_min',
                    'r7': number, 'policy': policy, 'returned': ret,
                    'pc': pc, 'instruction_address': pc - size, 'thumb': thumb,
                    'source': 'original-kernel-e0300'})
                self.report['syscall_responses_supplied'] += 1
                uc.reg_write(arm.UC_ARM_REG_R0, ret & 0xffffffff)
                return
            if number == 155:  # sched_getparam
                pid = uc.reg_read(arm.UC_ARM_REG_R0)
                param = uc.reg_read(arm.UC_ARM_REG_R1)
                ret, event = self.threads.handle_sched_getparam(pid, param, uc.mem_write)
                uc.reg_write(arm.UC_ARM_REG_R0, ret)
                event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                return
            if number == 156:  # sched_setscheduler
                pid = uc.reg_read(arm.UC_ARM_REG_R0)
                policy = uc.reg_read(arm.UC_ARM_REG_R1)
                param = uc.reg_read(arm.UC_ARM_REG_R2)
                ret, event = self.threads.handle_sched_setscheduler(pid, policy, param)
                uc.reg_write(arm.UC_ARM_REG_R0, ret)
                event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                return
            if number == 157:  # sched_getscheduler
                pid = uc.reg_read(arm.UC_ARM_REG_R0)
                ret, event = self.threads.handle_sched_getscheduler(pid)
                uc.reg_write(arm.UC_ARM_REG_R0, ret)
                event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                return
            if number == 158:  # sched_yield
                ret = 0
                uc.reg_write(arm.UC_ARM_REG_R0, ret)
                if self.syscall_policy == 'threads' and hasattr(self, 'threads'):
                    next_tid, event = self.threads.handle_sched_yield()
                    event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    if next_tid is not None:
                        self.threads.save_context(uc)
                        self.threads.restore_context(uc, next_tid, getattr(self, 'kuser', None))
                    return
                else:
                    event = {'syscall': 'sched_yield', 'r7': 158, 'returned': ret,
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    return
            if number == 241:  # sched_setaffinity
                pid = uc.reg_read(arm.UC_ARM_REG_R0)
                len_ = uc.reg_read(arm.UC_ARM_REG_R1)
                mask = uc.reg_read(arm.UC_ARM_REG_R2)
                ret, event = self.threads.handle_sched_setaffinity(pid, len_, mask)
                uc.reg_write(arm.UC_ARM_REG_R0, ret)
                event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                return
            if number == 242:  # sched_getaffinity
                pid = uc.reg_read(arm.UC_ARM_REG_R0)
                len_ = uc.reg_read(arm.UC_ARM_REG_R1)
                mask_ptr = uc.reg_read(arm.UC_ARM_REG_R2)
                if len_ >= 4 and mask_ptr:
                    uc.mem_write(mask_ptr, (1).to_bytes(4, 'little'))
                uc.reg_write(arm.UC_ARM_REG_R0, 0)
                event = {'syscall': 'sched_getaffinity', 'r7': 242, 'pid': pid,
                         'len': len_, 'mask': 1, 'returned': 0,
                         'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                return
            if number == 240:  # sys_futex
                uaddr = uc.reg_read(arm.UC_ARM_REG_R0)
                op = uc.reg_read(arm.UC_ARM_REG_R1)
                val = uc.reg_read(arm.UC_ARM_REG_R2)
                cmd = op & 0x7f
                if cmd == 0:  # FUTEX_WAIT
                    ret, next_tid, event = self.threads.handle_futex_wait(uaddr, val, uc.mem_read)
                    event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    if ret is not None:
                        uc.reg_write(arm.UC_ARM_REG_R0, ret)
                        return
                    if next_tid is not None:
                        self.threads.save_context(uc)
                        self.threads.restore_context(uc, next_tid, getattr(self, 'kuser', None))
                        return
                elif cmd == 1:  # FUTEX_WAKE
                    woken, event = self.threads.handle_futex_wake(uaddr, val)
                    uc.reg_write(arm.UC_ARM_REG_R0, woken)
                    event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    return
                elif cmd == 5:  # FUTEX_WAKE_OP
                    val2 = uc.reg_read(arm.UC_ARM_REG_R3)
                    uaddr2 = uc.reg_read(arm.UC_ARM_REG_R4)
                    val3 = uc.reg_read(arm.UC_ARM_REG_R5)
                    woken, event = self.threads.handle_futex_wake_op(
                        uaddr, val, val2, uaddr2, val3, uc.mem_read, uc.mem_write
                    )
                    uc.reg_write(arm.UC_ARM_REG_R0, woken)
                    event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    return
            if number == 1 and self.threads.current_tid != 1000:  # sys_exit from worker thread
                status = uc.reg_read(arm.UC_ARM_REG_R0)
                next_tid, event = self.threads.handle_exit(status, uc.mem_write)
                event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                if next_tid is not None:
                    self.threads.restore_context(uc, next_tid, getattr(self, 'kuser', None))
                    return
            if number == 128:  # sys_init_module
                umod = uc.reg_read(arm.UC_ARM_REG_R0)
                length = uc.reg_read(arm.UC_ARM_REG_R1)
                uargs = uc.reg_read(arm.UC_ARM_REG_R2)
                if self.kmod_service_policy == 'verified-image':
                    if 0 < length <= 64 * 1024 * 1024 and accessible(uc, umod, length, unicorn.UC_PROT_READ):
                        try:
                            self._before_host_read(umod, length)
                        except UnverifiedGuestData as error:
                            self._identity_boundary(error.details)
                            return
                        data = bytes(uc.mem_read(umod, length))
                        payload_hash = hashlib.sha256(data).hexdigest()
                        matching = [p for p, c in self.filesystem.cache.items()
                                    if len(c) == length and hashlib.sha256(c).hexdigest() == payload_hash]
                        if not matching:
                            self.report.update(status='unsupported_kmod_contract', boundary={
                                'reason': 'unverified_kmod_payload',
                                'address': umod, 'length': length, 'sha256': payload_hash,
                                'pc': pc, 'r7': 128
                            })
                            uc.emu_stop()
                            return
                        matched_path = matching[0]
                        ret = 0
                        uc.reg_write(arm.UC_ARM_REG_R0, ret)
                        event = {'syscall': 'init_module', 'r7': 128, 'path': matched_path,
                                 'length': length, 'returned': ret, 'sha256': payload_hash,
                                 'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                        self.report['serviced_syscalls'].append(event)
                        self.report['syscall_responses_supplied'] += 1
                        self.report.setdefault('loaded_modules', []).append(matched_path)
                        return
                    else:
                        self.report.update(status='unsupported_kmod_contract', boundary={
                            'reason': 'invalid_kmod_memory_range',
                            'address': umod, 'length': length, 'pc': pc, 'r7': 128
                        })
                        uc.emu_stop()
                        return
            if number == 6:  # sys_close
                fd = uc.reg_read(arm.UC_ARM_REG_R0)
                if fd in self.filesystem.fds:
                    entry = self.filesystem.fds.pop(fd)
                    if entry.get('device') == 'gpio' and hasattr(self, 'gpio') and self.gpio:
                        self.gpio.close(entry.get('owner_id'))
                    if entry.get('device') == 'kikilog' and getattr(self, 'kikilog', None) is not None:
                        self.kikilog.close(entry.get('owner_id'))
                    if entry.get('device') == 'usb_buspower' and hasattr(self, 'usb_buspower') and self.usb_buspower:
                        self.usb_buspower.close(entry.get('owner_id'))
                    if entry.get('device') == 'usb_event' and hasattr(self, 'usb_event') and self.usb_event:
                        self.usb_event.close(entry.get('owner_id'))
                    if entry.get('device') == 'usb_otgcore' and hasattr(self, 'usb_otgcore') and self.usb_otgcore:
                        self.usb_otgcore.close(entry.get('owner_id'))
                    if entry.get('device') == 'hdmi' and hasattr(self, 'hdmi') and self.hdmi:
                        self.hdmi.close(entry.get('owner_id'))
                    if entry.get('device') == 'cec' and hasattr(self, 'cec') and self.cec:
                        self.cec.close(entry.get('owner_id'))
                    if entry.get('device') == 'mmca_char' and hasattr(self, 'mmca_char') and self.mmca_char:
                        self.mmca_char.close(entry.get('owner_id'))
                    if entry.get('device') == 'pipe' and hasattr(self, 'pipes') and self.pipes:
                        self.pipes.close_end(entry.get('pipe_id'), entry.get('end'))
                        peer_fd = entry.get('peer_fd')
                        if peer_fd is not None and hasattr(self, 'threads'):
                            self.threads.handle_fd_wake(peer_fd)
                    ret = 0
                else:
                    ret = 0xfffffff7  # -EBADF
                uc.reg_write(arm.UC_ARM_REG_R0, ret)
                event = {'syscall': 'close', 'r7': 6, 'fd': fd, 'returned': ret,
                         'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                return
            if number == 42:  # sys_pipe
                pipefd_ptr = uc.reg_read(arm.UC_ARM_REG_R0)
                if not accessible(uc, pipefd_ptr, 8, unicorn.UC_PROT_WRITE):
                    self.report.update(status='unsupported_pipe_contract', boundary={
                        'reason': 'pipefd_pointer_not_writable', 'address': pipefd_ptr,
                        'pc': pc, 'r7': 42, 'instruction_address': pc - size})
                    uc.emu_stop()
                    return
                avail = [cand for cand in range(3, 259) if cand not in self.filesystem.fds]
                if len(avail) < 2:
                    ret = 0xffffffe8  # -EMFILE
                    event = {'syscall': 'pipe', 'r7': 42, 'returned': ret,
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                else:
                    read_fd, write_fd = avail[0], avail[1]
                    caller_pid = self.threads.current_tid if hasattr(self, 'threads') else None
                    caller_tgid = self.threads.process_id if hasattr(self, 'threads') else None
                    channel = self.pipes.create(flags=0, pid=caller_pid, tgid=caller_tgid)
                    pipe_id = channel['pipe_id']
                    self.filesystem.fds[read_fd] = {
                        'path': f'pipe:[{pipe_id}]', 'device': 'pipe', 'pipe_id': pipe_id,
                        'end': 'read', 'peer_fd': write_fd, 'flags': 0
                    }
                    self.filesystem.fds[write_fd] = {
                        'path': f'pipe:[{pipe_id}]', 'device': 'pipe', 'pipe_id': pipe_id,
                        'end': 'write', 'peer_fd': read_fd, 'flags': 1
                    }
                    self._uipc_write(pipefd_ptr, struct.pack('<II', read_fd, write_fd))
                    ret = 0
                    event = {'syscall': 'pipe', 'r7': 42, 'pipe_id': pipe_id,
                             'read_fd': read_fd, 'write_fd': write_fd, 'returned': ret,
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                uc.reg_write(arm.UC_ARM_REG_R0, ret)
                return
            if number == 168:  # sys_poll
                fds_ptr = uc.reg_read(arm.UC_ARM_REG_R0)
                nfds = uc.reg_read(arm.UC_ARM_REG_R1)
                timeout_raw = uc.reg_read(arm.UC_ARM_REG_R2)
                timeout = struct.unpack('<i', struct.pack('<I', timeout_raw))[0]
                if nfds > 256 or (nfds > 0 and not accessible(uc, fds_ptr, nfds * 8, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)):
                    self.report.update(status='unsupported_poll_contract', boundary={
                        'reason': 'pollfd_array_not_accessible', 'fds_ptr': fds_ptr, 'nfds': nfds,
                        'pc': pc, 'r7': 168, 'instruction_address': pc - size})
                    uc.emu_stop()
                    return
                try:
                    raw_pollfds = self._uipc_read(fds_ptr, nfds * 8) if nfds > 0 else b''
                except (UnsupportedUipc, UnverifiedGuestData) as error:
                    self.report.update(status='unsupported_poll_contract', boundary={
                        **(error.details if hasattr(error, 'details') else {'error': str(error)}),
                        'pc': pc, 'r7': 168, 'instruction_address': pc - size})
                    uc.emu_stop()
                    return
                out_pollfds = bytearray(raw_pollfds)
                ready_count = 0
                valid_fds = []
                for idx in range(nfds):
                    p_fd, p_events, _ = struct.unpack_from('<ihh', raw_pollfds, idx * 8)
                    if p_fd < 0:
                        revents = 0
                    elif p_fd not in self.filesystem.fds:
                        revents = POLLNVAL
                    else:
                        valid_fds.append(p_fd)
                        entry = self.filesystem.fds[p_fd]
                        dev_type = entry.get('device')
                        if dev_type == 'hdmi' and hasattr(self, 'hdmi') and self.hdmi:
                            mask = self.hdmi.poll(entry.get('owner_id'))
                            revents = (p_events & mask) | (mask & (POLLERR | POLLHUP | POLLNVAL))
                        elif dev_type == 'cec' and hasattr(self, 'cec') and self.cec:
                            mask = self.cec.poll(entry.get('owner_id'))
                            revents = (p_events & mask) | (mask & (POLLERR | POLLHUP | POLLNVAL))
                        elif dev_type == 'pipe' and hasattr(self, 'pipes') and self.pipes:
                            mask = self.pipes.poll(entry.get('pipe_id'), entry.get('end'))
                            revents = (p_events & mask) | (mask & (POLLERR | POLLHUP | POLLNVAL))
                        elif dev_type == 'usb_event' and hasattr(self, 'usb_event') and self.usb_event:
                            mask = 0x0041 if self.usb_event.event_queue else 0
                            revents = p_events & mask
                        else:
                            revents = p_events & 0x0005
                    struct.pack_into('<h', out_pollfds, idx * 8 + 6, revents)
                    if revents != 0:
                        ready_count += 1
                if nfds > 0:
                    self._uipc_write(fds_ptr, bytes(out_pollfds))
                if ready_count > 0 or timeout == 0:
                    ret = ready_count
                    event = {'syscall': 'poll', 'r7': 168, 'nfds': nfds, 'fds': valid_fds,
                             'timeout': timeout, 'returned': ret,
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                    self.report['serviced_syscalls'].append(event)
                    self.report['syscall_responses_supplied'] += 1
                    uc.reg_write(arm.UC_ARM_REG_R0, ret)
                    return
                if self.syscall_policy == 'threads' and valid_fds:
                    self.threads.save_context(uc)
                    self.threads.threads[self.threads.current_tid].regs[arm.UC_ARM_REG_PC] = pc - size
                    next_tid, event = self.threads.handle_fd_wait(valid_fds[0], 'poll', pc - size, extra_fds=valid_fds[1:])
                    event.update(pc=pc, instruction_address=pc - size, thumb=thumb, nfds=nfds, timeout=timeout)
                    self.report['serviced_syscalls'].append(event)
                    if next_tid is not None:
                        self.threads.restore_context(uc, next_tid, getattr(self, 'kuser', None))
                    else:
                        self.report.update(status='blocked_poll', boundary=event)
                        uc.emu_stop()
                    return
                self.report.update(status='blocked_poll', boundary={'fds': valid_fds, 'timeout': timeout, 'pc': pc, 'r7': 168})
                uc.emu_stop()
                return
            if number == 298:  # sys_semop
                semid = uc.reg_read(arm.UC_ARM_REG_R0)
                tsops = uc.reg_read(arm.UC_ARM_REG_R1)
                nsops = uc.reg_read(arm.UC_ARM_REG_R2)
                ret = self.sem.semop(semid, tsops, nsops,
                                     memory_reader=lambda a, sz: bytes(uc.mem_read(a, sz)),
                                     memory_writer=lambda a, d: uc.mem_write(a, d))
                uc.reg_write(arm.UC_ARM_REG_R0, ret & 0xffffffff if ret < 0 else ret)
                event = {'syscall': 'semop', 'r7': 298, 'semid': semid, 'tsops': hex(tsops),
                         'nsops': nsops, 'returned': ret,
                         'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                return
            if number == 299:  # sys_semget
                key = uc.reg_read(arm.UC_ARM_REG_R0)
                nsems = uc.reg_read(arm.UC_ARM_REG_R1)
                semflg = uc.reg_read(arm.UC_ARM_REG_R2)
                semid = self.sem.semget(key, nsems, semflg)
                uc.reg_write(arm.UC_ARM_REG_R0, semid & 0xffffffff if semid < 0 else semid)
                event = {'syscall': 'semget', 'r7': 299, 'key': hex(key), 'nsems': nsems,
                         'semflg': oct(semflg), 'returned': semid,
                         'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                return
            if number == 300:  # sys_semctl
                semid = uc.reg_read(arm.UC_ARM_REG_R0)
                semnum = uc.reg_read(arm.UC_ARM_REG_R1)
                cmd = uc.reg_read(arm.UC_ARM_REG_R2)
                arg = uc.reg_read(arm.UC_ARM_REG_R3)
                ret = self.sem.semctl(semid, semnum, cmd, arg,
                                      memory_reader=lambda a, sz: bytes(uc.mem_read(a, sz)),
                                      memory_writer=lambda a, d: uc.mem_write(a, d))
                uc.reg_write(arm.UC_ARM_REG_R0, ret & 0xffffffff if ret < 0 else ret)
                event = {'syscall': 'semctl', 'r7': 300, 'semid': semid, 'semnum': semnum,
                         'cmd': hex(cmd), 'arg': hex(arg), 'returned': ret,
                         'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                return
            if number in (301, 312):  # sys_semtimedop (a6400 glibc 2.11.2 wrapper uses 312)
                semid = uc.reg_read(arm.UC_ARM_REG_R0)
                tsops = uc.reg_read(arm.UC_ARM_REG_R1)
                nsops = uc.reg_read(arm.UC_ARM_REG_R2)
                timeout = uc.reg_read(arm.UC_ARM_REG_R3)
                ret = self.sem.semtimedop(semid, tsops, nsops, timeout_ptr=timeout,
                                          memory_reader=lambda a, sz: bytes(uc.mem_read(a, sz)),
                                          memory_writer=lambda a, d: uc.mem_write(a, d))
                uc.reg_write(arm.UC_ARM_REG_R0, ret & 0xffffffff if ret < 0 else ret)
                event = {'syscall': 'semtimedop', 'r7': number, 'semid': semid, 'tsops': hex(tsops),
                         'nsops': nsops, 'timeout': hex(timeout), 'returned': ret,
                         'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                return
            if number == 162:  # sys_nanosleep
                req_ptr = uc.reg_read(arm.UC_ARM_REG_R0)
                rem_ptr = uc.reg_read(arm.UC_ARM_REG_R1)
                raw_req = bytes(uc.mem_read(req_ptr, 8))
                tv_sec, tv_nsec = struct.unpack('<II', raw_req)
                ret = 0
                uc.reg_write(arm.UC_ARM_REG_R0, ret)
                event = {'syscall': 'nanosleep', 'r7': 162, 'tv_sec': tv_sec, 'tv_nsec': tv_nsec,
                         'returned': ret, 'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                if self.syscall_policy == 'threads' and hasattr(self, 'threads'):
                    if getattr(self, 'thread_sleep_policy', 'immediate') == 'block':
                        # Opt-in: no virtual clock exists, so a requested long sleep
                        # parks the caller instead of returning at once. Short sleeps
                        # are polling hints (e.g. the RM batch executor's 1 ms retry)
                        # and stay immediate, otherwise the emulator parks the very
                        # thread that has to make progress (E0355/E0353). The
                        # threshold and the no-deadline record are explicit.
                        duration_ns = tv_sec * 1_000_000_000 + tv_nsec
                        threshold_ns = getattr(self, 'thread_sleep_block_threshold_ns',
                                               100_000_000)
                        if duration_ns >= threshold_ns:
                            current_tid = self.threads.current_tid
                            self.threads.save_context(uc)
                            current = self.threads.threads[current_tid]
                            current.state = 'blocked_sleep'
                            current.blocked_uaddr = None
                            current.regs[arm.UC_ARM_REG_PC] = pc - size
                            current.regs[arm.UC_ARM_REG_R0] = 0
                            next_tid = self.threads.get_next_runnable_tid()
                            event.update(blocked_tid=current_tid,
                                         reason='nanosleep_no_virtual_deadline')
                            if next_tid is not None:
                                event['switched_to'] = next_tid
                                self.threads.restore_context(uc, next_tid, getattr(self, 'kuser', None))
                            else:
                                self.report.update(status='blocked_sleep', boundary=dict(event))
                                uc.reg_write(arm.UC_ARM_REG_PC, (pc - size) | int(thumb))
                                uc.emu_stop()
                            self.report['serviced_syscalls'].append(event)
                            self.report['syscall_responses_supplied'] += 1
                            return
                        event['reason'] = 'short_sleep_immediate'
                    next_tid = self.threads.get_next_runnable_tid()
                    if next_tid is not None:
                        event['switched_to'] = next_tid
                        self.threads.save_context(uc)
                        self.threads.threads[self.threads.current_tid].state = 'runnable'
                        self.threads.restore_context(uc, next_tid, getattr(self, 'kuser', None))
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                return
            if number == 78:  # sys_gettimeofday
                tv_ptr = uc.reg_read(arm.UC_ARM_REG_R0)
                tz_ptr = uc.reg_read(arm.UC_ARM_REG_R1)
                if tv_ptr != 0:
                    tv_sec = 1558936647 + (self.instructions // 1000000)
                    tv_usec = self.instructions % 1000000
                    uc.mem_write(tv_ptr, struct.pack('<II', tv_sec, tv_usec))
                if tz_ptr != 0:
                    uc.mem_write(tz_ptr, struct.pack('<II', 0, 0))
                ret = 0
                uc.reg_write(arm.UC_ARM_REG_R0, ret)
                event = {'syscall': 'gettimeofday', 'r7': 78, 'tv': tv_ptr, 'tz': tz_ptr,
                         'returned': ret, 'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                return
            if number == 263:  # sys_clock_gettime
                clk_id = uc.reg_read(arm.UC_ARM_REG_R0)
                tp_ptr = uc.reg_read(arm.UC_ARM_REG_R1)
                if tp_ptr != 0:
                    tv_sec = 1558936647 + (self.instructions // 1000000)
                    tv_nsec = (self.instructions % 1000000) * 1000
                    uc.mem_write(tp_ptr, struct.pack('<II', tv_sec, tv_nsec))
                ret = 0
                uc.reg_write(arm.UC_ARM_REG_R0, ret)
                event = {'syscall': 'clock_gettime', 'r7': 263, 'clk_id': clk_id, 'tp': tp_ptr,
                         'returned': ret, 'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                self.report['serviced_syscalls'].append(event)
                self.report['syscall_responses_supplied'] += 1
                return
        if svc and immediate == 0 and number == 21 and getattr(self, 'mount_service_policy', 'stop') == 'observed-nflasha1':
            self._serve_observed_mount(uc, pc, size, thumb)
            return
        if svc and immediate == 0 and number == 52 and getattr(self, 'mount_service_policy', 'stop') == 'observed-nflasha1':
            self._serve_observed_umount(uc, pc, size, thumb)
            return
        self.report.update(status='syscall_boundary' if svc and immediate == 0 else 'unsupported_exception',
                           boundary={'interrupt': interrupt, 'pc': pc, 'instruction_address': pc - size,
                                     'instruction_bytes': raw.hex(), 'thumb': thumb,
                                     'svc_immediate': immediate if svc else None,
                                     'r7': uc.reg_read(arm.UC_ARM_REG_R7),
                                     'arguments': [uc.reg_read(r) for r in
                                                   (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2,
                                                    arm.UC_ARM_REG_R3, arm.UC_ARM_REG_R4, arm.UC_ARM_REG_R5, arm.UC_ARM_REG_R6)]})
        if svc and immediate == 0 and uc.reg_read(arm.UC_ARM_REG_R7) in (5, 33, 85, 195, 196):
            self.report['boundary']['path_preview'] = cstring_preview(uc, uc.reg_read(arm.UC_ARM_REG_R0))
        if svc and immediate == 0 and uc.reg_read(arm.UC_ARM_REG_R7) == 128:
            self.report['boundary']['uargs_preview'] = cstring_preview(uc, uc.reg_read(arm.UC_ARM_REG_R2))
        uc.emu_stop()

    def _serve_observed_mount(self, uc, pc, size, thumb):
        """Serve only the observed read-only vfat mount of /dev/nflasha1 at /mnt.

        Arguments are compared with the E0307 boundary (source/target/fstype/
        flags/data). On a match the hash-checked nflasha1 vfat image is
        materialised read-only; any other mount is an explicit boundary.
        """
        filesystem = self.filesystem

        def guest_string(pointer, *, absolute=False):
            if not pointer:
                return None
            preview = cstring_preview(uc, pointer)
            if preview.get('status') != 'terminated':
                return None
            value = preview.get('value', '')
            if absolute and not value.startswith('/'):
                return None
            return value

        source = guest_string(uc.reg_read(arm.UC_ARM_REG_R0), absolute=True)
        target = guest_string(uc.reg_read(arm.UC_ARM_REG_R1), absolute=True)
        fstype = guest_string(uc.reg_read(arm.UC_ARM_REG_R2))
        flags = uc.reg_read(arm.UC_ARM_REG_R3)
        data = guest_string(uc.reg_read(arm.UC_ARM_REG_R4))
        event = {'syscall': 'mount', 'r7': 21, 'source': source, 'target': target,
                 'fstype': fstype, 'flags': flags, 'data': data,
                 'pc': pc, 'instruction_address': pc - size, 'thumb': thumb,
                 'policy': 'observed-nflasha1'}
        image = getattr(self, 'vfat_image', None)
        if image is None:
            self.report.update(status='unsupported_mount_contract', boundary={
                **event, 'reason': 'mount_image_identity_missing'})
            uc.emu_stop()
            return
        observed = {'source': '/dev/nflasha1', 'target': '/mnt', 'fstype': 'vfat',
                    'flags': 3236757505, 'data': 'posix_attr'}
        if {'source': source, 'target': target, 'fstype': fstype,
                'flags': flags, 'data': data} != observed:
            self.report.update(status='unsupported_mount_contract', boundary={
                **event, 'observed': observed, 'reason': 'mount_arguments_not_observed'})
            uc.emu_stop()
            return
        try:
            mounted = filesystem.mount_vfat(target, image)
        except UnsupportedFilesystem as error:
            self.report.update(status='unsupported_mount_contract', boundary={
                **event, 'reason': str(error), **error.details})
            uc.emu_stop()
            return
        event.update(returned=0, reason='observed_nflasha1_vfat_read_only',
                     mounted=mounted, image_sha256=image.image_sha256)
        self.report.setdefault('mounts', []).append(event)
        self.report['serviced_syscalls'].append(event)
        self.report['syscall_responses_supplied'] += 1
        uc.reg_write(arm.UC_ARM_REG_R0, 0)

    def _serve_observed_umount(self, uc, pc, size, thumb):
        """Serve only the observed read-only unmount of /mnt (flags 0)."""
        filesystem = self.filesystem
        target_pointer = uc.reg_read(arm.UC_ARM_REG_R0)
        preview = cstring_preview(uc, target_pointer) if target_pointer else {'status': 'unreadable'}
        target = preview.get('value') if preview.get('status') == 'terminated' else None
        flags = uc.reg_read(arm.UC_ARM_REG_R1)
        event = {'syscall': 'umount2', 'r7': 52, 'target': target, 'flags': flags,
                 'pc': pc, 'instruction_address': pc - size, 'thumb': thumb,
                 'policy': 'observed-nflasha1'}
        if target != '/mnt' or flags != 0:
            self.report.update(status='unsupported_mount_contract', boundary={
                **event, 'observed': {'target': '/mnt', 'flags': 0},
                'reason': 'umount_arguments_not_observed'})
            uc.emu_stop()
            return
        try:
            unmounted = filesystem.umount_vfat(target)
        except UnsupportedFilesystem as error:
            self.report.update(status='unsupported_mount_contract', boundary={
                **event, 'reason': str(error), **error.details})
            uc.emu_stop()
            return
        event.update(returned=0, reason='observed_nflasha1_vfat_read_only_unmounted',
                     unmounted=unmounted)
        self.report.setdefault('mounts', []).append(event)
        self.report['serviced_syscalls'].append(event)
        self.report['syscall_responses_supplied'] += 1
        uc.reg_write(arm.UC_ARM_REG_R0, 0)

    def _memory(self, uc, access, address, size, value, user_data):
        if getattr(self, 'null_page_policy', None) == 'read-zero' and 0 <= address < 4096:
            return True
        boundary = {'access': access, 'address': address, 'size': size,
                    'value': value, 'pc': uc.reg_read(arm.UC_ARM_REG_PC)}
        page = address & ~0xfff
        if page in getattr(getattr(self, 'mmap', None), 'beyond_eof_pages', ()):
            # Linux delivers SIGBUS here; the signal itself is not delivered by this model.
            owner = next((m for m in reversed(self.mmap.mappings)
                          if m['address'] <= page < m['address'] + m['length'] and 'beyond_eof' in m), {})
            boundary.update(signal='SIGBUS', reason='file_mapping_access_beyond_eof',
                            path=owner.get('path'), mapping_address=owner.get('address'),
                            file_offset=owner.get('offset', 0) + (address - owner['address']) if owner else None)
        self.report.update(status='memory_boundary', boundary=boundary)
        uc.emu_stop()
        return False

    MAX_SIGILL_DELIVERIES = 64
    MAX_SIGILL_EVENTS_RECORDED = 16

    def _invalid_insn(self, uc, user_data):
        pc = uc.reg_read(arm.UC_ARM_REG_PC)
        cpsr = uc.reg_read(arm.UC_ARM_REG_CPSR)
        thumb = bool(cpsr & 0x20)
        sigill = self.signal_handlers.get(4)
        self.sigill_count = getattr(self, 'sigill_count', 0) + 1
        if self.sigill_count > self.MAX_SIGILL_DELIVERIES:
            # Fail closed: a handler that keeps faulting is not a supported signal contract.
            try:
                raw = bytes(uc.mem_read(pc, 8)).hex()
            except unicorn.UcError:
                raw = None
            self.report.update(status='signal_loop_boundary',
                               boundary={'reason': 'repeated_sigill_delivery', 'pc': pc, 'thumb': thumb,
                                         'instruction_bytes': raw, 'deliveries': self.sigill_count - 1,
                                         'sp': uc.reg_read(arm.UC_ARM_REG_SP),
                                         'lr': uc.reg_read(arm.UC_ARM_REG_LR)})
            uc.emu_stop()
            return False
        if sigill and sigill.get('handler') not in (0, 1):
            handler = sigill['handler']
            sp = uc.reg_read(arm.UC_ARM_REG_SP)
            sp = (sp - 64) & ~7
            uc.reg_write(arm.UC_ARM_REG_SP, sp)
            uc.reg_write(arm.UC_ARM_REG_R0, 4)
            if sigill.get('restorer'):
                uc.reg_write(arm.UC_ARM_REG_LR, sigill['restorer'])
            if handler & 1:
                # Unicorn switches to Thumb only when PC is written with bit 0 set.
                uc.reg_write(arm.UC_ARM_REG_PC, handler)
            else:
                uc.reg_write(arm.UC_ARM_REG_CPSR, cpsr & ~0x20)
                uc.reg_write(arm.UC_ARM_REG_PC, handler)
            event = {'signal': 'SIGILL', 'signum': 4, 'fault_pc': pc,
                     'handler': handler, 'thumb': bool(handler & 1),
                     'reason': 'delivered_to_registered_guest_handler'}
            if self.sigill_count <= self.MAX_SIGILL_EVENTS_RECORDED:
                self.report['serviced_syscalls'].append(event)
            return True
        return False

    def _before_host_read(self, address, size):
        self.uname.assert_known_host_read(address, size)
        if hasattr(self, 'stat64'):
            self.stat64.assert_known_host_read(address, size)
        if hasattr(self, 'stream'):
            self.stream.assert_known_host_read(address, size)

    def _uipc_read(self, address, size):
        if not accessible(self.mu, address, size, unicorn.UC_PROT_READ):
            raise UnsupportedUipc('uipc_read_not_accessible', address=address, size=size)
        self._before_host_read(address, size)
        return bytes(self.mu.mem_read(address, size))

    def _uipc_write(self, address, data):
        if not accessible(self.mu, address, len(data), unicorn.UC_PROT_WRITE):
            raise UnsupportedUipc('uipc_write_not_accessible', address=address, size=len(data))
        self.mu.mem_write(address, data)
        self._after_host_write(address, len(data))

    def _after_host_write(self, address, size):
        if hasattr(self, 'uname'):
            self.uname.forget_range(address, size)
        if hasattr(self, 'stat64'):
            self.stat64.forget_range(address, size)
        if hasattr(self, 'stream'):
            self.stream.forget_range(address, size)

    def _stream_boundary(self, error, pc, number):
        self.report.update(status='unsupported_stream_contract',
                           boundary={**error.details, 'pc': pc, 'r7': number})
        self.mu.emu_stop()

    def _stream_host_read(self, address, size):
        if not accessible(self.mu, address, size, unicorn.UC_PROT_READ):
            raise UnsupportedStream('stream_host_copy_source_not_accessible', address=address, size=size)
        self._before_host_read(address, size)
        return bytes(self.mu.mem_read(address, size))

    def _identity_boundary(self, details):
        self.report.update(status=('unverified_device_read' if details.get('domain') == 'stream' else
                                   'unverified_metadata_read' if details.get('domain') == 'stat64' else 'unverified_identity_read'),
                           boundary={**details, 'pc': self.mu.reg_read(arm.UC_ARM_REG_PC)})
        self.mu.emu_stop()

    def begin(self, instruction_budget=100000, timeout_us=2000000):
        """Open a run without executing; slices may follow via run_slice()."""
        if not self.prepared:
            raise ValueError('Prepare the process before execution')
        if instruction_budget <= 0 or timeout_us <= 0:
            raise ValueError('Execution limits must be positive')
        if self._run_open:
            raise ValueError('A run is already open; use run_slice() or finish()')
        if self.report['status'] != 'not_started':
            raise ValueError('Use a fresh probe for each run')
        self._run_open = True
        self._slices_executed = 0
        self.report.update(status='running', instruction_budget=instruction_budget, timeout_us=timeout_us,
                           madvise_policy=self.madvise_policy)
        threads = getattr(self, 'threads', None)
        if threads is not None and threads.threads[threads.current_tid].state.startswith('blocked_'):
            next_tid = threads.get_next_runnable_tid()
            if next_tid is None:
                self.report.update(status='blocked_threads', boundary={'reason': 'no_runnable_guest_thread'})
                return self
            threads.restore_context(self.mu, next_tid, getattr(self, 'kuser', None))
            self.entry = self.mu.reg_read(arm.UC_ARM_REG_PC)
            if self.mu.reg_read(arm.UC_ARM_REG_CPSR) & 0x20:
                self.entry |= 1
        if (getattr(self, 'trace_usbcontrol_dispatch', False)
                and not getattr(self, '_usbcontrol_dispatch_installed', False)):
            # Setting the opt-in attribute after checkpoint restore is enough;
            # the CLI also installs explicitly so hook resolution is reported
            # before execution starts.
            self.install_usbcontrol_dispatch_hooks()
        self._maybe_inject_usb_connect()
        return self

    def run_slice(self, instruction_count, timeout_us=None):
        """Execute one bounded slice of an open run; a pause stays resumable."""
        if not self.prepared:
            raise ValueError('Prepare the process before execution')
        if not self._run_open:
            raise ValueError('Call begin() before run_slice()')
        if instruction_count <= 0:
            raise ValueError('Slice instruction count must be positive')
        if self.report['status'] not in ('running', 'paused'):
            raise ValueError('Run is not resumable')
        timeout = self.report.get('timeout_us') if timeout_us is None else timeout_us
        if timeout is None or timeout <= 0:
            raise ValueError('Execution limits must be positive')
        self._pause_requested = False
        self.report['status'] = 'running'
        if getattr(self, '_slices_executed', 0) == 0:
            start = self.entry
        else:
            start = self.mu.reg_read(arm.UC_ARM_REG_PC)
            if self.mu.reg_read(arm.UC_ARM_REG_CPSR) & 0x20:
                start |= 1
        self._slices_executed = getattr(self, '_slices_executed', 0) + 1
        try:
            self.mu.emu_start(start, 0, timeout=timeout, count=instruction_count)
        except unicorn.UcError as error:
            if self.report['status'] == 'running':
                self.report['status'] = 'execution_fault'
            self.report['engine_error'] = str(error)
            return self.report
        if self.report['status'] == 'running' and self.mu.query(unicorn.UC_QUERY_TIMEOUT):
            self.report['status'] = 'timeout'
        return self.report

    def pause(self):
        """Request a stop at the next block/instruction boundary."""
        if self._run_open and self.report['status'] == 'running':
            self._pause_requested = True

    def finish(self, reason=None):
        """Close an open run and build the final report."""
        if self._run_open:
            self._run_open = False
            if self.report['status'] == 'running':
                self.report['status'] = reason or 'instruction_budget_exhausted'
        return self._finalize_report()

    def run(self, instruction_budget=100000, timeout_us=2000000):
        self.begin(instruction_budget, timeout_us)
        if self.report['status'] == 'blocked_threads':
            return self.finish()
        budget_remaining = instruction_budget - self.instructions if instruction_budget > self.instructions else instruction_budget
        self.run_slice(budget_remaining, timeout_us)
        if (self.hook_mode == 'fast' and not getattr(self, '_stop_hit', False)
                and self.report.get('status') in ('running', 'instruction_budget_exhausted')):
            self.instructions = max(self.instructions, instruction_budget)
        return self.finish()

    def _finalize_report(self):
        last_insns = []
        for item in self.tail:
            if isinstance(item, tuple):
                addr, sz = item
                try:
                    raw_hex = bytes(self.mu.mem_read(addr, sz)).hex()
                except unicorn.UcError:
                    raw_hex = ''
                last_insns.append({'address': addr, 'size': sz, 'bytes': raw_hex})
            else:
                last_insns.append(item)
        self.report.update(instructions_executed=self.instructions, last_instructions=last_insns,
                           pc=self.mu.reg_read(arm.UC_ARM_REG_PC))
        if self.syscall_policy in ('brk', 'brk-uname', 'files', 'metadata', 'mmap', 'kuser', 'uipc', 'threads'):
            self.report['heap']['final'] = self.heap.current
        if self.syscall_policy in ('brk-uname', 'files', 'metadata', 'mmap', 'kuser', 'uipc', 'threads'):
            self.report['uname_fields_read'] = self.uname.read_fields
        if self.syscall_policy in ('files', 'metadata', 'mmap', 'kuser', 'uipc', 'threads'):
            self.report['file_descriptors'] = {str(fd): {key: value for key, value in item.items() if key != 'data'}
                                                for fd, item in self.filesystem.fds.items()}
        if hasattr(self, 'stat64'):
            self.report['stat64_fields_read'] = self.stat64.read_fields
        if hasattr(self, 'mmap'):
            self.report['mappings'] = self.mmap.mappings
        if hasattr(self, 'kuser'):
            self.report['kuser'] = {'page': 0xffff0000, 'version': 5, 'tls': self.kuser.tls_value}
        if hasattr(self, 'uipc'):
            self.report['uipc'] = {
                'connected': self.uipc.connected,
                'pool_base': self.uipc.pool_base,
                'total_pool_size': self.uipc.total_pool_size,
                'callbacks': self.uipc.callbacks,
                'transactions': self.uipc.transactions
            }
        if hasattr(self, 'stdio'):
            stderr_text = b''.join(self.stdio.stderr_log).decode('latin1', errors='replace')
            self.report['stdio'] = {
                'stdout_chunks': len(self.stdio.stdout_log),
                'stderr_chunks': len(self.stdio.stderr_log),
                'stdout_preview': b''.join(self.stdio.stdout_log).decode('latin1', errors='replace')[:256],
                'stderr_preview': stderr_text[:1024]
            }
            self.report['loader_stop'] = summarize_loader_stop(
                self.report.get('serviced_syscalls', []), stderr_text,
                self.report.get('boundary'))
        if hasattr(self, 'threads'):
            self.report['thread_group_id'] = self.threads.process_id
            self.report['threads'] = {str(tid): t.to_dict() for tid, t in self.threads.threads.items()}
            self.report['thread_events'] = self.threads.thread_log
        if hasattr(self, 'fb'):
            self.report['framebuffer'] = {
                'vram_base': self.fb.vram_base,
                'vram_length': self.fb.vram_length,
                'width': self.fb.width,
                'height': self.fb.height,
                'bpp': self.fb.bpp,
                'xoffset': self.fb.xoffset,
                'yoffset': self.fb.yoffset,
                'transactions': self.fb.transactions
            }
        if hasattr(self, 'stream'):
            self.report['stream'] = self.stream.report()
        if getattr(self, 'kikilog', None) is not None:
            self.report['kikilog'] = {'policy': self.kikilog.policy,
                                      'source_sha256': self.kikilog.source_sha256,
                                      'transactions': self.kikilog.transactions}
        if self.display is not None:
            self.report['display'] = self.display.report()
        return self.report

