"""Guarded ARM EABI mmap2 / mprotect / munmap contract over verified guest files and anonymous pages."""

import hashlib
import unicorn
from unicorn import arm_const as arm
from src.a6400.execution.guest_memory import accessible

# Linux ARM EABI protection flags
PROT_NONE = 0x0
PROT_READ = 0x1
PROT_WRITE = 0x2
PROT_EXEC = 0x4

# Linux ARM EABI map flags
MAP_SHARED = 0x1
MAP_PRIVATE = 0x2
MAP_FIXED = 0x10
MAP_ANONYMOUS = 0x20
MAP_GROWSDOWN = 0x100
MAP_DENYWRITE = 0x800
MAP_EXECUTABLE = 0x1000
MAP_LOCKED = 0x2000
MAP_NORESERVE = 0x4000
MAP_POPULATE = 0x8000
MAP_NONBLOCK = 0x10000
MAP_STACK = 0x20000
MAP_HUGETLB = 0x40000

PAGE_SIZE = 4096
PAGE_MASK = ~(PAGE_SIZE - 1)
CHUNK_ALIGN = 65536
CHUNK_MASK = ~(CHUNK_ALIGN - 1)


class UnsupportedMmap(RuntimeError):
    def __init__(self, reason, **details):
        super().__init__(reason)
        self.details = {'reason': reason, **details}


class GuestMmap:
    def __init__(self, mu, filesystem, base_address=0x50000000, ceiling_address=0x5f000000,
                 search_low_base=None, after_write=None):
        self.mu = mu
        self.filesystem = filesystem
        self.base_address = base_address
        self.next_address = base_address
        self.ceiling_address = ceiling_address
        self.search_low_base = search_low_base
        self.after_write = after_write
        self.mapped_pages = set()
        self.page_backing = {}
        self.mappings = []

    def register_range(self, start, size):
        """Record pre-existing guest mappings (such as initial ELF segments and stack) in mapped_pages."""
        aligned_start = start & PAGE_MASK
        aligned_end = (start + size + PAGE_SIZE - 1) & PAGE_MASK
        for p in range(aligned_start, aligned_end, PAGE_SIZE):
            self.mapped_pages.add(p)
            self.page_backing[p] = {'kind': 'initial'}

    def request_mmap2(self, addr, length, prot, flags, fd, pgoff):
        event = {'syscall': 'mmap2', 'arguments': [addr, length, prot, flags, fd, pgoff],
                 'partial_contract': True}
        if length <= 0:
            return {**event, 'returned': 0xffffffea, 'reason': 'EINVAL_zero_or_negative_length'}
        aligned_len = (length + PAGE_SIZE - 1) & PAGE_MASK

        is_fixed = bool(flags & MAP_FIXED)
        used_cursor = False
        is_anon = bool(flags & MAP_ANONYMOUS)
        # A failed file lookup must not map pages, change protection, or consume
        # allocator space. fd=-1 alone does not request anonymous memory.
        if not is_anon:
            if fd not in self.filesystem.fds:
                return {**event, 'returned': 0xfffffff7, 'reason': 'EBADF'}
            desc = self.filesystem.fds[fd]
            if 'data' not in desc or 'path' not in desc:
                raise UnsupportedMmap('mmap_fd_not_verified_regular_file', fd=fd)

        if is_fixed:
            if addr & (PAGE_SIZE - 1):
                return {**event, 'returned': 0xffffffea, 'reason': 'EINVAL_misaligned_fixed_address'}
            chosen_addr = addr
        else:
            if (addr >= PAGE_SIZE and not addr & (PAGE_SIZE - 1)
                    and addr + aligned_len <= self.ceiling_address
                    and not any(p in self.mapped_pages for p in range(addr, addr + aligned_len, PAGE_SIZE))):
                # Request with address hint
                chosen_addr = addr
            else:
                chosen_addr = self.next_address
                used_cursor = True
                # Non-fixed requests cannot replace existing ELF, stack, or
                # earlier hinted mappings. Placement remains an explicit model.
                found = False
                while chosen_addr + aligned_len <= self.ceiling_address:
                    collision = next((p for p in range(chosen_addr, chosen_addr + aligned_len, PAGE_SIZE)
                                      if p in self.mapped_pages), None)
                    if collision is None:
                        found = True
                        break
                    chosen_addr = (collision + PAGE_SIZE + CHUNK_ALIGN - 1) & CHUNK_MASK

                if not found and self.search_low_base is not None and self.search_low_base < self.base_address:
                    chosen_addr = self.search_low_base
                    while chosen_addr + aligned_len <= self.ceiling_address:
                        collision = next((p for p in range(chosen_addr, chosen_addr + aligned_len, PAGE_SIZE)
                                          if p in self.mapped_pages), None)
                        if collision is None:
                            found = True
                            break
                        chosen_addr = (collision + PAGE_SIZE + CHUNK_ALIGN - 1) & CHUNK_MASK

        end_addr = chosen_addr + aligned_len
        if chosen_addr < 0x1000 or end_addr > self.ceiling_address:
            raise UnsupportedMmap('mmap_address_outside_guest_boundary', addr=chosen_addr, end=end_addr,
                                  ceiling=self.ceiling_address)
        if used_cursor:
            self.next_address = (end_addr + CHUNK_ALIGN - 1) & CHUNK_MASK

        # Map pages into Unicorn if not already mapped
        pages_to_map = [p for p in range(chosen_addr, end_addr, PAGE_SIZE) if p not in self.mapped_pages]
        # Group contiguous runs of pages
        if pages_to_map:
            run_start = pages_to_map[0]
            run_len = PAGE_SIZE
            for p in pages_to_map[1:]:
                if p == run_start + run_len:
                    run_len += PAGE_SIZE
                else:
                    self.mu.mem_map(run_start, run_len, prot if prot != 0 else unicorn.UC_PROT_READ)
                    run_start = p
                    run_len = PAGE_SIZE
            self.mu.mem_map(run_start, run_len, prot if prot != 0 else unicorn.UC_PROT_READ)
            self.mapped_pages.update(pages_to_map)

        # If pages were already mapped, update their protection
        pages_to_protect = [p for p in range(chosen_addr, end_addr, PAGE_SIZE) if p not in pages_to_map]
        if pages_to_protect:
            run_start = pages_to_protect[0]
            run_len = PAGE_SIZE
            for p in pages_to_protect[1:]:
                if p == run_start + run_len:
                    run_len += PAGE_SIZE
                else:
                    self.mu.mem_protect(run_start, run_len, prot if prot != 0 else unicorn.UC_PROT_READ)
                    run_start = p
                    run_len = PAGE_SIZE
            self.mu.mem_protect(run_start, run_len, prot if prot != 0 else unicorn.UC_PROT_READ)

        # Populate memory if file-backed
        if not is_anon:
            file_offset = pgoff * PAGE_SIZE
            file_data = desc['data']
            if file_offset < len(file_data):
                raw = file_data[file_offset:file_offset + length]
            else:
                raw = b''
            self.mu.mem_write(chosen_addr, raw)
            if self.after_write:
                self.after_write(chosen_addr, len(raw))
            # Zero-fill remaining portion of the allocated page(s)
            if aligned_len > len(raw):
                remainder = aligned_len - len(raw)
                self.mu.mem_write(chosen_addr + len(raw), bytes(remainder))
                if self.after_write:
                    self.after_write(chosen_addr + len(raw), remainder)
            mapping_info = {'path': desc['path'], 'offset': file_offset, 'size': len(raw),
                            'sha256': hashlib.sha256(raw).hexdigest()}
        else:
            self.mu.mem_write(chosen_addr, bytes(aligned_len))
            if self.after_write:
                self.after_write(chosen_addr, aligned_len)
            mapping_info = {'anonymous': True}

        self.mappings.append({'address': chosen_addr, 'length': aligned_len, 'prot': prot,
                              'flags': flags, **mapping_info})
        for page in range(chosen_addr, end_addr, PAGE_SIZE):
            self.page_backing[page] = {'kind': 'anonymous' if is_anon else 'file', 'flags': flags}
        return {**event, 'returned': chosen_addr, 'reason': 'guarded_mmap2_allocated',
                'mapping': mapping_info}

    def request_madvise(self, addr, length, advice):
        """Only MADV_DONTNEED on known private anonymous pages; no host syscall.

        Eager zeroing implements subsequent zero-fill-on-demand reads in this
        process model. RSS, physical reclaim and timing are not modeled.
        """
        event = {'syscall': 'madvise', 'arguments': [addr, length, advice], 'partial_contract': True}
        if advice != 4:
            raise UnsupportedMmap('madvise_advice_not_supported', advice=advice)
        if addr < 0 or addr > 0xffffffff or addr % PAGE_SIZE or length < 0 or length > 0xffffffff:
            return {**event, 'returned': 0xffffffea, 'reason': 'EINVAL_madvise_range'}
        rounded = (length + PAGE_SIZE - 1) & PAGE_MASK
        if addr + rounded > 0x100000000:
            return {**event, 'returned': 0xffffffea, 'reason': 'EINVAL_madvise_overflow'}
        # Preflight the entire range before a host write. A mixed or missing
        # range is outside this subset; do not partially discard then invent errno.
        for page in range(addr, addr + rounded, PAGE_SIZE):
            owner = self.page_backing.get(page, {})
            flags = owner.get('flags', 0)
            if (page not in self.mapped_pages or owner.get('kind') != 'anonymous'
                    or flags & (MAP_PRIVATE | MAP_ANONYMOUS) != (MAP_PRIVATE | MAP_ANONYMOUS)
                    or flags & ~(MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED)):
                raise UnsupportedMmap('madvise_requires_known_private_anonymous_pages', address=page)
        if not accessible(self.mu, addr, rounded, 0):
            raise UnsupportedMmap('madvise_range_not_mapped', address=addr, length=rounded)
        zero_page = bytes(PAGE_SIZE)
        for page in range(addr, addr + rounded, PAGE_SIZE):
            self.mu.mem_write(page, zero_page)
            if self.after_write:
                self.after_write(page, PAGE_SIZE)
        return {**event, 'returned': 0, 'reason': 'private_anonymous_pages_discarded', 'discarded_bytes': rounded}

    def mark_device_range(self, addr, length, device):
        """Keep device emulation's storage distinct from private anonymous RAM."""
        pages = range(addr & PAGE_MASK, (addr + length + PAGE_SIZE - 1) & PAGE_MASK, PAGE_SIZE)
        for page in pages:
            if page not in self.mapped_pages:
                raise UnsupportedMmap('device_range_not_mapped', address=page)
        for page in pages:
            self.page_backing[page] = {'kind': 'device', 'device': device}

    def request_mprotect(self, addr, length, prot):
        event = {'syscall': 'mprotect', 'arguments': [addr, length, prot], 'partial_contract': True}
        if addr & (PAGE_SIZE - 1):
            return {**event, 'returned': 0xffffffea, 'reason': 'EINVAL_misaligned_address'}
        aligned_len = (length + PAGE_SIZE - 1) & PAGE_MASK
        end_addr = addr + aligned_len
        # Check that pages are mapped
        for p in range(addr, end_addr, PAGE_SIZE):
            if p not in self.mapped_pages:
                return {**event, 'returned': 0xfffffff4, 'reason': 'ENOMEM_unmapped_page'}
        self.mu.mem_protect(addr, aligned_len, prot if prot != 0 else unicorn.UC_PROT_READ)
        return {**event, 'returned': 0, 'reason': 'mprotect_applied'}

    def request_munmap(self, addr, length):
        event = {'syscall': 'munmap', 'arguments': [addr, length], 'partial_contract': True}
        if addr & (PAGE_SIZE - 1):
            return {**event, 'returned': 0xffffffea, 'reason': 'EINVAL_misaligned_address'}
        aligned_len = (length + PAGE_SIZE - 1) & PAGE_MASK
        end_addr = addr + aligned_len
        pages_to_unmap = [p for p in range(addr, end_addr, PAGE_SIZE) if p in self.mapped_pages]
        if pages_to_unmap:
            run_start = pages_to_unmap[0]
            run_len = PAGE_SIZE
            for p in pages_to_unmap[1:]:
                if p == run_start + run_len:
                    run_len += PAGE_SIZE
                else:
                    self.mu.mem_unmap(run_start, run_len)
                    run_start = p
                    run_len = PAGE_SIZE
            self.mu.mem_unmap(run_start, run_len)
            self.mapped_pages.difference_update(pages_to_unmap)
            for page in pages_to_unmap:
                self.page_backing.pop(page, None)
        return {**event, 'returned': 0, 'reason': 'munmap_applied'}
