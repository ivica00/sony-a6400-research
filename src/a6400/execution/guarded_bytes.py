"""Shared provenance guards for bytes whose guest-visible values are unverified."""
import unicorn


class UnverifiedGuestData(RuntimeError):
    def __init__(self, details):
        super().__init__('A guest consumer requested unverified data')
        self.details = details


class GuardedGuestBytes:
    def __init__(self, mu, unverified_fields, stop, domain):
        self.mu, self.stop, self.domain = mu, stop, domain
        self.unverified_fields = set(unverified_fields)
        self.bytes = {}
        self.read_fields = {}
        mu.hook_add(unicorn.UC_HOOK_MEM_READ, self._read)
        mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, self._write)

    def track(self, address, labels):
        self.forget_range(address, len(labels))
        self.bytes.update({address + index: label for index, label in enumerate(labels) if label is not None})

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
