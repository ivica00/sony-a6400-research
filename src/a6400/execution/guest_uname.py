"""Image-backed UTS data with fail-closed guards for runtime-unknown fields."""
import hashlib
from pathlib import Path
import re

import unicorn
from src.a6400.execution.guest_memory import accessible
from src.a6400.execution.guarded_bytes import GuardedGuestBytes, UnverifiedGuestData

FIELDS = ('sysname', 'nodename', 'release', 'version', 'machine', 'domainname')
FIELD_SIZE = 65
STRUCT_SIZE = FIELD_SIZE * len(FIELDS)
UNVERIFIED = ('nodename', 'machine', 'domainname')


UnverifiedIdentityData = UnverifiedGuestData  # compatibility for callers of the identity-only guard


def extract_kernel_uts(path, expected_hash):
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_hash:
        raise ValueError('Kernel identity source hash mismatch')
    banner = re.search(rb'Linux version ([^ \x00]+) [^\x00]+', data)
    if banner is None:
        raise ValueError('Missing kernel release banner')
    candidates = []
    for match in re.finditer(b'Linux\x00', data):
        raw = data[match.start():match.start() + STRUCT_SIZE]
        if len(raw) != STRUCT_SIZE:
            continue
        fields = {}
        for index, name in enumerate(FIELDS):
            chunk = raw[index * FIELD_SIZE:(index + 1) * FIELD_SIZE]
            value, separator, padding = chunk.partition(b'\0')
            if not value or not separator or any(padding) or any(c < 32 or c > 126 for c in value):
                break
            fields[name] = value.decode('ascii')
        else:
            if fields['release'].encode('ascii') == banner[1]:
                candidates.append({'source_sha256': expected_hash, 'file_offset': match.start(),
                                   'raw_hex': raw.hex(), 'fields': fields,
                                   'runtime_unverified_fields': list(UNVERIFIED),
                                   'scope': 'compiled UTS defaults; runtime-dependent reads are guarded'})
    if len(candidates) != 1:
        raise ValueError(f'Expected one unambiguous UTS record, found {len(candidates)}')
    return candidates[0]


class GuestUname(GuardedGuestBytes):
    def __init__(self, mu, profile, stop):
        self.profile = profile
        self.raw = bytes.fromhex(profile['raw_hex'])
        if len(self.raw) != STRUCT_SIZE:
            raise ValueError('Invalid UTS record length')
        super().__init__(mu, UNVERIFIED, stop, 'uname')

    def request(self, address):
        event = {'syscall': 'uname', 'buffer': address, 'size': STRUCT_SIZE,
                 'source_sha256': self.profile['source_sha256'],
                 'source_file_offset': self.profile['file_offset']}
        if not accessible(self.mu, address, STRUCT_SIZE, unicorn.UC_PROT_WRITE):
            return {**event, 'returned': 0xfffffff2, 'reason': 'EFAULT_preflight'}
        self.mu.mem_write(address, self.raw)
        self.track(address, [FIELDS[offset // FIELD_SIZE] for offset in range(STRUCT_SIZE)])
        return {**event, 'returned': 0, 'reason': 'copied_compiled_record_with_runtime_read_guards'}
