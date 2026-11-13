"""Shared provenance guards for bytes whose guest-visible values are unverified."""
import unicorn


class UnverifiedGuestData(RuntimeError):
    def __init__(self, details):
        super().__init__('A guest consumer requested unverified data')
        self.details = details


# Opt-in (set by --fast-hooks runs): page-range hooks instead of global ones. Global hooks stay the
# default because exact-mode instruction counts shift by one without them.
PAGE_HOOKS = False


class GuardedGuestBytes:
    def __init__(self, mu, unverified_fields, stop, domain):
        self.mu, self.stop, self.domain = mu, stop, domain
        self.unverified_fields = set(unverified_fields)
        self._bytes = {}
        self.read_fields = {}
        self.hooked_pages = set()
        if not PAGE_HOOKS:
            mu.hook_add(unicorn.UC_HOOK_MEM_READ, self._read)
            mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, self._write)

    @property
    def bytes(self):
        return self._bytes

    @bytes.setter
    def bytes(self, value):  # checkpoint restore assigns the whole dict
        self._bytes = value
        self._rehook(True)

    def _rehook(self, was_empty):
        """Invariant: an access that touches a tracked byte always starts on a hooked page.
        Accesses outside hooked pages cost no Python callback overhead.
        Hooks are never deleted; at most one read/write pair exists per page."""
        if not PAGE_HOOKS:
            return
        PAGE = 0x1000
        needed_pages = set()
        for a in self._bytes:
            needed_pages.add((a // PAGE) * PAGE)
            needed_pages.add((max(a - 15, 0) // PAGE) * PAGE)
        for page in needed_pages:
            if page not in self.hooked_pages:
                self.mu.hook_add(unicorn.UC_HOOK_MEM_READ, self._read, begin=page, end=page + PAGE - 1)
                self.mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, self._write, begin=page, end=page + PAGE - 1)
                self.hooked_pages.add(page)

    def track(self, address, labels):
        was_empty = not self._bytes
        self.forget_range(address, len(labels))
        self._bytes.update({address + index: label for index, label in enumerate(labels) if label is not None})
        self._rehook(was_empty)

    def _fields(self, address, size):
        return {self.bytes[a] for a in range(address, address + size) if a in self.bytes}

    def _details(self, address, size, fields):
        return {'address': address, 'size': size, 'fields': sorted(fields), 'domain': self.domain}

    def _read(self, uc, access, address, size, value, user_data):
        fields = self._fields(address, size)
        for field in sorted(fields):
            self.read_fields[field] = self.read_fields.get(field, 0) + 1
        unknown = fields.intersection(self.unverified_fields)
        if unknown:
            self.stop(self._details(address, size, unknown))

    def _write(self, uc, access, address, size, value, user_data):
        self.forget_range(address, size)

    def forget_range(self, address, size):
        for offset in range(size):
            self.bytes.pop(address + offset, None)

    def assert_known_host_read(self, address, size):
        unknown = self._fields(address, size).intersection(self.unverified_fields)
        if unknown:
            raise UnverifiedGuestData({**self._details(address, size, unknown), 'consumer': 'guest_filesystem'})
