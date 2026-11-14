"""Verified Linux ARM EABI multithreading, clone, and futex contracts."""

import struct
from typing import Dict, List, Optional, Tuple, Callable
import unicorn.arm_const as arm

# Supported clone flags for Linux ARM NPTL (0x3d0f00)
CLONE_VM = 0x00000100
CLONE_FS = 0x00000200
CLONE_FILES = 0x00000400
CLONE_SIGHAND = 0x00000800
CLONE_THREAD = 0x00010000
CLONE_SYSVSEM = 0x00040000
CLONE_SETTLS = 0x00080000
CLONE_PARENT_SETTID = 0x00100000
CLONE_CHILD_CLEARTID = 0x00200000

EXPECTED_PTHREAD_CLONE_FLAGS = (
    CLONE_VM | CLONE_FS | CLONE_FILES | CLONE_SIGHAND |
    CLONE_THREAD | CLONE_SYSVSEM | CLONE_SETTLS |
    CLONE_PARENT_SETTID | CLONE_CHILD_CLEARTID
)

# Futex operations
FUTEX_WAIT = 0
FUTEX_WAKE = 1
FUTEX_WAKE_OP = 5
FUTEX_PRIVATE_FLAG = 128
FUTEX_CMD_MASK = 0x7f

PR_SET_NAME = 15

REGISTER_LIST = (
    arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2, arm.UC_ARM_REG_R3,
    arm.UC_ARM_REG_R4, arm.UC_ARM_REG_R5, arm.UC_ARM_REG_R6, arm.UC_ARM_REG_R7,
    arm.UC_ARM_REG_R8, arm.UC_ARM_REG_R9, arm.UC_ARM_REG_R10, arm.UC_ARM_REG_R11,
    arm.UC_ARM_REG_R12, arm.UC_ARM_REG_SP, arm.UC_ARM_REG_LR, arm.UC_ARM_REG_PC,
    arm.UC_ARM_REG_CPSR
)


class GuestThread:
    """Represents an active or terminated thread in the guest process."""

    def __init__(self, tid: int, name: str, state: str = 'running',
                 child_stack: Optional[int] = None, tls_val: Optional[int] = None,
                 parent_tidptr: Optional[int] = None, child_tidptr: Optional[int] = None,
                 fn: Optional[int] = None, arg: Optional[int] = None):
        self.tid = tid
        self.name = name
        self.state = state  # 'running', 'runnable', 'blocked_futex', 'terminated'
        self.child_stack = child_stack
        self.tls_val = tls_val
        self.parent_tidptr = parent_tidptr
        self.child_tidptr = child_tidptr
        self.fn = fn
        self.arg = arg
        self.regs: Dict[int, int] = {}
        self.blocked_uaddr: Optional[int] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            'tid': self.tid,
            'name': self.name,
            'state': self.state,
            'fn': hex(self.fn) if self.fn is not None else None,
            'arg': hex(self.arg) if self.arg is not None else None,
            'tls_val': hex(self.tls_val) if self.tls_val is not None else None,
            'child_stack': hex(self.child_stack) if self.child_stack is not None else None
        }


class GuestThreads:
    """Manages thread lifecycle, cooperative scheduling, and synchronization primitives."""

    def __getstate__(self):
        # timer_fire is a bound probe method (holds Unicorn ctypes); _sync_timer_objects re-sets it every step.
        state = self.__dict__.copy()
        state.pop('timer_fire', None)
        return state

    def __init__(self, initial_tid: int = 1000):
        self.process_id = initial_tid  # All supported clones include CLONE_THREAD.
        self.current_tid = initial_tid
        self.next_tid = initial_tid + 1
        self.threads: Dict[int, GuestThread] = {
            initial_tid: GuestThread(tid=initial_tid, name='main', state='running')
        }
        self.futex_waiters: Dict[int, List[int]] = {}
        self.uipc_waiters: Dict[int, List[int]] = {}
        self.fd_waiters: Dict[int, List[int]] = {}
        self.timer_waiters: Dict[int, int] = {}  # tid -> absolute guest-time deadline (us)
        self.thread_log: List[Dict[str, object]] = []
        # Optional observer for a guest-derived per-thread kernel task record.
        self.on_clone = None

    def save_context(self, uc) -> None:
        """Saves current CPU registers into the active thread descriptor."""
        if self.current_tid in self.threads:
            regs = {r: uc.reg_read(r) for r in REGISTER_LIST}
            self.threads[self.current_tid].regs = regs

    def restore_context(self, uc, target_tid: int, kuser=None) -> None:
        """Restores CPU registers and TLS for target thread."""
        thread = self.threads[target_tid]
        if arm.UC_ARM_REG_CPSR in thread.regs:
            # Select the target register bank before writing its SP/LR.
            uc.reg_write(arm.UC_ARM_REG_CPSR, thread.regs[arm.UC_ARM_REG_CPSR])
        for reg, val in thread.regs.items():
            uc.reg_write(reg, val)
        if thread.tls_val is not None:
            if kuser is not None:
                kuser.set_tls(thread.tls_val)
            else:
                # Original NPTL reads TPIDRURO directly with MRC, not only
                # the kuser software slot. Both belong to the switched thread.
                uc.reg_write(arm.UC_ARM_REG_C13_C0_3, thread.tls_val)
                uc.mem_write(0xffff0ff0, struct.pack('<I', thread.tls_val))
        self.current_tid = target_tid
        thread.state = 'running'

    def handle_clone(self, flags: int, child_stack: int, parent_tidptr: int,
                     tls_val: int, child_tidptr: int,
                     mem_reader: Callable[[int, int], bytes],
                     mem_writer: Callable[[int, bytes], None],
                     *, syscall_registers: Dict[int, int]) -> Tuple[int, Dict[str, object]]:
        """Handles sys_clone (syscall 120).

        Copy the syscall-return context, replacing only child r0 and sp.
        Original libc instructions own function dispatch and the exit path.
        """
        if flags != EXPECTED_PTHREAD_CLONE_FLAGS:
            raise ValueError(f"Unsupported clone flags: {hex(flags)} (expected {hex(EXPECTED_PTHREAD_CLONE_FLAGS)})")
        if any(register not in syscall_registers for register in REGISTER_LIST):
            raise ValueError('Incomplete clone syscall-return context')

        tid = self.next_tid
        self.next_tid += 1

        # Write child TID to parent_tidptr if CLONE_PARENT_SETTID
        if flags & CLONE_PARENT_SETTID:
            mem_writer(parent_tidptr, struct.pack('<I', tid))

        child_regs = dict(syscall_registers)
        child_regs[arm.UC_ARM_REG_R0] = 0
        child_regs[arm.UC_ARM_REG_SP] = child_stack

        new_thread = GuestThread(
            tid=tid,
            name=f'thread_{tid}',
            state='runnable',
            child_stack=child_stack,
            tls_val=tls_val,
            parent_tidptr=parent_tidptr,
            child_tidptr=child_tidptr
        )
        new_thread.regs = child_regs
        self.threads[tid] = new_thread
        if self.on_clone is not None:
            # The child TID is guest-derived by the emulated clone; a kernel
            # task observation table may register the matching record here.
            self.on_clone(tid, self.process_id)

        event = {
            'syscall': 'clone',
            'r7': 120,
            'flags': flags,
            'child_tid': tid,
            'child_stack': child_stack,
            'tls_val': tls_val,
            'parent_tidptr': parent_tidptr,
            'child_tidptr': child_tidptr,
            'child_resume_pc': child_regs[arm.UC_ARM_REG_PC],
            'child_cpsr': child_regs[arm.UC_ARM_REG_CPSR],
            'returned': tid
        }
        self.thread_log.append(event)
        return tid, event

    def get_next_runnable_tid(self) -> Optional[int]:
        """Finds the next runnable thread in cyclic round-robin order."""
        all_tids = list(self.threads.keys())
        if self.current_tid not in all_tids:
            return None
        idx = all_tids.index(self.current_tid)
        candidates = all_tids[idx + 1:] + all_tids[:idx]
        for tid in candidates:
            if self.threads[tid].state == 'runnable':
                return tid
        waiters = getattr(self, 'timer_waiters', None)
        if waiters:
            # Idle CPU: jump the guest clock to the earliest timer deadline (applied by the probe at its next syscall).
            deadline = min(waiters.values())
            self.clock_floor = max(getattr(self, 'clock_floor', 0), deadline)
            self.wake_due(deadline)
            for tid in candidates + [self.current_tid]:
                if self.threads[tid].state == 'runnable':
                    return tid
        return None

    def wake_due(self, now: int) -> List[int]:
        """Makes timer waiters whose deadline has passed runnable (--uipc-timer-service)."""
        due = [tid for tid, deadline in getattr(self, 'timer_waiters', {}).items() if deadline <= now]
        for tid in due:
            self.timer_waiters.pop(tid, None)
            if tid < 0 and getattr(self, 'timer_fire', None):  # pseudo-waiter -key: an armed osal timer object expired
                self.timer_fire(-tid)
            if tid in self.threads and self.threads[tid].state == 'blocked_uipc':  # rcv_msg_tmo expiry
                queue = self.threads[tid].blocked_uaddr
                if tid in self.uipc_waiters.get(queue, []):
                    self.uipc_waiters[queue].remove(tid)
                self.threads[tid].blocked_uaddr = None
                self.threads[tid].state = 'runnable'
            if tid in self.threads and self.threads[tid].state == 'blocked_poll':  # finite poll timeout expiry
                for waiting in self.fd_waiters.values():
                    if tid in waiting:
                        waiting.remove(tid)
                self.threads[tid].blocked_uaddr = None
                self.threads[tid].poll_expired = True  # the re-executed svc returns 0 instead of blocking again
                self.threads[tid].state = 'runnable'
            if tid in self.threads and self.threads[tid].state == 'blocked_timer':
                self.threads[tid].state = 'runnable'
        return due

    def handle_sched_yield(self) -> Tuple[Optional[int], Dict[str, object]]:
        """Handles sys_sched_yield (syscall 158).

        Yields execution to the next runnable thread if one exists.
        Returns (next_tid, event).
        """
        next_tid = self.get_next_runnable_tid()
        if next_tid is not None:
            self.threads[self.current_tid].state = 'runnable'
        event = {
            'syscall': 'sched_yield',
            'r7': 158,
            'yielded_tid': self.current_tid,
            'switched_to': next_tid,
            'returned': 0
        }
        return next_tid, event

    def handle_gettid(self) -> Tuple[int, Dict[str, object]]:
        """Handles sys_gettid (syscall 224)."""
        event = {'syscall': 'gettid', 'r7': 224, 'returned': self.current_tid}
        return self.current_tid, event

    def handle_prctl(self, option: int, arg2: int,
                     mem_reader: Callable[[int, int], bytes]) -> Tuple[int, Dict[str, object]]:
        """Handles sys_prctl (syscall 172). Supports PR_SET_NAME (15)."""
        name = ""
        if option == PR_SET_NAME:
            raw = mem_reader(arg2, 16)
            name = raw.split(b'\x00')[0].decode('latin1', errors='replace')
            if self.current_tid in self.threads:
                self.threads[self.current_tid].name = name
        event = {'syscall': 'prctl', 'r7': 172, 'option': option, 'name': name, 'returned': 0}
        return 0, event

    def handle_sched_getparam(self, pid: int, param: int,
                              mem_writer: Callable[[int, bytes], None]) -> Tuple[int, Dict[str, object]]:
        """Handles sys_sched_getparam (syscall 155). Writes int32 priority (0) to param."""
        if param:
            mem_writer(param, struct.pack('<I', 0))
        event = {'syscall': 'sched_getparam', 'r7': 155, 'pid': pid, 'param': param, 'returned': 0}
        return 0, event

    def handle_sched_getscheduler(self, pid: int) -> Tuple[int, Dict[str, object]]:
        """Handles sys_sched_getscheduler (syscall 157). Returns SCHED_OTHER (0)."""
        event = {'syscall': 'sched_getscheduler', 'r7': 157, 'pid': pid, 'returned': 0}
        return 0, event

    def handle_sched_setscheduler(self, pid: int, policy: int, param: int) -> Tuple[int, Dict[str, object]]:
        """Handles sys_sched_setscheduler (syscall 156)."""
        event = {'syscall': 'sched_setscheduler', 'r7': 156, 'pid': pid, 'policy': policy, 'param': param, 'returned': 0}
        return 0, event

    def handle_sched_setaffinity(self, pid: int, len_: int, mask: int) -> Tuple[int, Dict[str, object]]:
        """Handles sys_sched_setaffinity (syscall 242)."""
        event = {'syscall': 'sched_setaffinity', 'r7': 242, 'pid': pid, 'len': len_, 'returned': 0}
        return 0, event

    def handle_futex_wait(self, uaddr: int, val: int,
                          mem_reader: Callable[[int, int], bytes]) -> Tuple[Optional[int], Optional[int], Dict[str, object]]:
        """Handles sys_futex FUTEX_WAIT.

        Returns (ret_val, next_runnable_tid, event).
        If *uaddr != val, returns (-EAGAIN, None, event).
        If *uaddr == val, blocks current thread and returns (None, next_tid, event).
        """
        curr = struct.unpack('<I', mem_reader(uaddr, 4))[0]
        if curr != val:
            ret = 0xfffffff5  # ARM Linux -EAGAIN / -EWOULDBLOCK (11), not -EINVAL (22)
            event = {'syscall': 'futex', 'cmd': 'FUTEX_WAIT', 'uaddr': uaddr, 'val': val, 'returned': ret}
            return ret, None, event

        # Block current thread
        curr_thread = self.threads[self.current_tid]
        curr_thread.state = 'blocked_futex'
        curr_thread.blocked_uaddr = uaddr
        self.futex_waiters.setdefault(uaddr, []).append(self.current_tid)

        next_tid = self.get_next_runnable_tid()

        event = {
            'syscall': 'futex',
            'cmd': 'FUTEX_WAIT',
            'uaddr': uaddr,
            'val': val,
            'blocked_tid': self.current_tid,
            'switched_to': next_tid
        }
        return None, next_tid, event

    def handle_futex_wake(self, uaddr: int, val: int) -> Tuple[int, Dict[str, object]]:
        """Handles sys_futex FUTEX_WAKE. Unblocks up to val threads."""
        waiters = self.futex_waiters.get(uaddr, [])
        to_wake = waiters[:val]
        self.futex_waiters[uaddr] = waiters[val:]

        woken = 0
        for w_tid in to_wake:
            if w_tid in self.threads:
                self.threads[w_tid].state = 'runnable'
                self.threads[w_tid].blocked_uaddr = None
                # Syscall return in woken thread is 0 (success)
                self.threads[w_tid].regs[arm.UC_ARM_REG_R0] = 0
                woken += 1

        event = {'syscall': 'futex', 'cmd': 'FUTEX_WAKE', 'uaddr': uaddr, 'woken': woken, 'returned': woken}
        return woken, event

    def handle_futex_wake_op(self, uaddr: int, val: int, val2: int, uaddr2: int, val3: int,
                             mem_read=None, mem_write=None):
        woken, _ = self.handle_futex_wake(uaddr, val)

        op = (val3 >> 28) & 0xf
        cmp_op = (val3 >> 24) & 0xf
        oparg = (val3 >> 12) & 0xfff
        cmparg = val3 & 0xfff

        woken2 = 0
        if mem_read is not None and mem_write is not None and uaddr2:
            try:
                oldval = struct.unpack('<i', mem_read(uaddr2, 4))[0]
                newval = oldval
                if op == 0:  # FUTEX_OP_SET
                    newval = oparg
                elif op == 1:  # FUTEX_OP_ADD
                    newval = (oldval + oparg) & 0xffffffff
                elif op == 2:  # FUTEX_OP_OR
                    newval = oldval | oparg
                elif op == 3:  # FUTEX_OP_ANDN
                    newval = oldval & ~oparg
                elif op == 4:  # FUTEX_OP_XOR
                    newval = oldval ^ oparg

                if newval != oldval:
                    mem_write(uaddr2, struct.pack('<i', newval))

                cond = False
                if cmp_op == 0:  # FUTEX_OP_CMP_EQ
                    cond = (oldval == cmparg)
                elif cmp_op == 1:  # FUTEX_OP_CMP_NE
                    cond = (oldval != cmparg)
                elif cmp_op == 2:  # FUTEX_OP_CMP_LT
                    cond = (oldval < cmparg)
                elif cmp_op == 3:  # FUTEX_OP_CMP_LE
                    cond = (oldval <= cmparg)
                elif cmp_op == 4:  # FUTEX_OP_CMP_GT
                    cond = (oldval > cmparg)
                elif cmp_op == 5:  # FUTEX_OP_CMP_GE
                    cond = (oldval >= cmparg)

                if cond and val2 > 0:
                    w2, _ = self.handle_futex_wake(uaddr2, val2)
                    woken2 = w2
            except Exception:
                pass

        total_woken = woken + woken2
        event = {
            'syscall': 'futex',
            'cmd': 'FUTEX_WAKE_OP',
            'uaddr': uaddr,
            'val': val,
            'val2': val2,
            'uaddr2': uaddr2,
            'val3': val3,
            'woken': total_woken,
            'returned': total_woken,
        }
        return total_woken, event

    def handle_uipc_wait(self, queue: int, resume_pc: int, deadline: Optional[int] = None) -> Tuple[Optional[int], Dict[str, object]]:
        """Handles blocking wait on an empty UIPC queue (ioctl 0x80000007); a deadline also arms a timer wake."""
        curr_thread = self.threads[self.current_tid]
        curr_thread.state = 'blocked_uipc'
        curr_thread.blocked_uaddr = queue
        self.uipc_waiters.setdefault(queue, []).append(self.current_tid)
        if deadline is not None:
            self.__dict__.setdefault('timer_waiters', {})[self.current_tid] = deadline

        next_tid = self.get_next_runnable_tid()

        event = {
            'syscall': 'ioctl',
            'cmd': 'UIPC_CMD_RCV_MSG_TMO',
            'queue': queue,
            'blocked_tid': self.current_tid,
            'switched_to': next_tid
        }
        return next_tid, event

    def handle_fd_wait(self, fd: int, op: str, resume_pc: int, extra_fds: Optional[List[int]] = None, deadline: Optional[int] = None) -> Tuple[Optional[int], Dict[str, object]]:
        """Handles blocking wait on one or more file descriptors (e.g. read or poll); a deadline arms a timeout wake."""
        curr_thread = self.threads[self.current_tid]
        if deadline is not None:
            self.__dict__.setdefault('timer_waiters', {})[self.current_tid] = deadline
        curr_thread.state = f'blocked_{op}'
        curr_thread.blocked_uaddr = fd
        all_fds = [fd] + [f for f in (extra_fds or []) if f != fd]
        for wait_fd in all_fds:
            waiters = self.fd_waiters.setdefault(wait_fd, [])
            if self.current_tid not in waiters:
                waiters.append(self.current_tid)

        next_tid = self.get_next_runnable_tid()

        event = {
            'syscall': op,
            'fd': fd,
            'fds': all_fds,
            'blocked_tid': self.current_tid,
            'switched_to': next_tid
        }
        return next_tid, event

    def handle_fd_wake(self, fd: int) -> List[int]:
        """Unblocks threads waiting on target file descriptor."""
        waiters = self.fd_waiters.pop(fd, [])
        woken = []
        for tid in waiters:
            if tid in self.threads and self.threads[tid].state.startswith('blocked_'):
                if self.threads[tid].state == 'blocked_poll':  # data beat the poll deadline
                    self.__dict__.setdefault('timer_waiters', {}).pop(tid, None)
                    for waiting in self.fd_waiters.values():
                        if tid in waiting:
                            waiting.remove(tid)
                self.threads[tid].state = 'runnable'
                self.threads[tid].blocked_uaddr = None
                woken.append(tid)
        return woken

    def handle_uipc_wake(self, queue: int) -> List[int]:
        """Unblocks threads waiting on target UIPC queue."""
        waiters = self.uipc_waiters.pop(queue, [])
        woken = []
        for tid in waiters:
            self.__dict__.setdefault('timer_waiters', {}).pop(tid, None)  # a message beat the rcv_msg_tmo deadline
            if tid in self.threads:
                self.threads[tid].state = 'runnable'
                self.threads[tid].blocked_uaddr = None
                woken.append(tid)
        return woken

    def handle_exit(self, status: int,
                    mem_writer: Callable[[int, bytes], None]) -> Tuple[Optional[int], Dict[str, object]]:
        """Handles sys_exit (syscall 1).

        Terminates the current thread. Clears child_tidptr if registered.
        Returns (next_runnable_tid, event).
        """
        curr = self.threads[self.current_tid]
        curr.state = 'terminated'

        if curr.child_tidptr:
            mem_writer(curr.child_tidptr, struct.pack('<I', 0))
            # Wake any waiters on child_tidptr (pthread_join)
            for w_tid in self.futex_waiters.get(curr.child_tidptr, []):
                if w_tid in self.threads:
                    self.threads[w_tid].state = 'runnable'
                    self.threads[w_tid].blocked_uaddr = None
                    self.threads[w_tid].regs[arm.UC_ARM_REG_R0] = 0
            self.futex_waiters.pop(curr.child_tidptr, None)

        next_tid = self.get_next_runnable_tid()

        event = {
            'syscall': 'exit',
            'r7': 1,
            'tid': self.current_tid,
            'status': status,
            'switched_to': next_tid
        }
        return next_tid, event
