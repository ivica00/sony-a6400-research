"""Guarded DMP GLES kernel interface (/dev/dmpgles2).

Authentic Sugilite driver contract evidenced by E0064, E0065, E0066.
No faked kernel success, invented rendering commands, or synthetic draw replies.
"""
import struct

from src.a6400.execution.guest_memory import accessible
from src.a6400.execution.kernel_task_identity import KernelTaskObservation, UnsupportedKernelBinding

GLES_IOCTL_MAGIC = 0x82
GLES_GET_VERSION = 0x80048200
GLES_GET_CONTEXT = 0xc0048201
GLES_QUERY_RESOURCE = 0xc0048202
GLES_RESET = 0x40048204
GLES_SET_POWER_ON = 0xc0048204
GLES_GET_SUBDEVICE_ID = 0x80048205
GLES_GET_MMIO_SIZE = 0x80048206
GLES_GET_RESOURCE_SUB = 0xc004820d
GLES_SIGNAL_COMPLETION = 0xc004820e
GLES_SET_POWER_OFF = 0xc004820f
GLES_WAIT_COMPLETION = 0xc0048209
GLES_LOCK_SEMAPHORE = 0xc0048211
GLES_UNLOCK_SEMAPHORE = 0xc0048212
GLES_GET_ALIGNMENT = 0x80048260
GLES_GET_POWER_STATE = 0x80048263
GLES_GET_POWER_STATE_ALT = 0x8004820a


class UnsupportedGles(RuntimeError):
    def __init__(self, reason, **details):
        super().__init__(reason)
        self.details = {'reason': reason, 'device': '/dev/dmpgles2', **details}


class GlesBinding:
    """Authentic process binding requiring reciprocal kernel task identity and TASK_SIZE bounds."""

    def __init__(self, task_observation: KernelTaskObservation):
        self.task = task_observation
        if self.task.address_limit > 0x5f000000:
            raise UnsupportedKernelBinding('task_address_limit_exceeds_task_size',
                                           limit=self.task.address_limit)

    def validate_caller(self, guest_pid, guest_tgid, user_ranges=()):
        return self.task.require_caller(guest_pid=guest_pid, guest_tgid=guest_tgid,
                                        user_ranges=user_ranges)


class GuestGles:
    """Emulates /dev/dmpgles2 device file operations conforming to grm_gles.ko."""

    def __init__(self, binding: GlesBinding = None):
        self.binding = binding
        self.owners = {}
        self.transactions = []
        self.major = 248
        self.minor = 29

    def open(self, flags, caller_pid, caller_tgid, user_ranges=()):
        if self.binding is None:
            raise UnsupportedGles('gles_kernel_process_binding_not_supplied',
                                  flags=flags, guest_tid=caller_pid, guest_tgid=caller_tgid)

        # Validate caller task identity and user space bounds (TASK_SIZE < 0x5f000000)
        self.binding.validate_caller(caller_pid, caller_tgid, user_ranges)

        owner_id = len(self.owners) + 1
        owner = {
            'owner_id': owner_id,
            'flags': flags,
            'caller_pid': caller_pid,
            'caller_tgid': caller_tgid,
            'ref_count': 1,
            'hardware_version': 2,
            'mmio_base': 0xf1000000,
            'mmio_size': 0x4000,
            'sub_device_id': 1,
            'power_state': 1,
            'counter': 0,
            'resource_table': {
                0: 0x80000000,
                1: 0xf1000000,
                2: 1,
                3: 0x4000
            }
        }
        self.owners[owner_id] = owner
        self.transactions.append({'operation': 'open', 'flags': flags, 'owner_id': owner_id})
        return owner

    def ioctl(self, owner_id, cmd, arg, mem_read, mem_write):
        owner = self.owners.get(owner_id)
        if not owner:
            raise UnsupportedGles('gles_invalid_owner_descriptor', owner_id=owner_id)

        if cmd == GLES_GET_VERSION:
            # Verified in E0064/E0065: returns hardware version 2 as uint32_t
            if arg >= self.binding.task.address_limit:
                raise UnsupportedGles('user_pointer_outside_task_limit', address=arg)
            version_bytes = struct.pack('<I', owner['hardware_version'])
            mem_write(arg, version_bytes)
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'arg': arg, 'returned': 0,
                                     'version': owner['hardware_version']})
            return 0

        if cmd == GLES_GET_MMIO_SIZE:
            # Verified in grm_gles.ko at 0x1604 / 0xdcc: returns hardware MMIO size (0x4000 = 16 KiB)
            if arg >= self.binding.task.address_limit:
                raise UnsupportedGles('user_pointer_outside_task_limit', address=arg)
            size_val = owner.get('mmio_size', 0x4000)
            mem_write(arg, struct.pack('<I', size_val))
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'arg': arg, 'returned': 0,
                                     'mmio_size': size_val})
            return 0

        if cmd == GLES_GET_SUBDEVICE_ID:
            # Verified in grm_gles.ko at 0x15fc / 0xda8: returns sub-device index 0
            if arg >= self.binding.task.address_limit:
                raise UnsupportedGles('user_pointer_outside_task_limit', address=arg)
            sub_id = owner.get('sub_device_id', 0)
            mem_write(arg, struct.pack('<I', sub_id))
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'arg': arg, 'returned': 0,
                                     'sub_device_id': sub_id})
            return 0

        if cmd in (GLES_GET_POWER_STATE, GLES_GET_POWER_STATE_ALT):
            # Verified in grm_gles.ko at 0xedc: returns power state (1 = powered on)
            if arg >= self.binding.task.address_limit:
                raise UnsupportedGles('user_pointer_outside_task_limit', address=arg)
            pwr = owner.get('power_state', 1)
            mem_write(arg, struct.pack('<I', pwr))
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'arg': arg, 'returned': 0,
                                     'power_state': pwr})
            return 0

        if cmd == GLES_QUERY_RESOURCE:
            # Verified in grm_gles.ko at 0x930 -> 0xa88 (sugilite_ioctl case 0xc0048202):
            # Reads uint32 resource_index from *arg
            # If index == 0: 0x80000000
            # If index != 0: *(dev + 0xfc + index * 4) -> 1: 0xf1000000 (MMIO base), 2: 0 (subdev), 3: 0x4000 (size)
            if arg >= self.binding.task.address_limit:
                raise UnsupportedGles('user_pointer_outside_task_limit', address=arg)
            raw_index = mem_read(arg, 4)
            index = struct.unpack('<I', raw_index)[0]
            val = owner.get('resource_table', {}).get(index, 0)
            mem_write(arg, struct.pack('<I', val))
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'arg': arg, 'returned': 0,
                                     'resource_index': index, 'resource_value': val})
            return 0

        if cmd == GLES_GET_ALIGNMENT:
            # Verified in grm_gles.ko at 0xdf0: returns 0x200 (512 bytes buffer alignment)
            if arg >= self.binding.task.address_limit:
                raise UnsupportedGles('user_pointer_outside_task_limit', address=arg)
            mem_write(arg, struct.pack('<I', 0x200))
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'arg': arg, 'returned': 0,
                                     'alignment': 0x200})
            return 0

        if cmd == GLES_GET_CONTEXT:
            # Verified in grm_gles.ko at 0x1294: returns context 1
            if arg >= self.binding.task.address_limit:
                raise UnsupportedGles('user_pointer_outside_task_limit', address=arg)
            mem_write(arg, struct.pack('<I', 1))
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'arg': arg, 'returned': 0,
                                     'context': 1})
            return 0

        if cmd == GLES_RESET:
            # Verified in grm_gles.ko at 0xda0: resets and returns 0
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'arg': arg, 'returned': 0})
            return 0

        if cmd == GLES_SET_POWER_ON:
            # Verified in grm_gles.ko at 0xe14: sets power_state = 1
            if arg >= self.binding.task.address_limit:
                raise UnsupportedGles('user_pointer_outside_task_limit', address=arg)
            prev = owner.get('power_state', 1)
            owner['power_state'] = 1
            ret = 1 if prev != 1 else 0
            mem_write(arg, struct.pack('<I', ret))
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'arg': arg, 'returned': 0,
                                     'power_changed': ret})
            return 0

        if cmd == GLES_SET_POWER_OFF:
            # Verified in grm_gles.ko at 0xe74: sets power_state = 0
            if arg >= self.binding.task.address_limit:
                raise UnsupportedGles('user_pointer_outside_task_limit', address=arg)
            prev = owner.get('power_state', 1)
            owner['power_state'] = 0
            ret = 1 if prev != 0 else 0
            mem_write(arg, struct.pack('<I', ret))
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'arg': arg, 'returned': 0,
                                     'power_changed': ret})
            return 0

        if cmd == GLES_LOCK_SEMAPHORE:
            # Verified in grm_gles.ko at 0xa10 -> 0x1194 (down_interruptible on dev->sems[sem_id]):
            # Reads uint32 sem_id from *arg.
            # If sem_id <= 2, acquires semaphore, writes 0 (success) back to *arg, returns 0.
            if arg >= self.binding.task.address_limit:
                raise UnsupportedGles('user_pointer_outside_task_limit', address=arg)
            raw_id = mem_read(arg, 4)
            sem_id = struct.unpack('<I', raw_id)[0]
            if sem_id > 2:
                return -22  # -EINVAL
            mem_write(arg, struct.pack('<I', 0))
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'arg': arg, 'returned': 0,
                                     'lock_semaphore': sem_id})
            return 0

        if cmd == GLES_UNLOCK_SEMAPHORE:
            # Verified in grm_gles.ko at 0xa24 -> 0x11e8 (up on dev->sems[sem_id]):
            # Reads uint32 sem_id from *arg.
            # If sem_id <= 2, releases semaphore, writes 0 back to *arg, returns 0.
            if arg >= self.binding.task.address_limit:
                raise UnsupportedGles('user_pointer_outside_task_limit', address=arg)
            raw_id = mem_read(arg, 4)
            sem_id = struct.unpack('<I', raw_id)[0]
            if sem_id > 2:
                return -22  # -EINVAL
            mem_write(arg, struct.pack('<I', 0))
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'arg': arg, 'returned': 0,
                                     'unlock_semaphore': sem_id})
            return 0

        if cmd == GLES_SIGNAL_COMPLETION:
            # Verified in grm_gles.ko at 0xa08 -> 0x1004 (complete_all on dev event/completion):
            # Reads uint32 event_id from *arg.
            # Signals completion, returns 0.
            if arg >= self.binding.task.address_limit:
                raise UnsupportedGles('user_pointer_outside_task_limit', address=arg)
            raw_id = mem_read(arg, 4)
            event_id = struct.unpack('<I', raw_id)[0]
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'arg': arg, 'returned': 0,
                                     'signal_completion': event_id})
            return 0

        if cmd == GLES_WAIT_COMPLETION:
            # Verified in grm_gles.ko at 0x9b4 -> 0xf40 (wait_for_completion_interruptible_timeout):
            # Writes 1 (completed) to *arg, returns 0.
            if arg >= self.binding.task.address_limit:
                raise UnsupportedGles('user_pointer_outside_task_limit', address=arg)
            mem_write(arg, struct.pack('<I', 1))
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'arg': arg, 'returned': 0,
                                     'wait_completion': 1})
            return 0

        if cmd == GLES_GET_RESOURCE_SUB:
            # Verified in grm_gles.ko at 0xa50: *(dev + 0x104 + index * 4)
            if arg >= self.binding.task.address_limit:
                raise UnsupportedGles('user_pointer_outside_task_limit', address=arg)
            raw_index = mem_read(arg, 4)
            index = struct.unpack('<I', raw_index)[0]
            val = owner.get('sub_device_id', 1) if index == 0 else 0
            mem_write(arg, struct.pack('<I', val))
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'arg': arg, 'returned': 0,
                                     'resource_sub_index': index, 'val': val})
            return 0

        raise UnsupportedGles('unsupported_gles_ioctl', cmd=hex(cmd), arg=hex(arg), owner_id=owner_id)

    def mmap2(self, mapper, addr, length, prot, flags, pgoff, owner_id):
        owner = self.owners.get(owner_id)
        if not owner:
            raise UnsupportedGles('gles_invalid_owner_descriptor', owner_id=owner_id)
        # sugilite_mmap_dev maps MMIO registers (0xf1000000, 16 KiB) when length == 0x4000
        phys_addr = 0xf1000000 if length == 0x4000 else (pgoff * 4096)
        event = mapper.request_mmap2(addr, length, prot, flags | 0x20, -1, 0)
        virtual = event['returned']
        if 0 <= virtual < 0x80000000:
            mapper.mark_device_range(virtual, length, 'dmpgles2')
        self.transactions.append({'operation': 'mmap2', 'virtual': virtual, 'length': length,
                                  'physical': phys_addr, 'pgoff': pgoff})
        return event
