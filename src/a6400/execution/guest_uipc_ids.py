"""Bounded original kernel dynamic-ID geometry in a declared empty namespace.

E0301: osal_dynamic_id instructions and .data descriptors. This is a new
emulated allocator namespace, not a copy of the camera's live global bitmap.
"""


class UnsupportedDynamicId(RuntimeError):
    pass


class KernelDynamicIds:
    GEOMETRY = {'queue': (0x6000, 0x1000), 'broadcast': (0x7000, 0x1000),
                'semaphore': (0x6000, 0x2000)}

    def __init__(self):
        self.allocations = {kind: {} for kind in self.GEOMETRY}

    @staticmethod
    def kind(type_value):
        return 'semaphore' if type_value & 0x10 else 'broadcast' if type_value & 4 else 'queue'

    def allocate(self, type_value, key):
        if not type_value & 2 or type_value & 0x40:
            return -1024, None
        kind = self.kind(type_value)
        base, count = self.GEOMETRY[kind]
        used = self.allocations[kind]
        slot = next((slot for slot in range(base, base + count) if slot not in used), None)
        if slot is None:
            raise UnsupportedDynamicId('dynamic_id_pool_exhausted_oom_side_effects_not_supplied')
        value = ((key & 0xffff) << 16) | slot
        used[slot] = value
        return 0, value

    def release(self, type_value, value):
        if not type_value & 2 or not type_value & 0x40:
            return -1024
        kind = self.kind(type_value)
        base, count = self.GEOMETRY[kind]
        slot = value & 0x7fff
        if not base <= slot < base + count:
            return -1024
        # Scope guard: original kernel ignores the high key when freeing.
        # Unknown or stale IDs are not owned by this emulated namespace.
        if self.allocations[kind].get(slot) != value:
            raise UnsupportedDynamicId('dynamic_id_not_owned_or_already_released')
        del self.allocations[kind][slot]
        return 0
