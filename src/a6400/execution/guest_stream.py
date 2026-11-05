"""Selected original /dev/stream ABI; physical contents remain guarded.

No physical memory, DMA engine or display processor is emulated here.
"""
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
        if any(physical < m['physical_start'] + m['length'] and m['physical_start'] < physical + rounded
               for m in self.mappings):
            raise UnsupportedStream('stream_multiple_mapping_requires_physical_alias_contract')
        if addr and addr % PAGE_SIZE:
            raise UnsupportedStream('stream_unaligned_address_hint', address=addr)
        chosen = addr or self.mapper.next_address
        if any(p in self.mapper.mapped_pages for p in range(chosen, chosen + rounded, PAGE_SIZE)):
            raise UnsupportedStream('stream_mapping_would_replace_existing_pages', address=chosen, length=rounded)
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

    def _write(self, uc, access, address, size, value, data):
        if accessible(uc, address, size, unicorn.UC_PROT_WRITE):
            self.forget_range(address, size)

    def forget_range(self, address, size):
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

    def report(self):
        return {'profile': self.profile, 'offset': self.offset, 'mapping': self.mapping,
                'unknown_bytes': sum(end - start for start, end in self.unknown),
                'transactions': self.transactions,
                'limits': 'single mapping; physical contents, aliases, DMA and synchronization not supplied'}
