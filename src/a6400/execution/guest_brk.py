"""Bounded guest-only Linux brk contract, without host syscall forwarding.

Based on Linux v3.0 mm/mmap.c sys_brk: failed requests return the unchanged
break, not -errno. Resource policy here is explicit and experimental.
"""
import unicorn

PAGE_SIZE = 4096


def page_up(value):
    return (value + PAGE_SIZE - 1) & ~(PAGE_SIZE - 1)


def initial_break(image):
    ends = [s['p_vaddr'] + s['p_memsz'] for s in image['segments'] if s['p_memsz']]
    if not ends:
        raise ValueError('Cannot derive initial break without load segments')
    return page_up(max(ends))


class GuestBrk:
    def __init__(self, mu, start, max_growth=64 * 1024 * 1024):
        if start <= 0 or start % PAGE_SIZE or max_growth < 0 or start + max_growth >= 0x100000000:
            raise ValueError('Invalid experimental heap bounds')
        self.mu = mu
        self.start = start
        self.current = start
        self.ceiling = start + max_growth

    def request(self, requested):
        if not 0 <= requested <= 0xffffffff:
            raise ValueError('Program break request is not ARM32')
        old = self.current
        event = {'syscall': 'brk', 'requested': requested, 'previous': old,
                 'initial': self.start, 'ceiling': self.ceiling,
                 'returned': old, 'mapping_change': None}

        def finish(reason):
            event.update(reason=reason, returned=self.current)
            return event

        if requested == 0:
            return finish('query')
        if requested < self.start:
            return finish('below_initial_break')
        if requested > self.ceiling:
            return finish('experimental_heap_limit')
        old_end, new_end = page_up(old), page_up(requested)
        if old_end == new_end:
            self.current = requested
            return finish('same_page')
        if requested < old:
            try:
                self.mu.mem_unmap(new_end, old_end - new_end)
            except unicorn.UcError:
                return finish('unmap_failed')
            event['mapping_change'] = {'operation': 'unmap', 'address': new_end, 'size': old_end - new_end}
        else:
            # Linux checks one additional page beyond the growth range.
            for begin, end_inclusive, permissions in self.mu.mem_regions():
                if begin < new_end + PAGE_SIZE and end_inclusive + 1 > old_end:
                    return finish('mapping_collision_or_guard')
            try:
                self.mu.mem_map(old_end, new_end - old_end, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
            except unicorn.UcError:
                return finish('allocation_failed')
            event['mapping_change'] = {'operation': 'map_rw', 'address': old_end, 'size': new_end - old_end}
        self.current = requested
        return finish('shrink' if requested < old else 'growth')
