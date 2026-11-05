"""PC <-> Sony ILCE-6400 Communication Layer and Emulator Boundary Analyzer.

Provides the closed-loop workflow between the A6400 emulator and the physical
Sony ILCE-6400 camera (connected via USB in Mass Storage / Senser mode):

1. BoundaryAnalyzer:
   - Inspects emulator stop reports (artifacts/execution/*.json).
   - Resolves guest PC and LR virtual addresses to exact firmware ELF binaries,
     function symbols (.symtab / .dynsym), and Capstone ARM/Thumb disassembly.
   - Decodes ARM EABI syscall numbers (r7) and Linux _IOC ioctl commands.
   - Cross-references the stop boundary against existing camera ground-truth
     telemetry (reports/a6400_hw_dump.txt) and firmware device tables.
   - Generates targeted camera diagnostic probes when new hardware readings
     are required.

2. CameraLink:
   - Connects to the physical Sony ILCE-6400 in Mass Storage mode via PMCA
     Senser protocol.
   - Supports chunk-safe file reads (bypassing the 32 KB PMCA padding timeout),
     direct memory dumps, backup ID reads, and self-cleaning diagnostic probes
     in /tmp/autoexec.sh that automatically restore the camera to clean standby.
"""
import argparse
import io
import json
import os
import re
import struct
import sys
import time
from pathlib import Path

import capstone
from elftools.elf.elffile import ELFFile

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ARM_SYSCALL_TABLE = {
    0: ('restart_syscall', 'void'),
    1: ('exit', 'int status'),
    2: ('fork', 'void'),
    3: ('read', 'int fd, void *buf, size_t count'),
    4: ('write', 'int fd, const void *buf, size_t count'),
    5: ('open', 'const char *pathname, int flags, mode_t mode'),
    6: ('close', 'int fd'),
    9: ('link', 'const char *oldpath, const char *newpath'),
    10: ('unlink', 'const char *pathname'),
    11: ('execve', 'const char *filename, char *const argv[], char *const envp[]'),
    12: ('chdir', 'const char *path'),
    13: ('time', 'time_t *tloc'),
    14: ('mknod', 'const char *pathname, mode_t mode, dev_t dev'),
    15: ('chmod', 'const char *pathname, mode_t mode'),
    19: ('lseek', 'int fd, off_t offset, int whence'),
    20: ('getpid', 'void'),
    21: ('mount', 'const char *source, const char *target, const char *fstype, unsigned long flags, const void *data'),
    22: ('umount', 'const char *target'),
    24: ('getuid', 'void'),
    33: ('access', 'const char *pathname, int mode'),
    36: ('sync', 'void'),
    37: ('kill', 'pid_t pid, int sig'),
    38: ('rename', 'const char *oldpath, const char *newpath'),
    39: ('mkdir', 'const char *pathname, mode_t mode'),
    40: ('rmdir', 'const char *pathname'),
    41: ('dup', 'int oldfd'),
    42: ('pipe', 'int pipefd[2]'),
    43: ('times', 'struct tms *buf'),
    45: ('brk', 'void *addr'),
    47: ('getgid', 'void'),
    54: ('ioctl', 'int fd, unsigned long request, unsigned long arg'),
    55: ('fcntl', 'int fd, int cmd, unsigned long arg'),
    63: ('dup2', 'int oldfd, int newfd'),
    64: ('getppid', 'void'),
    66: ('setsid', 'void'),
    78: ('gettimeofday', 'struct timeval *tv, struct timezone *tz'),
    85: ('readlink', 'const char *pathname, char *buf, size_t bufsiz'),
    90: ('mmap', 'void *addr, size_t length, int prot, int flags, int fd, off_t offset'),
    91: ('munmap', 'void *addr, size_t length'),
    104: ('setitimer', 'int which, const struct itimerval *new_value, struct itimerval *old_value'),
    114: ('wait4', 'pid_t pid, int *wstatus, int options, struct rusage *rusage'),
    118: ('fsync', 'int fd'),
    120: ('clone', 'unsigned long flags, void *child_stack, int *ptid, unsigned long tls, int *ctid'),
    122: ('uname', 'struct utsname *buf'),
    125: ('mprotect', 'void *addr, size_t len, int prot'),
    128: ('init_module', 'void *module_image, unsigned long len, const char *param_values'),
    129: ('delete_module', 'const char *name, int flags'),
    140: ('_llseek', 'unsigned int fd, unsigned long offset_high, unsigned long offset_low, loff_t *result, unsigned int whence'),
    142: ('_newselect', 'int nfds, fd_set *readfds, fd_set *writefds, fd_set *exceptfds, struct timeval *timeout'),
    145: ('readv', 'int fd, const struct iovec *iov, int iovcnt'),
    146: ('writev', 'int fd, const struct iovec *iov, int iovcnt'),
    148: ('fdatasync', 'int fd'),
    154: ('sched_setparam', 'pid_t pid, const struct sched_param *param'),
    155: ('sched_getparam', 'pid_t pid, struct sched_param *param'),
    156: ('sched_setscheduler', 'pid_t pid, int policy, const struct sched_param *param'),
    157: ('sched_getscheduler', 'pid_t pid'),
    158: ('sched_yield', 'void'),
    159: ('sched_get_priority_max', 'int policy'),
    160: ('sched_get_priority_min', 'int policy'),
    162: ('nanosleep', 'const struct timespec *req, struct timespec *rem'),
    168: ('poll', 'struct pollfd *fds, nfds_t nfds, int timeout'),
    172: ('prctl', 'int option, unsigned long arg2, unsigned long arg3, unsigned long arg4, unsigned long arg5'),
    174: ('rt_sigaction', 'int signum, const struct sigaction *act, struct sigaction *oldact, size_t sigsetsize'),
    175: ('rt_sigprocmask', 'int how, const sigset_t *set, sigset_t *oldset, size_t sigsetsize'),
    186: ('sigaltstack', 'const stack_t *ss, stack_t *old_ss'),
    192: ('mmap2', 'void *addr, size_t length, int prot, int flags, int fd, off_t pgoffset'),
    195: ('stat64', 'const char *pathname, struct stat64 *statbuf'),
    196: ('lstat64', 'const char *pathname, struct stat64 *statbuf'),
    197: ('fstat64', 'int fd, struct stat64 *statbuf'),
    199: ('getuid32', 'void'),
    200: ('getgid32', 'void'),
    201: ('geteuid32', 'void'),
    202: ('getegid32', 'void'),
    220: ('madvise', 'void *addr, size_t length, int advice'),
    221: ('fcntl64', 'int fd, int cmd, unsigned long arg'),
    224: ('gettid', 'void'),
    238: ('tkill', 'int tid, int sig'),
    240: ('futex', 'int *uaddr, int futex_op, int val, const struct timespec *timeout, int *uaddr2, int val3'),
    241: ('sched_setaffinity', 'pid_t pid, size_t cpusetsize, const unsigned long *mask'),
    242: ('sched_getaffinity', 'pid_t pid, size_t cpusetsize, unsigned long *mask'),
    248: ('exit_group', 'int status'),
    250: ('epoll_create', 'int size'),
    251: ('epoll_ctl', 'int epfd, int op, int fd, struct epoll_event *event'),
    252: ('epoll_wait', 'int epfd, struct epoll_event *events, int maxevents, int timeout'),
    256: ('set_tid_address', 'int *tidptr'),
    257: ('timer_create', 'clockid_t clockid, struct sigevent *sevp, timer_t *timerid'),
    263: ('clock_gettime', 'clockid_t clk_id, struct timespec *tp'),
    264: ('clock_getres', 'clockid_t clk_id, struct timespec *res'),
    265: ('clock_nanosleep', 'clockid_t clockid, int flags, const struct timespec *request, struct timespec *remain'),
    268: ('tgkill', 'int tgid, int tid, int sig'),
    281: ('socket', 'int domain, int type, int protocol'),
    282: ('bind', 'int sockfd, const struct sockaddr *addr, socklen_t addrlen'),
    283: ('connect', 'int sockfd, const struct sockaddr *addr, socklen_t addrlen'),
    284: ('listen', 'int sockfd, int backlog'),
    285: ('accept', 'int sockfd, struct sockaddr *addr, socklen_t *addrlen'),
    290: ('sendto', 'int sockfd, const void *buf, size_t len, int flags, const struct sockaddr *dest_addr, socklen_t addrlen'),
    292: ('recvfrom', 'int sockfd, void *buf, size_t len, int flags, struct sockaddr *src_addr, socklen_t *addrlen'),
    322: ('openat', 'int dirfd, const char *pathname, int flags, mode_t mode'),
    338: ('set_robust_list', 'struct robust_list_head *head, size_t len'),
    339: ('get_robust_list', 'int pid, struct robust_list_head **head_ptr, size_t *len_ptr'),
    356: ('eventfd2', 'unsigned int initval, int flags'),
    359: ('pipe2', 'int pipefd[2], int flags'),
    0xf0005: ('ARM_set_tls', 'void *tls'),
}


def decode_ioctl_cmd(cmd):
    """Decode standard 32-bit Linux _IOC command into direction, type, nr, and size."""
    direction = (cmd >> 30) & 0x3
    size = (cmd >> 16) & 0x3fff
    ioc_type = (cmd >> 8) & 0xff
    nr = cmd & 0xff
    dir_names = {0: '_IO', 1: '_IOW', 2: '_IOR', 3: '_IOWR'}
    type_char = chr(ioc_type) if 32 <= ioc_type <= 126 else f'0x{ioc_type:02x}'
    return {
        'raw': f'0x{cmd:08x}',
        'macro': dir_names[direction],
        'type_byte': f'0x{ioc_type:02x}',
        'type_char': type_char,
        'nr': nr,
        'size': size,
        'formatted': f"{dir_names[direction]}('{type_char}', 0x{nr:02x}, {size})",
    }


class BoundaryAnalyzer:
    """Resolves emulator stop boundaries against ELF symbols and camera ground truth."""

    def __init__(self, project_root=PROJECT_ROOT, hw_dump_path=None):
        self.project_root = Path(project_root)
        self.hw_dump_path = Path(hw_dump_path or (self.project_root / 'reports/a6400_hw_dump.txt'))
        self.manifest_path = self.project_root / 'artifacts/inventory/guest-filesystem.json'
        self._nodes = None
        self._symbol_cache = {}

    @property
    def nodes(self):
        if self._nodes is None:
            if self.manifest_path.exists():
                data = json.loads(self.manifest_path.read_text(encoding='utf-8'))
                self._nodes = data.get('nodes', {})
            else:
                self._nodes = {}
        return self._nodes

    def _resolve_guest_file(self, guest_path):
        """Find the local extracted ELF path for a guest path like //usr/lib/libObj.so."""
        if not guest_path:
            return None
        norm = '/' + guest_path.lstrip('/')
        node = self.nodes.get(norm)
        # Follow symlinks if needed
        visited = set()
        while node and node.get('kind') == 'symlink' and norm not in visited:
            visited.add(norm)
            target = node.get('target', '')
            if target.startswith('/'):
                norm = target
            else:
                parent = str(Path(norm).parent).replace('\\', '/')
                norm = ('/' if parent == '/' else parent + '/') + target
            node = self.nodes.get(norm)
        if node and node.get('extracted_path'):
            full = self.project_root / node['extracted_path']
            if full.exists():
                return full
        return None

    def _load_elf_symbols(self, elf_path):
        key = str(elf_path)
        if key in self._symbol_cache:
            return self._symbol_cache[key]
        symbols = []
        try:
            with open(elf_path, 'rb') as f:
                elf = ELFFile(f)
                for sec_name in ('.symtab', '.dynsym'):
                    sec = elf.get_section_by_name(sec_name)
                    if not sec:
                        continue
                    for sym in sec.iter_symbols():
                        val = sym['st_value']
                        sz = sym['st_size']
                        if val > 0 and sym.name:
                            clean_val = val & ~1
                            symbols.append((clean_val, max(sz, 1), sym.name, bool(val & 1)))
        except Exception:
            pass
        symbols.sort(key=lambda x: x[0])
        self._symbol_cache[key] = symbols
        return symbols

    def resolve_address(self, report, address):
        """Map a guest virtual address to binary path, file offset, ELF symbol, and disassembly."""
        if address is None or address == 0:
            return None
        clean_addr = address & ~1
        is_thumb_ptr = bool(address & 1)

        # 1. Check application_mapping (/usr/bin/im.elf)
        app_map = report.get('application_mapping', {})
        for seg in app_map.get('segments', []):
            start = seg.get('start', 0)
            end = seg.get('end', 0)
            if start <= clean_addr < end:
                file_offset = clean_addr - app_map.get('load_bias', 0)
                return self._enrich_elf_location('/usr/bin/im.elf', clean_addr, file_offset, is_thumb_ptr)

        # 2. Check interpreter_mapping (/lib/ld-linux.so.3)
        interp_map = report.get('interpreter_mapping', {})
        for seg in interp_map.get('segments', []):
            start = seg.get('start', 0)
            end = seg.get('end', 0)
            if start <= clean_addr < end:
                file_offset = clean_addr - interp_map.get('load_bias', 0)
                return self._enrich_elf_location(interp_map.get('path', '/lib/ld-linux.so.3'), clean_addr, file_offset, is_thumb_ptr)

        # 3. Check dynamic mmap mappings
        mappings = report.get('mappings', [])
        matched_map = None
        for m in mappings:
            start = m.get('address', 0)
            length = m.get('length', 0)
            if start <= clean_addr < start + length and m.get('path'):
                matched_map = m
        if matched_map:
            guest_path = matched_map['path']
            # Find base address of this library (first mapping of the same path with offset 0)
            lib_base = matched_map['address'] - matched_map.get('offset', 0)
            for m in mappings:
                if m.get('path') == guest_path and m.get('offset', 0) == 0:
                    lib_base = m['address']
                    break
            file_offset = clean_addr - lib_base
            return self._enrich_elf_location(guest_path, clean_addr, file_offset, is_thumb_ptr)

        return {
            'address': f'0x{clean_addr:08x}',
            'guest_path': '<anonymous_or_stack>',
            'offset': None,
            'symbol': None,
            'disassembly': [],
        }

    def _enrich_elf_location(self, guest_path, clean_addr, file_offset, is_thumb):
        elf_path = self._resolve_guest_file(guest_path)
        symbol_str = None
        disasm_lines = []
        if elf_path:
            symbols = self._load_elf_symbols(elf_path)
            best_sym = None
            for sym_addr, sym_size, sym_name, sym_thumb in symbols:
                if sym_addr <= file_offset < sym_addr + max(sym_size, 0x200):
                    best_sym = (sym_addr, sym_name, sym_thumb)
                elif sym_addr > file_offset:
                    break
            if best_sym:
                sym_off = file_offset - best_sym[0]
                symbol_str = f"{best_sym[1]}+0x{sym_off:x}"
                is_thumb = is_thumb or best_sym[2]

            # Disassemble surrounding instructions
            try:
                with open(elf_path, 'rb') as f:
                    elf = ELFFile(f)
                    for sec in elf.iter_sections():
                        sh_addr = sec['sh_addr']
                        sh_size = sec['sh_size']
                        if sh_addr <= file_offset < sh_addr + sh_size and sh_size > 0:
                            sec_data = sec.data()
                            rel = file_offset - sh_addr
                            win_start = max(0, rel - 8)
                            win_end = min(len(sec_data), rel + 16)
                            mode = capstone.CS_MODE_THUMB if is_thumb else capstone.CS_MODE_ARM
                            md = capstone.Cs(capstone.CS_ARCH_ARM, mode)
                            for insn in md.disasm(sec_data[win_start:win_end], sh_addr + win_start):
                                marker = '-->' if insn.address == file_offset else '   '
                                disasm_lines.append(f"{marker} 0x{insn.address:06x}: {insn.mnemonic} {insn.op_str}")
                            break
            except Exception:
                pass

        return {
            'address': f'0x{clean_addr:08x}',
            'guest_path': guest_path,
            'local_path': str(elf_path.relative_to(self.project_root)) if elf_path else None,
            'offset': f'0x{file_offset:x}',
            'symbol': symbol_str,
            'disassembly': disasm_lines,
        }

    def search_ground_truth(self, keywords):
        """Search reports/a6400_hw_dump.txt for relevant lines matching keywords."""
        if not self.hw_dump_path.exists() or not keywords:
            return []
        lines = self.hw_dump_path.read_text(encoding='utf-8', errors='replace').splitlines()
        matches = []
        for idx, line in enumerate(lines, 1):
            for kw in keywords:
                if kw and kw.lower() in line.lower():
                    matches.append(f"L{idx}: {line.strip()}")
                    break
            if len(matches) >= 25:
                break
        return matches

    def analyze_report(self, report):
        """Produce a complete structured diagnosis of an emulator execution report."""
        status = report.get('status', 'unknown')
        boundary = report.get('boundary', {})
        instructions = report.get('instructions_executed', 0)
        syscalls_count = report.get('syscall_responses_supplied', 0)
        regs = report.get('registers', {})
        tls = report.get('tls_observation', {})
        current_tid = tls.get('current_tid') or boundary.get('guest_tid')
        threads = report.get('threads', {})
        active_thread = threads.get(str(current_tid), {}) if current_tid else {}

        pc = boundary.get('instruction_address') or boundary.get('pc') or regs.get('pc', 0)
        lr = regs.get('lr', 0)
        cpsr = regs.get('cpsr', 0)
        if bool(cpsr & 0x20):
            pc = pc | 1

        pc_info = self.resolve_address(report, pc)
        lr_info = self.resolve_address(report, lr)

        r7 = boundary.get('r7') if 'r7' in boundary else regs.get('r7')
        syscall_info = None
        if r7 is not None and r7 in ARM_SYSCALL_TABLE:
            sc_name, sc_sig = ARM_SYSCALL_TABLE[r7]
            syscall_info = {'r7': r7, 'name': sc_name, 'signature': sc_sig}
        elif r7 is not None:
            syscall_info = {'r7': r7, 'name': f'syscall_{r7}', 'signature': 'unknown'}

        # Identify keywords for ground-truth lookup
        keywords = []
        target_path = boundary.get('path') or report.get('requested_path_preview', {}).get('value')
        if target_path:
            keywords.append(target_path)
            base_name = Path(target_path).name
            if len(base_name) >= 3:
                keywords.append(base_name)
        if boundary.get('device'):
            keywords.append(boundary['device'])
        if pc_info and pc_info.get('guest_path') and 'libc' not in pc_info['guest_path']:
            keywords.append(Path(pc_info['guest_path']).stem)
        if lr_info and lr_info.get('guest_path') and 'libc' not in lr_info['guest_path']:
            keywords.append(Path(lr_info['guest_path']).stem)

        ioctl_decoded = None
        if boundary.get('cmd') is not None and isinstance(boundary.get('cmd'), int):
            ioctl_decoded = decode_ioctl_cmd(boundary['cmd'])

        gt_matches = self.search_ground_truth(keywords)
        probe_script = self._build_recommended_probe(status, boundary, target_path, syscall_info)

        return {
            'status': status,
            'instructions_executed': instructions,
            'syscalls_serviced': syscalls_count,
            'active_thread': {
                'tid': current_tid,
                'name': active_thread.get('name', 'main'),
                'state': active_thread.get('state', 'running'),
                'total_threads': len(threads),
            },
            'boundary': boundary,
            'syscall': syscall_info,
            'ioctl': ioctl_decoded,
            'pc_location': pc_info,
            'lr_caller': lr_info,
            'ground_truth_matches': gt_matches,
            'recommended_camera_probe': probe_script,
        }

    def _build_recommended_probe(self, status, boundary, target_path, syscall_info):
        """Generate a shell snippet for the camera when additional hardware telemetry is needed."""
        cmds = ['echo "=== A6400 TARGETED DIAGNOSTIC PROBE ==="']
        if target_path:
            cmds.append(f'ls -la "{target_path}" 2>&1')
            cmds.append(f'stat "{target_path}" 2>&1')
            dev_name = Path(target_path).name
            cmds.append(f'grep -i "{dev_name}" /proc/devices /proc/modules /proc/mounts 2>&1')
            cmds.append(f'find /sys -name "*{dev_name}*" 2>/dev/null')
        elif syscall_info and syscall_info['name'] in ('pipe', 'pipe2', 'eventfd2', 'socket', 'connect'):
            cmds.append('IM_PID=$(pidof im.elf 2>/dev/null)')
            cmds.append('ls -la /proc/$IM_PID/fd 2>&1')
        else:
            cmds.append('cat /proc/devices /proc/modules 2>&1')
        return '\n'.join(cmds)


def format_boundary_report(analysis):
    """Format the output of BoundaryAnalyzer.analyze_report into a readable diagnostic block."""
    lines = [
        '=' * 78,
        '=== A6400 EMULATOR BOUNDARY & GROUND-TRUTH DIAGNOSIS ===',
        '=' * 78,
        f"Status              : {analysis['status']}",
        f"Instructions        : {analysis['instructions_executed']:,}",
        f"Serviced Syscalls   : {analysis['syscalls_serviced']:,}",
    ]
    th = analysis.get('active_thread', {})
    lines.append(f"Active Thread       : TID {th.get('tid')} ({th.get('name')}) [{th.get('total_threads')} total threads]")

    sc = analysis.get('syscall')
    if sc:
        lines.append(f"Syscall (r7={sc['r7']:<3})    : sys_{sc['name']}({sc['signature']})")

    ioc = analysis.get('ioctl')
    if ioc:
        lines.append(f"Ioctl Command       : {ioc['raw']} -> {ioc['formatted']}")

    pc = analysis.get('pc_location')
    if pc:
        lines.append(f"PC Location         : {pc['address']} in {pc['guest_path']} (offset {pc['offset']}, symbol: {pc['symbol']})")
        for dline in pc.get('disassembly', []):
            lines.append(f"                      {dline}")

    lr = analysis.get('lr_caller')
    if lr:
        lines.append(f"LR Caller           : {lr['address']} in {lr['guest_path']} (offset {lr['offset']}, symbol: {lr['symbol']})")
        for dline in lr.get('disassembly', []):
            lines.append(f"                      {dline}")

    lines.append('-' * 78)
    lines.append(f"Raw Boundary        : {json.dumps(analysis.get('boundary', {}))}")

    gt = analysis.get('ground_truth_matches', [])
    lines.append('-' * 78)
    if gt:
        lines.append(f"Ground-Truth Matches in reports/a6400_hw_dump.txt ({len(gt)} hits):")
        for m in gt[:12]:
            lines.append(f"  [GT] {m}")
    else:
        lines.append("Ground-Truth Matches: None in local cache -> Use `python -m tools.camera_link probe` to query camera.")
        lines.append("Recommended Camera Probe:")
        for pline in analysis.get('recommended_camera_probe', '').splitlines():
            lines.append(f"  $ {pline}")
    lines.append('=' * 78)
    return '\n'.join(lines)


class _LoggedSyscallList(list):
    """List wrapper that invokes a callback whenever a serviced syscall event is appended."""

    def __init__(self, initial, callback):
        super().__init__(initial)
        self._callback = callback

    def append(self, item):
        super().append(item)
        self._callback(item)


class BootLogger:
    """Real-time structured boot logger for InterpreterProbe execution."""

    def __init__(self, log_interval=5_000_000, stream=sys.stdout):
        self.log_interval = log_interval
        self.stream = stream
        self.probe = None
        self.start_time = None
        self._seen_libs = set()
        self._seen_kmods = set()
        self._seen_ioctls = set()
        self._stdout_idx = 0
        self._stderr_idx = 0
        self.events = []

    def attach(self, probe):
        """Attach real-time boot logging hooks to an InterpreterProbe instance."""
        self.probe = probe
        self.start_time = time.perf_counter()
        probe.report['serviced_syscalls'] = _LoggedSyscallList(
            probe.report.get('serviced_syscalls', []),
            self._on_syscall,
        )
        if self.log_interval and self.log_interval > 0:
            probe._progress_interval = self.log_interval
            probe._on_progress = self._on_progress
        return self

    def _emit(self, tag, message, insns=None):
        if insns is None and self.probe is not None:
            insns = self.probe.instructions
        m_insns = (insns or 0) / 1_000_000.0
        line = f"[BOOT {m_insns:6.2f}M | {tag:<5}] {message}"
        self.events.append(line)
        if self.stream is not None:
            print(line, file=self.stream, flush=True)

    def _current_thread_label(self):
        if self.probe is not None and hasattr(self.probe, 'threads'):
            tid = self.probe.threads.current_tid
            t_obj = self.probe.threads.threads.get(tid)
            tname = t_obj.name if t_obj and getattr(t_obj, 'name', None) else 'im.elf'
            return tid, tname
        return 1000, 'im.elf'

    def _on_progress(self, probe):
        elapsed = time.perf_counter() - (self.start_time or time.perf_counter())
        mips = (probe.instructions / 1_000_000.0) / max(elapsed, 1e-6)
        tid, tname = self._current_thread_label()
        total_threads = len(probe.threads.threads) if hasattr(probe, 'threads') else 1
        open_fds = len(probe.filesystem.fds) if hasattr(probe, 'filesystem') else 0
        syscalls = len(probe.report.get('serviced_syscalls', []))
        self._emit(
            'STEP',
            f"{elapsed:5.1f}s ({mips:4.2f} MIPS) | syscalls={syscalls:,} | "
            f"threads={total_threads} | fds={open_fds} | active=TID {tid} ({tname})",
            insns=probe.instructions,
        )

    def _on_syscall(self, event, insns_override=None, fd_map_override=None):
        sc = event.get('syscall')
        insns = insns_override if insns_override is not None else (self.probe.instructions if self.probe else 0)
        tid, tname = self._current_thread_label()
        if 'tid' in event and event['tid']:
            tid = event['tid']

        if sc == 'open':
            ret = event.get('returned', -1)
            path = event.get('path', '')
            if isinstance(ret, int) and 0 <= ret < 0x80000000 and path:
                norm_path = '/' + path.lstrip('/')
                if norm_path.startswith('/dev/'):
                    dev_num = event.get('device_number')
                    dev_str = f" (major={dev_num[0]}, minor={dev_num[1]})" if isinstance(dev_num, list) and len(dev_num) == 2 else ""
                    self._emit('DEV', f"Opened device {norm_path}{dev_str} -> fd={ret} [TID {tid} {tname}]", insns=insns)
                elif '.so' in norm_path and norm_path not in self._seen_libs:
                    self._seen_libs.add(norm_path)
                    self._emit('LIB', f"Loaded shared library {norm_path} (fd={ret}) [TID {tid} {tname}]", insns=insns)
                elif norm_path.endswith('.ko') and norm_path not in self._seen_kmods:
                    self._seen_kmods.add(norm_path)
                    self._emit('KMOD', f"Opened kernel module {norm_path} (fd={ret}) [TID {tid} {tname}]", insns=insns)

        elif sc == 'init_module':
            path = event.get('path', '<module>')
            length = event.get('length', 0)
            ret = event.get('returned', 0)
            self._emit('KMOD', f"Authenticated & initialized {path} ({length:,} bytes) -> {ret} [TID {tid} {tname}]", insns=insns)

        elif sc == 'clone':
            child_tid = event.get('child_tid') or event.get('returned')
            total = len(self.probe.threads.threads) if (self.probe and hasattr(self.probe, 'threads')) else '?'
            self._emit('THRD', f"Spawned thread TID {child_tid} (parent=TID {tid} {tname}, total={total})", insns=insns)

        elif sc == 'prctl':
            new_name = event.get('name')
            if new_name:
                self._emit('THRD', f"Named thread TID {tid} -> \"{new_name}\"", insns=insns)

        elif sc == 'pipe':
            r_fd = event.get('read_fd')
            w_fd = event.get('write_fd')
            pid = event.get('pipe_id')
            self._emit('PIPE', f"Created pipe:[{pid}] -> read_fd={r_fd}, write_fd={w_fd} [TID {tid} {tname}]", insns=insns)

        elif sc == 'poll':
            if 'blocked_tid' in event:
                b_tid = event.get('blocked_tid')
                sw_tid = event.get('switched_to')
                fds = event.get('fds', [event.get('fd')])
                self._emit('POLL', f"Thread TID {b_tid} ({tname}) blocked on poll(fds={fds}) -> switched to TID {sw_tid}", insns=insns)

        elif sc == 'ioctl':
            fd = event.get('fd')
            cmd = event.get('cmd') or event.get('request')
            dev_path = event.get('path') or event.get('device')
            if not dev_path:
                if fd_map_override and str(fd) in fd_map_override:
                    dev_path = fd_map_override[str(fd)].get('path')
                elif self.probe and hasattr(self.probe, 'filesystem') and fd in self.probe.filesystem.fds:
                    dev_path = self.probe.filesystem.fds[fd].get('path')
            dev_label = dev_path or f"fd={fd}"
            if cmd is not None and (dev_label, cmd) not in self._seen_ioctls:
                self._seen_ioctls.add((dev_label, cmd))
                if isinstance(cmd, int):
                    decoded = decode_ioctl_cmd(cmd)['formatted']
                    cmd_str = f"0x{cmd:08x} ({decoded})"
                else:
                    cmd_str = str(cmd)
                self._emit('IOCTL', f"First {dev_label} ioctl {cmd_str} -> {event.get('returned')} [TID {tid} {tname}]", insns=insns)

        elif sc in ('write', 'writev'):
            fd = event.get('fd')
            if fd in (1, 2) and self.probe and hasattr(self.probe, 'stdio'):
                if fd == 1 and len(self.probe.stdio.stdout_log) > self._stdout_idx:
                    chunk = b''.join(self.probe.stdio.stdout_log[self._stdout_idx:]).decode('latin1', errors='replace').strip()
                    self._stdout_idx = len(self.probe.stdio.stdout_log)
                    if chunk:
                        self._emit('CON', f"stdout: {chunk}", insns=insns)
                elif fd == 2 and len(self.probe.stdio.stderr_log) > self._stderr_idx:
                    chunk = b''.join(self.probe.stdio.stderr_log[self._stderr_idx:]).decode('latin1', errors='replace').strip()
                    self._stderr_idx = len(self.probe.stdio.stderr_log)
                    if chunk:
                        self._emit('CON', f"stderr: {chunk}", insns=insns)

    @classmethod
    def replay_from_report(cls, report, stream=sys.stdout):
        """Reconstruct and print the structured boot milestone timeline from a saved report JSON."""
        logger = cls(log_interval=0, stream=stream)
        fd_map = dict(report.get('file_descriptors', {}))
        syscalls = report.get('serviced_syscalls', [])
        total_insns = report.get('instructions_executed', 0)
        n_sc = max(len(syscalls), 1)
        for idx, ev in enumerate(syscalls):
            if ev.get('syscall') == 'open' and isinstance(ev.get('returned'), int) and 0 <= ev['returned'] < 0x80000000:
                fd_map[str(ev['returned'])] = {'path': ev.get('path')}
            approx_insns = int((idx / n_sc) * total_insns)
            logger._on_syscall(ev, insns_override=approx_insns, fd_map_override=fd_map)
        stdout_text = report.get('stdout', '').strip()
        if stdout_text:
            for line in stdout_text.splitlines():
                if line.strip():
                    logger._emit('CON', f"stdout: {line.strip()}", insns=total_insns)
        return logger.events


class CameraLink:
    """Direct USB Mass Storage / Senser communication bridge to physical Sony ILCE-6400."""

    def __init__(self, project_root=PROJECT_ROOT):
        self.project_root = Path(project_root)
        pmca_dir = str(self.project_root / 'Sony-PMCA-RE')
        if pmca_dir not in sys.path:
            sys.path.insert(0, pmca_dir)

    def run_session(self, callback):
        """Connect to camera in Mass Storage / Senser mode and execute callback(cam)."""
        from pmca.commands.usb import senserShellCommand
        results = {}

        def _wrap(cam):
            results['output'] = callback(cam)

        senserShellCommand(complete=_wrap)
        return results.get('output')

    @staticmethod
    def read_file_chunked(cam, remote_path):
        """Read a file from the camera using 512-byte chunk streaming (immune to 32 KB PMCA bug)."""
        dev = cam.dev
        filename = remote_path.encode('latin1')
        filename += b'\0' * (4 - len(filename) % 4)
        header = cam.FileControlHeader.pack(cmd=cam.SONY_FILE_CONTROL_READ, filenameSize=len(filename))
        p_func = cam.SONY_PFUNC_FileControl
        data = header + filename
        p_header = dev.SenserPacketHeader.pack(
            size=len(data), pFunc=p_func, sequence=dev._sequence,
            version=0, miconType=0, offsetType=0, response=0
        )
        dev.driver.write(p_header + data)

        d = dev.driver.read(512)
        resp_header = dev.SenserPacketHeader.unpack(d[:dev.SenserPacketHeader.size])
        if resp_header.response != 1:
            dev._sequence += 1
            raise FileNotFoundError(f"Camera returned Senser response {resp_header.response} for {remote_path}")

        total_size = resp_header.size
        file_bytes = bytearray(d[dev.SenserPacketHeader.size:])
        while len(file_bytes) < total_size:
            to_read = min(total_size - len(file_bytes), 512)
            chunk = dev.driver.read(to_read)
            if not chunk:
                break
            file_bytes.extend(chunk)

        dev._sequence += 1
        return bytes(file_bytes[:total_size])

    def read_camera_file(self, remote_path, save_to=None):
        """Read a file directly from the connected camera."""
        def _op(cam):
            raw = self.read_file_chunked(cam, remote_path)
            if save_to:
                out = Path(save_to)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(raw)
            return raw

        return self.run_session(_op)

    def read_camera_memory(self, address, size, save_to=None):
        """Read physical/kernel memory from the connected camera via SONY_PFUNC_MemoryDump."""
        def _op(cam):
            buf = io.BytesIO()
            cam.readMemory(address, size, buf)
            raw = buf.getvalue()
            if save_to:
                out = Path(save_to)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(raw)
            return raw

        return self.run_session(_op)

    def read_camera_backup(self, backup_id):
        """Read a Sony NVRAM Backup ID directly from the connected camera."""
        def _op(cam):
            return cam.readBackup(backup_id)

        return self.run_session(_op)

    def stage_diagnostic_probe(self, shell_commands, remote_out='/tmp/diag_result.txt'):
        """Stage a self-cleaning diagnostic probe in /tmp/autoexec.sh on the camera."""
        script = f"""#!/bin/sh
export PATH=/usr/bin:/bin:/sbin:/usr/sbin:/tmp
OUT="{remote_out}"
(
{shell_commands}
) > "$OUT" 2>&1

# Restore clean standby autoexec.sh immediately after probe finishes
cat << 'EOF' > /tmp/autoexec.sh
#!/bin/sh
export PATH=/usr/bin:/bin:/sbin:/usr/sbin:/tmp
echo "[+] Clean standby at $(date)" > /tmp/autoexec.log
rm -f /tmp/autoexec.lock 2>/dev/null
EOF
chmod 755 /tmp/autoexec.sh
sync
rm -f /tmp/autoexec.lock 2>/dev/null
""".replace('\r\n', '\n').encode('latin1')

        def _op(cam):
            try:
                cam.deleteFile('/tmp/autoexec.lock')
            except Exception:
                pass
            try:
                cam.deleteFile(remote_out)
            except Exception:
                pass
            cam.writeFile('/tmp/autoexec.sh', script)
            cam.writeFile('/etc/ld.so.preload', b'/tmp/autoexec_hook.so\n')
            return True

        return self.run_session(_op)

    def fetch_probe_result(self, remote_out='/tmp/diag_result.txt', save_to='reports/latest_probe.txt'):
        """Fetch the output of a staged diagnostic probe and clean up the temporary file."""
        def _op(cam):
            raw = self.read_file_chunked(cam, remote_out)
            out_path = self.project_root / save_to
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(raw)
            try:
                cam.deleteFile(remote_out)
            except Exception:
                pass
            return raw

        return self.run_session(_op)


def main():
    parser = argparse.ArgumentParser(description='PC <-> Sony ILCE-6400 Communication & Boundary Diagnosis Tool')
    sub = parser.add_subparsers(dest='command', required=True)

    diag_p = sub.add_parser('diagnose', help='Analyze an emulator execution report and cross-reference camera ground truth')
    diag_p.add_argument('report', nargs='?', default='artifacts/execution/ui-boot-hdmi-100m.json',
                        help='Path to emulator report JSON')
    diag_p.add_argument('--stage-probe', action='store_true',
                        help='Automatically stage the recommended probe onto the connected camera')

    bl_p = sub.add_parser('boot-log', help='Replay structured boot milestones and diagnosis from an emulator report JSON')
    bl_p.add_argument('report', nargs='?', default='artifacts/execution/ui-boot-hdmi-100m.json',
                      help='Path to emulator report JSON')

    rf_p = sub.add_parser('read-file', help='Read a file directly from the connected camera over USB')
    rf_p.add_argument('remote_path', help='Path on camera (e.g. /tmp/autoexec.log)')
    rf_p.add_argument('--out', help='Optional local path to save the file')

    rm_p = sub.add_parser('read-mem', help='Dump memory directly from the connected camera over USB')
    rm_p.add_argument('address', type=lambda x: int(x, 0), help='Memory address (hex or dec)')
    rm_p.add_argument('size', type=lambda x: int(x, 0), help='Number of bytes to read')
    rm_p.add_argument('--out', help='Optional local path to save the dump')

    rb_p = sub.add_parser('read-backup', help='Read a Sony NVRAM Backup ID directly from the camera')
    rb_p.add_argument('backup_id', type=lambda x: int(x, 0), help='Backup ID (e.g. 0x00010000)')

    pr_p = sub.add_parser('stage-probe', help='Stage a shell diagnostic query on the camera (/tmp/autoexec.sh)')
    pr_p.add_argument('shell_cmd', help='Shell command(s) to execute on camera boot')

    fp_p = sub.add_parser('fetch-probe', help='Fetch /tmp/diag_result.txt from the camera into reports/latest_probe.txt')
    fp_p.add_argument('--remote', default='/tmp/diag_result.txt')
    fp_p.add_argument('--out', default='reports/latest_probe.txt')

    args = parser.parse_args()

    if args.command == 'diagnose':
        report_path = Path(args.report)
        if not report_path.exists():
            print(f"[-] Report file not found: {report_path}")
            sys.exit(1)
        report = json.loads(report_path.read_text(encoding='utf-8'))
        analyzer = BoundaryAnalyzer()
        analysis = analyzer.analyze_report(report)
        print(format_boundary_report(analysis))
        if args.stage_probe:
            link = CameraLink()
            print("[*] Staging recommended diagnostic probe to camera...")
            link.stage_diagnostic_probe(analysis['recommended_camera_probe'])
            print("[+] Probe staged! Turn camera OFF/ON for 5s, then run `python -m tools.camera_link fetch-probe`.")

    elif args.command == 'boot-log':
        report_path = Path(args.report)
        if not report_path.exists():
            print(f"[-] Report file not found: {report_path}")
            sys.exit(1)
        report = json.loads(report_path.read_text(encoding='utf-8'))
        BootLogger.replay_from_report(report)
        analyzer = BoundaryAnalyzer()
        print(format_boundary_report(analyzer.analyze_report(report)))

    elif args.command == 'read-file':
        link = CameraLink()
        raw = link.read_camera_file(args.remote_path, save_to=args.out)
        print(f"[+] Read {len(raw)} bytes from {args.remote_path}:")
        print(raw.decode('latin1', errors='replace'))

    elif args.command == 'read-mem':
        link = CameraLink()
        raw = link.read_camera_memory(args.address, args.size, save_to=args.out)
        print(f"[+] Read {len(raw)} bytes from memory 0x{args.address:08x}:")
        print(raw[:256].hex())

    elif args.command == 'read-backup':
        link = CameraLink()
        raw = link.read_camera_backup(args.backup_id)
        print(f"[+] Backup ID 0x{args.backup_id:08x} ({len(raw)} bytes): {raw.hex()}")

    elif args.command == 'stage-probe':
        link = CameraLink()
        link.stage_diagnostic_probe(args.shell_cmd)
        print("[+] Diagnostic probe staged on camera! Turn camera OFF/ON for 5s, then run `python -m tools.camera_link fetch-probe`.")

    elif args.command == 'fetch-probe':
        link = CameraLink()
        raw = link.fetch_probe_result(remote_out=args.remote, save_to=args.out)
        print(f"[+] Fetched probe result ({len(raw)} bytes) -> {args.out}:")
        print(raw.decode('latin1', errors='replace'))


if __name__ == '__main__':
    main()
