"""Selected original /dev/stream ABI; physical contents remain guarded.

No physical memory, DMA engine or display processor is emulated here.
"""
import bisect
import ctypes
import struct

import unicorn

from src.a6400.execution.guest_memory import accessible
from src.a6400.execution.guarded_bytes import UnverifiedGuestData

STREAM_GET_OFFSET = 0xc0047801
PAGE_SIZE = 4096


class UnsupportedStream(RuntimeError):
    def __init__(self, reason, **details):
        super().__init__(reason)
        self.details = {'reason': reason, 'device': '/dev/stream', **details}


class GuestStream:
    def __init__(self, mu, mapper, profile, stop, after_write):
        if (profile.get('major'), profile.get('minor')) != (249, 7):
            raise ValueError('Unexpected stream device identity')
        if profile.get('initial_offset') != 0:
            raise ValueError('Expected the selected compiled stream BSS initializer')
        self.backed_physical_ranges = dict(profile.get('backed_physical_ranges') or {})
        self.mu, self.mapper = mu, mapper
        self.profile = {k: v for k, v in profile.items() if k != 'backed_physical_ranges'}
        self.stop, self.after_write = stop, after_write
        self.offset = 0
        self.transactions = []
        self.mapping = None
        self.mappings = []
        self.unknown = []
        self._alias_buffers = {}  # root virtual_start -> host buffer; must outlive the probe

    def open(self, flags):
        # O_RDWR | O_DSYNC (0x1002) is the original DDS request; mcmn_mmap_init
        # in libInfraMediaCommon.so invokes open64("/dev/stream", 0x1002) which
        # sets O_LARGEFILE (0x20000 -> 0x21002).
        if flags not in (0x1002, 0x21002):
            raise UnsupportedStream('stream_open_flags_not_supported', flags=flags)

    def ioctl(self, cmd, arg):
        if cmd != STREAM_GET_OFFSET:
            return 0xffffffea  # Original driver returns -EINVAL.
        if not accessible(self.mu, arg, 4, unicorn.UC_PROT_WRITE):
            # Original callback ignores copy_to_user's residual. Do not invent
            # an EFAULT return or pretend that the kernel copy succeeded.
            raise UnsupportedStream('stream_copy_to_user_not_accessible', address=arg, size=4)
        self.mu.mem_write(arg, struct.pack('<I', self.offset))
        self.after_write(arg, 4)
        self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'offset': self.offset, 'returned': 0})
        return 0

    def mmap2(self, addr, length, prot, flags, fd, pgoff):
        arguments = [addr, length, prot, flags, fd, pgoff]
        if length <= 0:
            return {'syscall': 'mmap2', 'arguments': arguments, 'returned': 0xffffffea}
        rounded = (length + PAGE_SIZE - 1) & -PAGE_SIZE
        physical = pgoff * PAGE_SIZE
        if physical < 0 or physical + rounded > 0x100000000 or rounded > 64 * 1024 * 1024:
            raise UnsupportedStream('stream_physical_range_not_supported', pgoff=pgoff, length=length)
        if flags not in (1, 0x11) or prot not in (1, 2, 3):
            raise UnsupportedStream('stream_mapping_flags_not_supported', flags=flags, prot=prot)
        # Exact duplicate = alias (real stream.ko remap_pfn_range does not check prior mappings).
        twin = next((m for m in self.mappings if m['physical_start'] == physical and m['length'] == rounded
                     and 'alias_of' not in m), None)
        if twin is None and any(physical < m['physical_start'] + m['length'] and m['physical_start'] < physical + rounded
                                for m in self.mappings):
            raise UnsupportedStream('stream_multiple_mapping_requires_physical_alias_contract')
        if addr and addr % PAGE_SIZE:
            raise UnsupportedStream('stream_unaligned_address_hint', address=addr)
        # Only MAP_FIXED replaces pages; non-fixed placement is request_mmap2's free-hole search.
        if flags & 0x10 and any(p in self.mapper.mapped_pages for p in range(addr, addr + rounded, PAGE_SIZE)):
            raise UnsupportedStream('stream_mapping_would_replace_existing_pages', address=addr, length=rounded)
        # Anonymous storage is an implementation detail, not supplied physical
        # zeroes. Every byte is guarded before execution resumes.
        event = self.mapper.request_mmap2(addr, length, prot, flags | 0x20, -1, 0)
        event.update(arguments=arguments, path='/dev/stream', physical_start=physical,
                     physical_contents='unsupplied; stop on reads until overwritten', partial_contract=True)
        virtual = event['returned']
        if not 0 <= virtual < 0x80000000:
            return event
        self.mapper.mark_device_range(virtual, rounded, 'stream')
        device_mapping = {'path': '/dev/stream', 'device': 'stream', 'physical_start': physical,
                          'physical_contents': 'unsupplied; guarded until overwritten'}
        self.mapper.mappings[-1].pop('anonymous', None)
        self.mapper.mappings[-1].update(flags=flags, **device_mapping)
        event['mapping'] = dict(device_mapping)
        self.mapping = {'virtual_start': virtual, 'physical_start': physical, 'length': rounded,
                        'pgoff': pgoff, 'prot': prot}
        self.mappings.append(self.mapping)
        self.offset = abs(virtual - physical)
        if twin is not None:
            self._alias(twin, self.mapping, event)
            self.transactions.append({'operation': 'mmap_alias', **self.mapping, 'offset': self.offset})
            return event
        backed_data = self.backed_physical_ranges.get((physical, rounded))
        if backed_data is not None:
            self.mu.mem_write(virtual, backed_data)
            device_mapping['physical_contents'] = 'verified WBI section 555 mcmn_buf_init region'
            self.mapper.mappings[-1]['physical_contents'] = device_mapping['physical_contents']
            event['physical_contents'] = device_mapping['physical_contents']
        else:
            self.unknown.append((virtual, virtual + rounded))
            self.mu.hook_add(unicorn.UC_HOOK_MEM_READ, self._read, begin=virtual, end=virtual + rounded - 1)
            self.mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, self._write, begin=virtual, end=virtual + rounded - 1)
        self.transactions.append({'operation': 'mmap', **self.mapping, 'offset': self.offset})
        return event

    def _buffer(self, root):
        """Host buffer backing a root VA; created from the root's current bytes, root remapped onto it."""
        a, size = root['virtual_start'], root['length']
        buf = self._alias_buffers.get(a)
        if buf is None:
            perms = [(max(begin, a), min(end + 1, a + size), p) for begin, end, p in self.mu.mem_regions()
                     if begin < a + size and a <= end]
            buf = ctypes.create_string_buffer(bytes(self.mu.mem_read(a, size)), size)
            self.mu.mem_unmap(a, size)
            self.mu.mem_map_ptr(a, size, unicorn.UC_PROT_ALL, ctypes.addressof(buf))
            for begin, end, p in perms:
                self.mu.mem_protect(begin, end - begin, p)
            self._alias_buffers[a] = buf
        return buf

    def _link(self, root, b, prot):
        buf = self._buffer(root)
        self.mu.mem_unmap(b, root['length'])
        self.mu.mem_map_ptr(b, root['length'], unicorn.UC_PROT_ALL, ctypes.addressof(buf))
        self.mu.mem_protect(b, root['length'], prot)

    def _alias(self, root, new, event):
        """Back both VAs with one host buffer so writes through either are visible through the other."""
        size, a, b = root['length'], root['virtual_start'], new['virtual_start']
        self._link(root, b, root['prot'])
        new['alias_of'] = a
        event['alias_of'] = a
        # Unknown-byte state is shared: copy the root's, hook the alias; forget_range clears both.
        self.unknown += [(begin - a + b, end - a + b) for begin, end in self.unknown if a <= begin < a + size]
        self.mu.hook_add(unicorn.UC_HOOK_MEM_READ, self._read, begin=b, end=b + size - 1)
        self.mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, self._write, begin=b, end=b + size - 1)

    def relink_aliases(self):
        """After a checkpoint restore: re-share aliases (restored as copies) and re-register guard hooks."""
        by_va = {m['virtual_start']: m for m in self.mappings}
        for m in self.mappings:
            root = by_va.get(m.get('alias_of'))
            if root is None:
                continue
            prot = next(p for begin, end, p in self.mu.mem_regions() if begin <= m['virtual_start'] <= end)
            self._link(root, m['virtual_start'], prot)  # root bytes win; copies were identical when saved
        for m in self.mappings:  # guards are hooks on a fresh probe; roots hook only while bytes are unknown
            lo, hi = m['virtual_start'], m['virtual_start'] + m['length']
            if 'alias_of' in m or any(lo < end and begin < hi for begin, end in self.unknown):
                self.mu.hook_add(unicorn.UC_HOOK_MEM_READ, self._read, begin=lo, end=hi - 1)
                self.mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, self._write, begin=lo, end=hi - 1)

    def details(self, address, size):
        if any(address < end and begin < address + size for begin, end in self.unknown):
            target = next((m for m in self.mappings
                           if m['virtual_start'] <= address < m['virtual_start'] + m['length']),
                          self.mapping)
            return {'reason': 'stream_physical_bytes_not_supplied', 'domain': 'stream',
                    'address': address, 'size': size,
                    'physical_address': target['physical_start'] + address - target['virtual_start'],
                    'source': self.profile}
        return None

    def _read(self, uc, access, address, size, value, data):
        details = self.details(address, size)
        if details:
            self.stop(details)

    def _overlaps_unknown(self, address, size):
        """Fast path for the per-write hook: bisect over unknown ranges (rebuilt only when the list changes)."""
        if getattr(self, '_index_src', None) is not self.unknown:
            ranges = sorted(self.unknown)
            self._index_starts = [begin for begin, _ in ranges]
            self._index_maxlast, top = [], -1
            for _, last in ranges:
                top = max(top, last)
                self._index_maxlast.append(top)
            self._index_src = self.unknown
        i = bisect.bisect_left(self._index_starts, address + size)
        return i > 0 and self._index_maxlast[i - 1] > address

    def _write(self, uc, access, address, size, value, data):
        # Profiled at ~97% of wall time when every write rescanned mem_regions; only writes into unknown bytes matter.
        if self._overlaps_unknown(address, size) and accessible(uc, address, size, unicorn.UC_PROT_WRITE):
            self.forget_range(address, size)

    def forget_range(self, address, size):
        owner = next((m for m in self.mappings
                      if m['virtual_start'] <= address < m['virtual_start'] + m['length']), None)
        root = owner and owner.get('alias_of', owner['virtual_start'])
        group = [m for m in self.mappings if root is not None and root in (m['virtual_start'], m.get('alias_of'))]
        if len(group) < 2:
            return self._forget(address, size)
        for m in group:  # same bytes seen through every alias VA
            delta = m['virtual_start'] - owner['virtual_start']
            self._forget(address + delta, size)

    def _forget(self, address, size):
        end = address + size
        remaining = []
        for begin, last in self.unknown:
            if last <= address or end <= begin:
                remaining.append((begin, last))
            else:
                if begin < address:
                    remaining.append((begin, address))
                if end < last:
                    remaining.append((end, last))
        self.unknown = remaining

    def assert_known_host_read(self, address, size):
        details = self.details(address, size)
        if details:
            raise UnverifiedGuestData(details)

    def to_state(self):
        """Serialisable state for checkpoints; the Unicorn object is not pickled."""
        return {'mapping': self.mapping, 'mappings': list(self.mappings),
                'offset': self.offset, 'unknown': list(self.unknown)}

    def from_state(self, state):
        """Restore mapping/guard state onto a probe built with the same stream options."""
        if not isinstance(state, dict):
            raise ValueError('Stream checkpoint state must be a mapping')
        existing = set(self.unknown)
        self.mapping = state.get('mapping')
        self.mappings = list(state.get('mappings') or [])
        self.offset = int(state.get('offset', 0))
        self.unknown = [tuple(item) for item in (state.get('unknown') or [])]
        self._alias_buffers = {}
        self.relink_aliases()
        for begin, end in self.unknown:
            if (begin, end) in existing:
                continue
            self.mu.hook_add(unicorn.UC_HOOK_MEM_READ, self._read, begin=begin, end=end - 1)
            self.mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, self._write, begin=begin, end=end - 1)

    def report(self):
        return {'profile': self.profile, 'offset': self.offset, 'mapping': self.mapping,
                'unknown_bytes': sum(end - start for start, end in self.unknown),
                'transactions': self.transactions,
                'limits': 'exact-duplicate physical ranges alias one host buffer (partial overlaps stop); aliases are not preserved across checkpoint restore; physical contents, DMA and synchronization not supplied'}
