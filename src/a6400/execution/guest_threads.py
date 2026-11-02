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

    def __init__(self, initial_tid: int = 1000):
        self.process_id = initial_tid  # All supported clones include CLONE_THREAD.
        self.current_tid = initial_tid
        self.next_tid = initial_tid + 1
        self.threads: Dict[int, GuestThread] = {
            initial_tid: GuestThread(tid=initial_tid, name='main', state='running')
        }
        self.futex_waiters: Dict[int, List[int]] = {}
        self.uipc_waiters: Dict[int, List[int]] = {}
        self.thread_log: List[Dict[str, object]] = []

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

        runnable = [t for t in self.threads.values() if t.state == 'runnable']
        next_tid = runnable[0].tid if runnable else None

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

    def handle_uipc_wait(self, queue: int, resume_pc: int) -> Tuple[Optional[int], Dict[str, object]]:
        """Handles blocking wait on an empty UIPC queue (ioctl 0x80000007)."""
        curr_thread = self.threads[self.current_tid]
        curr_thread.state = 'blocked_uipc'
        curr_thread.blocked_uaddr = queue
        self.uipc_waiters.setdefault(queue, []).append(self.current_tid)

        runnable = [t for t in self.threads.values() if t.state == 'runnable']
        next_tid = runnable[0].tid if runnable else None

        event = {
            'syscall': 'ioctl',
            'cmd': 'UIPC_CMD_RCV_MSG_TMO',
            'queue': queue,
            'blocked_tid': self.current_tid,
            'switched_to': next_tid
        }
        return next_tid, event

    def handle_uipc_wake(self, queue: int) -> List[int]:
        """Unblocks threads waiting on target UIPC queue."""
        waiters = self.uipc_waiters.pop(queue, [])
        woken = []
        for tid in waiters:
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

        runnable = [t for t in self.threads.values() if t.state == 'runnable']
        next_tid = runnable[0].tid if runnable else None

        event = {
            'syscall': 'exit',
            'r7': 1,
            'tid': self.current_tid,
            'status': status,
            'switched_to': next_tid
        }
        return next_tid, event
