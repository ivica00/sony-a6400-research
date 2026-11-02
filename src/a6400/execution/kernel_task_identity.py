"""Observed Sony kernel task ABI fields; identity checks grant no driver success.

The caller supplies a bounded, provenance-checked virtual memory reader. These
offsets are evidenced by original GLES and kernel instructions in E0064/E0065.
This module does not create a task or initialize an address space.
"""
from dataclasses import dataclass
import struct


class UnsupportedKernelBinding(RuntimeError):
    def __init__(self, reason, **details):
        self.details = {'reason': reason, **details}
        super().__init__(reason)


@dataclass(frozen=True)
class KernelTaskObservation:
    thread_info: int
    task: int
    pid: int
    tgid: int
    address_limit: int
    cpu: int

    @classmethod
    def read(cls, memory_reader, thread_info):
        if not 0 <= thread_info <= 0xffffe000 or thread_info % 8192:
            raise UnsupportedKernelBinding('thread_info_alignment_or_range', thread_info=thread_info)
        header = memory_reader(thread_info, 24)
        if len(header) != 24:
            raise UnsupportedKernelBinding('thread_info_bytes_not_supplied')
        _, _, limit, task, _, cpu = struct.unpack('<6I', header)
        if not task or task % 4 or task > 0xfffffef4:
            raise UnsupportedKernelBinding('task_pointer_invalid', task=task)
        record = memory_reader(task, 0x10c)
        if len(record) != 0x10c:
            raise UnsupportedKernelBinding('task_bytes_not_supplied')
        if struct.unpack_from('<I', record, 8)[0] != thread_info:
            raise UnsupportedKernelBinding('task_thread_info_backlink_mismatch', task=task)
        pid, tgid = struct.unpack_from('<2I', record, 0x104)
        return cls(thread_info, task, pid, tgid, limit, cpu)

    def mismatches(self, *, guest_pid, guest_tgid, user_ranges=()):
        failures = []
        if self.address_limit == 0:
            failures.append({'reason': 'kernel_task_has_no_supported_user_limit'})
        if self.pid != guest_pid:
            failures.append({'reason': 'pid_mismatch', 'guest': guest_pid, 'kernel': self.pid})
        if self.tgid != guest_tgid:
            failures.append({'reason': 'tgid_mismatch', 'guest': guest_tgid, 'kernel': self.tgid})
        for start, size in user_ranges:
            # This is the selected task's addr_limit, not a guessed universal
            # TASK_SIZE. Special kuser mappings are not regular user-copy ranges.
            if (not isinstance(start, int) or not isinstance(size, int) or start < 0 or size < 0
                    or start + size > 1 << 32 or start + size > self.address_limit):
                failures.append({'reason': 'user_range_outside_task_limit', 'address': start,
                                 'size': size, 'address_limit': self.address_limit})
        return failures

    def require_caller(self, *, guest_pid, guest_tgid, user_ranges=()):
        failures = self.mismatches(guest_pid=guest_pid, guest_tgid=guest_tgid, user_ranges=user_ranges)
        if failures:
            raise UnsupportedKernelBinding('kernel_caller_identity_or_address_space_mismatch',
                                           mismatches=failures)
        # Matching these fields alone is not permission to service open/ioctl:
        # task construction, resource ownership and the driver remain separate.
        return self
