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
from src.a6400.execution.guest_usb_buspower import GuestUsbBusPower, UnsupportedUsbBusPower
from src.a6400.execution.guest_usb_event import GuestUsbEvent, UnsupportedUsbEvent
from src.a6400.execution.guest_usb_otgcore import GuestUsbOtgCore, UnsupportedUsbOtgCore
from src.a6400.execution.guest_hdmi import GuestHdmi, UnsupportedHdmi
from src.a6400.execution.guest_cec import GuestCec, UnsupportedCec
from src.a6400.execution.guest_mmca_char import GuestMmcChar, UnsupportedMmcChar, MMC_CHAR_NODES
from src.a6400.execution.guest_pipe import GuestPipe, UnsupportedPipe, POLLNVAL, POLLERR, POLLHUP
from src.a6400.execution.guest_sem import GuestSem
from src.a6400.execution.kernel_task_identity import UnsupportedKernelBinding


class InterpreterProbe:
    def __init__(self, syscall_policy='stop', uname_profile=None, filesystem=None, kuser_template=None,
                 madvise_policy='stop', backup_service_policy='unverified-ack',
                 graphics_service_policy='stop', null_page_policy='stop',
                 kmod_service_policy='stop',
                 media_service_policy='stop', hook_mode='instruction',
                 mmap_base=None, mmap_ceiling=None, mmap_search_low=None):
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
        if madvise_policy != 'stop':
            self.report['assumptions'].append('Optional MADV_DONTNEED: only owned private anonymous pages; eager zeroing models later zero-fill reads, not RSS, physical reclaim or timing.')
        self.prepared = False
        self.prepare_attempted = False
        self.tail = deque(maxlen=32)
        self.signal_handlers = {}
        if self.hook_mode == 'fast':
            self.mu.hook_add(unicorn.UC_HOOK_BLOCK, self._block)
            for it_addr in (0x40004e4c, 0x50259c24, 0x50034e32, 0x50034e6a):
                self.mu.hook_add(unicorn.UC_HOOK_CODE, self._it_workaround, begin=it_addr, end=it_addr)
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
            mmap_kwargs = {'after_write': self._after_host_write}
            if mmap_base is not None:
                mmap_kwargs['base_address'] = mmap_base
            if mmap_ceiling is not None:
                mmap_kwargs['ceiling_address'] = mmap_ceiling
            if mmap_search_low is not None:
                mmap_kwargs['search_low_base'] = mmap_search_low
            self.mmap = GuestMmap(self.mu, self.filesystem, **mmap_kwargs)
            self.report['assumptions'].append('Optional mmap contract: ARM EABI mmap2/mprotect/munmap allocate page-aligned guest memory from verified files or anonymous pages.')
        if syscall_policy in ('kuser', 'uipc', 'threads'):
            if kuser_template is None:
                raise ValueError('The kuser policy requires a verified kuser helper template')
            self.kuser = GuestKuser(self.mu, kuser_template)
            self.report['assumptions'].append('ARM Linux high vectors page at 0xffff0000 with kernel helper template (version 5) and set_tls contract.')
        if syscall_policy in ('uipc', 'threads'):
            self.uipc = GuestUipc(backup_service_policy=backup_service_policy,
                                  graphics_service_policy=graphics_service_policy,
                                  media_service_policy=media_service_policy)
            self.report['media_service_policy'] = media_service_policy
            self.report['backup_service_policy'] = backup_service_policy
            self.report['graphics_service_policy'] = graphics_service_policy
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
                stack_bottom=0x7fe00000, stack_size=0x100000):
        if self.prepare_attempted:
            raise ValueError('Use a fresh probe for each preparation attempt')
        self.prepare_attempted = True
        if application['type'] != 'ET_EXEC' or interpreter['type'] != 'ET_DYN':
            raise ValueError('This experiment requires ET_EXEC application and ET_DYN interpreter')
        app = map_image(self.mu, application, 0)
        linker = map_image(self.mu, interpreter, interpreter_bias)
        self.mu.mem_map(stack_bottom, stack_size, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
        stack = build_stack(stack_bottom, stack_size, argv, [], app, interpreter_bias)
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
        if self.syscall_policy in ('mmap', 'kuser', 'uipc', 'threads'):
            cpsr = uc.reg_read(arm.UC_ARM_REG_CPSR)
            if cpsr & ((3 << 25) | (0x3f << 10)):
                uc.reg_write(arm.UC_ARM_REG_CPSR, cpsr & ~((3 << 25) | (0x3f << 10)))

    def _block(self, uc, address, size, user_data):
        insn_est = max(1, size // 2)
        self.instructions += insn_est
        if self._progress_interval and self.instructions % self._progress_interval < insn_est:
            self._on_progress(self)
        self.tail.append((address, size))

    def _code(self, uc, address, size, user_data):
        self.instructions += 1
        if self._progress_interval and self.instructions % self._progress_interval == 0:
            self._on_progress(self)
        self.tail.append((address, size))
        # Workaround for emulator bug where a Thumb-2 IT block with mixed 16/32-bit instructions
        # leaves leftover IT bits in CPSR, corrupting subsequent non-IT instructions.
        if address in (0x40004e4c, 0x50259c24, 0x50034e32, 0x50034e6a) and self.syscall_policy in ('mmap', 'kuser', 'uipc', 'threads'):
            cpsr = uc.reg_read(arm.UC_ARM_REG_CPSR)
            if cpsr & ((3 << 25) | (0x3f << 10)):
                uc.reg_write(arm.UC_ARM_REG_CPSR, cpsr & ~((3 << 25) | (0x3f << 10)))

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
            if number in (3, 4, 19, 146, 197):
                stream_fd = uc.reg_read(arm.UC_ARM_REG_R0)
                if self.filesystem.fds.get(stream_fd, {}).get('device') == 'stream':
                    self._stream_boundary(UnsupportedStream('stream_file_operation_not_supported',
                                                           number=number, fd=stream_fd), pc, number)
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
                if fd in self.filesystem.fds and self.filesystem.fds[fd].get('device') == 'dmpgles2':
                    owner_id = self.filesystem.fds[fd].get('owner_id')
                    try:
                        ret = self.gles.ioctl(
                            owner_id, cmd, arg,
                            lambda addr, sz: bytes(uc.mem_read(addr, sz)),
                            lambda addr, data: uc.mem_write(addr, data)
                        )
                    except UnsupportedGles as error:
                        self.report.update(status='unsupported_gles_contract', boundary={
                            **error.details, 'fd': fd, 'cmd': cmd, 'arg': arg,
                            'pc': pc, 'r7': number, 'instruction_address': pc - size})
                        uc.emu_stop()
                        return
                    event = {'syscall': 'ioctl', 'r7': 54, 'fd': fd, 'cmd': cmd, 'arg': arg, 'returned': ret,
                             'pc': pc, 'instruction_address': pc - size, 'thumb': thumb, 'device': 'dmpgles2'}
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
                        ret = self.uipc.handle_ioctl(self._uipc_read, self._uipc_write, cmd, arg)
                    except UnverifiedGuestData as error:
                        self._identity_boundary(error.details)
                        return
                    except UnsupportedUipc as error:
                        self.report.update(status='unsupported_uipc_contract', boundary={
                            **error.details, 'pc': pc, 'r7': number, 'cmd': cmd, 'arg': arg})
                        uc.emu_stop()
                        return
                    if ret is None and cmd == 0x80000007 and self.syscall_policy == 'threads':
                        self.threads.save_context(uc)
                        self.threads.threads[self.threads.current_tid].regs[arm.UC_ARM_REG_PC] = pc - size
                        next_tid, event = self.threads.handle_uipc_wait(queue, pc - size)
                        event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
                        self.report['serviced_syscalls'].append(event)
                        if next_tid is not None:
                            self.threads.restore_context(uc, next_tid, getattr(self, 'kuser', None))
                        else:
                            self.report.update(status='blocked_uipc', boundary=event)
                            uc.emu_stop()
                        return
                    if ret is not None:
                        event = {'syscall': 'ioctl', 'r7': 54, 'fd': fd, 'cmd': cmd, 'arg': arg, 'returned': ret,
                                 'pc': pc, 'instruction_address': pc - size, 'thumb': thumb}
                        if self.syscall_policy == 'threads' and ret == 0:
                            woken = []
                            if cmd == 0x80000004:
                                woken.extend(self.threads.handle_uipc_wake(queue))
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
        if svc and immediate == 0 and self.syscall_policy in ('files', 'metadata', 'mmap', 'kuser', 'uipc', 'threads') and number in ((3, 5, 6, 19, 33, 195, 197) if self.syscall_policy in ('metadata', 'mmap', 'kuser', 'uipc', 'threads') else (3, 5, 6, 19, 33, 195)):
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
            if number == 242:  # sched_setaffinity
                pid = uc.reg_read(arm.UC_ARM_REG_R0)
                len_ = uc.reg_read(arm.UC_ARM_REG_R1)
                mask = uc.reg_read(arm.UC_ARM_REG_R2)
                ret, event = self.threads.handle_sched_setaffinity(pid, len_, mask)
                uc.reg_write(arm.UC_ARM_REG_R0, ret)
                event.update(pc=pc, instruction_address=pc - size, thumb=thumb)
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
            if number == 301:  # sys_semtimedop
                semid = uc.reg_read(arm.UC_ARM_REG_R0)
                tsops = uc.reg_read(arm.UC_ARM_REG_R1)
                nsops = uc.reg_read(arm.UC_ARM_REG_R2)
                timeout = uc.reg_read(arm.UC_ARM_REG_R3)
                ret = self.sem.semtimedop(semid, tsops, nsops, timeout_ptr=timeout,
                                          memory_reader=lambda a, sz: bytes(uc.mem_read(a, sz)),
                                          memory_writer=lambda a, d: uc.mem_write(a, d))
                uc.reg_write(arm.UC_ARM_REG_R0, ret & 0xffffffff if ret < 0 else ret)
                event = {'syscall': 'semtimedop', 'r7': 301, 'semid': semid, 'tsops': hex(tsops),
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

    def _memory(self, uc, access, address, size, value, user_data):
        if getattr(self, 'null_page_policy', None) == 'read-zero' and 0 <= address < 4096:
            return True
        self.report.update(status='memory_boundary',
                           boundary={'access': access, 'address': address, 'size': size,
                                     'value': value, 'pc': uc.reg_read(arm.UC_ARM_REG_PC)})
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

    def run(self, instruction_budget=100000, timeout_us=2000000):
        if not self.prepared:
            raise ValueError('Prepare the process before execution')
        if instruction_budget <= 0 or timeout_us <= 0:
            raise ValueError('Execution limits must be positive')
        if self.report['status'] != 'not_started':
            raise ValueError('Use a fresh probe for each run')
        self.report.update(status='running', instruction_budget=instruction_budget, timeout_us=timeout_us,
                           madvise_policy=self.madvise_policy)
        budget_remaining = instruction_budget - self.instructions if instruction_budget > self.instructions else instruction_budget
        try:
            self.mu.emu_start(self.entry, 0, timeout=timeout_us, count=budget_remaining)
            if self.report['status'] == 'running':
                self.report['status'] = ('timeout' if self.mu.query(unicorn.UC_QUERY_TIMEOUT)
                                         else 'instruction_budget_exhausted' if (self.instructions >= instruction_budget or self.hook_mode == 'fast')
                                         else 'unexpected_stop')
            if self.hook_mode == 'fast' and self.report['status'] == 'instruction_budget_exhausted':
                self.instructions = max(self.instructions, instruction_budget)
        except unicorn.UcError as error:
            if self.report['status'] == 'running':
                self.report['status'] = 'execution_fault'
            self.report['engine_error'] = str(error)
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
            self.report['stdio'] = {
                'stdout_chunks': len(self.stdio.stdout_log),
                'stderr_chunks': len(self.stdio.stderr_log),
                'stdout_preview': b''.join(self.stdio.stdout_log).decode('latin1', errors='replace')[:256]
            }
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
        return self.report

