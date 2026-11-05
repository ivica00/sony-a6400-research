"""Linux System V IPC semaphore contract (sys_semget, sys_semctl, sys_semop, sys_semtimedop)."""

import struct


# IPC and semctl constants
IPC_CREAT = 0o1000
IPC_EXCL = 0o2000
IPC_NOWAIT = 0o4000
SEM_UNDO = 0o10000
IPC_64 = 0x0100

IPC_RMID = 0
IPC_SET = 1
IPC_STAT = 2
IPC_INFO = 3
SEM_STAT = 4
SEM_INFO = 5
GETPID = 11
GETVAL = 12
GETALL = 13
GETNCNT = 14
GETZCNT = 15
SETVAL = 16
SETALL = 17


class SemaphoreSet:
    """Represents a System V semaphore set created by semget."""

    def __init__(self, semid: int, key: int, nsems: int, semflg: int):
        self.semid = semid
        self.key = key
        self.nsems = nsems
        self.semflg = semflg
        self.values = [0] * nsems
        self.last_pid = 1000  # Default caller TID/PID


class GuestSem:
    """Manages System V IPC semaphores in guest memory space."""

    def __init__(self):
        self.sets_by_id = {}
        self.sets_by_key = {}
        self.next_semid = 0

    def semget(self, key: int, nsems: int, semflg: int) -> int:
        """Implements sys_semget (r7 = 299)."""
        key &= 0xffffffff
        if nsems < 0 or nsems > 32000:
            return -22  # -EINVAL

        # IPC_PRIVATE (0) always creates a new semaphore set
        if key == 0:
            if nsems == 0:
                return -22  # -EINVAL
            semid = self.next_semid
            self.next_semid += 1
            s = SemaphoreSet(semid, key, nsems, semflg)
            self.sets_by_id[semid] = s
            return semid

        # Keyed semaphore set lookup
        if key in self.sets_by_key:
            if (semflg & IPC_CREAT) and (semflg & IPC_EXCL):
                return -17  # -EEXIST
            existing = self.sets_by_key[key]
            if nsems > 0 and nsems > existing.nsems:
                return -22  # -EINVAL
            return existing.semid

        # Not found
        if not (semflg & IPC_CREAT):
            return -2  # -ENOENT

        if nsems <= 0:
            return -22  # -EINVAL

        semid = self.next_semid
        self.next_semid += 1
        s = SemaphoreSet(semid, key, nsems, semflg)
        self.sets_by_id[semid] = s
        self.sets_by_key[key] = s
        return semid

    def semctl(self, semid: int, semnum: int, cmd: int, arg: int,
               memory_reader=None, memory_writer=None) -> int:
        """Implements sys_semctl (r7 = 300)."""
        if semid not in self.sets_by_id:
            return -22  # -EINVAL

        s = self.sets_by_id[semid]
        cmd_raw = cmd & ~IPC_64

        if cmd_raw == IPC_RMID:
            del self.sets_by_id[semid]
            if s.key in self.sets_by_key and self.sets_by_key[s.key] is s:
                del self.sets_by_key[s.key]
            return 0

        elif cmd_raw == IPC_SET:
            return 0

        elif cmd_raw == IPC_STAT:
            if memory_writer and arg != 0:
                # Fill dummy struct semid64_ds (84 bytes)
                raw = bytes(84)
                memory_writer(arg, raw)
            return 0

        elif cmd_raw == GETVAL:
            if semnum < 0 or semnum >= s.nsems:
                return -22  # -EINVAL
            return s.values[semnum]

        elif cmd_raw == SETVAL:
            if semnum < 0 or semnum >= s.nsems:
                return -22  # -EINVAL
            val = arg & 0xffff
            s.values[semnum] = val
            return 0

        elif cmd_raw == GETALL:
            if not memory_writer or arg == 0:
                return -14  # -EFAULT
            raw = struct.pack(f'<{s.nsems}H', *s.values)
            memory_writer(arg, raw)
            return 0

        elif cmd_raw == SETALL:
            if not memory_reader or arg == 0:
                return -14  # -EFAULT
            raw = memory_reader(arg, s.nsems * 2)
            values = struct.unpack(f'<{s.nsems}H', raw)
            s.values = list(values)
            return 0

        elif cmd_raw == GETPID:
            return s.last_pid

        elif cmd_raw in (GETNCNT, GETZCNT):
            return 0

        return -22  # -EINVAL

    def semtimedop(self, semid: int, tsops_ptr: int, nsops: int, timeout_ptr: int = 0,
                   memory_reader=None, memory_writer=None) -> int:
        """Implements sys_semop (r7 = 298) and sys_semtimedop (r7 = 301)."""
        if semid not in self.sets_by_id:
            return -22  # -EINVAL

        if nsops <= 0 or nsops > 32:
            return -22  # -EINVAL

        if not memory_reader or tsops_ptr == 0:
            return -14  # -EFAULT

        s = self.sets_by_id[semid]

        # Read sembuf structs: struct sembuf { uint16 sem_num; int16 sem_op; int16 sem_flg; } (6 bytes each)
        raw_ops = memory_reader(tsops_ptr, nsops * 6)
        ops = []
        for i in range(nsops):
            sem_num, sem_op, sem_flg = struct.unpack_from('<Hhh', raw_ops, i * 6)
            if sem_num >= s.nsems:
                return -27  # -EFBIG
            ops.append((sem_num, sem_op, sem_flg))

        # Atomic check: verify all ops can proceed
        temp_values = list(s.values)
        for sem_num, sem_op, sem_flg in ops:
            if sem_op < 0:
                needed = -sem_op
                if temp_values[sem_num] < needed:
                    # In our execution model, if non-blocking return EAGAIN;
                    # if timeout is 0 (or uncontended), succeed with remaining or return 0
                    if sem_flg & IPC_NOWAIT:
                        return -11  # -EAGAIN
                    # For non-contended single-process execution, allow or clamp to 0
                    temp_values[sem_num] = max(0, temp_values[sem_num] - needed)
                else:
                    temp_values[sem_num] -= needed
            elif sem_op > 0:
                temp_values[sem_num] += sem_op
            else:  # sem_op == 0 (wait for zero)
                if temp_values[sem_num] != 0:
                    if sem_flg & IPC_NOWAIT:
                        return -11  # -EAGAIN

        # Commit operations
        s.values = temp_values
        return 0

    def semop(self, semid: int, tsops_ptr: int, nsops: int,
              memory_reader=None, memory_writer=None) -> int:
        return self.semtimedop(semid, tsops_ptr, nsops, 0, memory_reader, memory_writer)
