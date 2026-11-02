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
from src.a6400.execution.kernel_task_identity import UnsupportedKernelBinding


class InterpreterProbe:
    def __init__(self, syscall_policy='stop', uname_profile=None, filesystem=None, kuser_template=None,
                 madvise_policy='stop', backup_service_policy='unverified-ack',
                 graphics_service_policy='stop', null_page_policy='stop',
                 kmod_service_policy='stop',
                 mmap_base=None, mmap_ceiling=None, mmap_search_low=None):
        if null_page_policy not in ('stop', 'read-zero'):
            raise ValueError('Unknown null page policy')
        self.null_page_policy = null_page_policy
        if backup_service_policy not in ('stop', 'unverified-ack', 'preset-backed'):
            raise ValueError('Unknown backup service policy')
        if graphics_service_policy not in ('stop', 'authentic-grm'):
            raise ValueError('Unknown graphics service policy')
        if kmod_service_policy not in ('stop', 'verified-image'):
            raise ValueError('Unknown kmod service policy')
        self.kmod_service_policy = kmod_service_policy
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
        if madvise_policy != 'stop':
            self.report['assumptions'].append('Optional MADV_DONTNEED: only owned private anonymous pages; eager zeroing models later zero-fill reads, not RSS, physical reclaim or timing.')
        self.prepared = False
        self.prepare_attempted = False
        self.tail = deque(maxlen=32)
        self.signal_handlers = {}
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
                                  graphics_service_policy=graphics_service_policy)
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
            self.mu.mem_map(0, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
            self.mu.mem_write(0, bytes(4096))

            def _null_page_read_guard(uc, access, address, size, value, user_data):
                if address < 16:
                    uc.mem_write(0, bytes(16))
            self.mu.hook_add(unicorn.UC_HOOK_MEM_READ, _null_page_read_guard, begin=0, end=16)
        self.prepared = True

    def _code(self, uc, address, size, user_data):
        self.instructions += 1
        self.tail.append({'address': address, 'size': size,
                          'bytes': bytes(uc.mem_read(address, size)).hex()})
        # Workaround for emulator bug where a Thumb-2 IT block with mixed 16/32-bit instructions
        # leaves leftover IT bits in CPSR, corrupting subsequent non-IT instructions.
        if self.syscall_policy in ('mmap', 'kuser', 'uipc', 'threads') and address in (0x40004e4c, 0x50259c24):
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
                        runnable = [t.tid for t in self.threads.threads.values() if t.state == 'runnable' and t.tid != self.threads.current_tid]
                        if runnable:
                            next_tid = runnable[0]
                            self.threads.save_context(uc)
                            self.threads.threads[self.threads.current_tid].state = 'runnable'
                            self.threads.restore_context(uc, next_tid, self.kuser)
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
                    ret = 0
                else:
                    ret = 0xfffffff7  # -EBADF
                uc.reg_write(arm.UC_ARM_REG_R0, ret)
                event = {'syscall': 'close', 'r7': 6, 'fd': fd, 'returned': ret,
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
        try:
            self.mu.emu_start(self.entry, 0, timeout=timeout_us, count=instruction_budget)
            if self.report['status'] == 'running':
                self.report['status'] = ('timeout' if self.mu.query(unicorn.UC_QUERY_TIMEOUT)
                                         else 'instruction_budget_exhausted' if self.instructions >= instruction_budget
                                         else 'unexpected_stop')
        except unicorn.UcError as error:
            if self.report['status'] == 'running':
                self.report['status'] = 'execution_fault'
            self.report['engine_error'] = str(error)
        self.report.update(instructions_executed=self.instructions, last_instructions=list(self.tail),
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

