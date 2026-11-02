"""Guarded ARM EABI stat64 subset: write sourced fields; never invent unknowns."""
import struct
import stat

import unicorn
from src.a6400.execution.guest_memory import accessible
from src.a6400.execution.guarded_bytes import GuardedGuestBytes

# ARM EABI aligns 64-bit members to 8 bytes; this is not x86's packed layout.
LAYOUT = {'st_dev': (0, 8), 'pad0': (8, 4), '__st_ino': (12, 4),
          'st_mode': (16, 4), 'st_nlink': (20, 4), 'st_uid': (24, 4), 'st_gid': (28, 4),
          'st_rdev': (32, 8), 'pad3': (40, 8), 'st_size': (48, 8),
          'st_blksize': (56, 4), 'align_blocks': (60, 4), 'st_blocks': (64, 8),
          'st_atime': (72, 4), 'st_atime_nsec': (76, 4),
          'st_mtime': (80, 4), 'st_mtime_nsec': (84, 4),
          'st_ctime': (88, 4), 'st_ctime_nsec': (92, 4), 'st_ino': (96, 8)}
SIZE = 104
UNKNOWN = ('st_dev', 'st_rdev', 'st_atime', 'st_atime_nsec',
           'st_mtime', 'st_mtime_nsec', 'st_ctime', 'st_ctime_nsec')


class GuestStat64(GuardedGuestBytes):
    def __init__(self, mu, stop, after_write, known_fields=(), regular_inode_rdev=False,
                 readonly_image_times=False):
        self.known_fields = set(known_fields)
        self.regular_inode_rdev = regular_inode_rdev
        self.readonly_image_times = readonly_image_times
        unverified = [f for f in UNKNOWN if f not in self.known_fields]
        super().__init__(mu, unverified, stop, 'stat64')
        self.after_write = after_write

    def request(self, metadata, address):
        guarded = [f for f in UNKNOWN if f not in self.known_fields]
        event = {'buffer': address, 'size': SIZE, 'partial_contract': True,
                 'source': {key: metadata[key] for key in ('image_sha256', 'inode_file_offset', 'inode') if key in metadata},
                 'guarded_fields': guarded}
        if not accessible(self.mu, address, SIZE, unicorn.UC_PROT_WRITE):
            return {**event, 'returned': 0xfffffff2, 'reason': 'EFAULT_stat64_preflight'}
        values = {'__st_ino': struct.pack('<I', metadata['inode'] & 0xffffffff),
                  'st_ino': struct.pack('<Q', metadata['inode']),
                  'st_mode': struct.pack('<I', metadata['mode']),
                  'st_nlink': struct.pack('<I', metadata['nlink']),
                  'st_uid': struct.pack('<I', metadata['uid']), 'st_gid': struct.pack('<I', metadata['gid']),
                  'st_size': struct.pack('<q', metadata['size']),
                  'st_blksize': struct.pack('<I', metadata['block_size']),
                  'st_blocks': struct.pack('<Q', metadata['blocks_512']),
                  'pad0': bytes(4), 'pad3': bytes(8), 'align_blocks': bytes(4)}
        if 'st_dev' in self.known_fields and 'st_dev' in metadata:
            values['st_dev'] = struct.pack('<Q', metadata['st_dev'])
            event['source']['st_dev'] = metadata['st_dev']
        regular_rdev = self.regular_inode_rdev and stat.S_ISREG(metadata['mode'])
        if regular_rdev:
            values['st_rdev'] = bytes(8)
            event['source'].update(st_rdev=0, st_rdev_basis='regular_inode_initialization')
            event['guarded_fields'] = [field for field in guarded if field != 'st_rdev']
        mount = metadata.get('readonly_image_mount', {})
        image_hash = metadata.get('image_sha256', '')
        readonly_times = (self.readonly_image_times and len(image_hash) == 64
                          and all(c in '0123456789abcdef' for c in image_hash)
                          and mount.get('image_sha256') == image_hash
                          and isinstance(mount.get('flags'), int) and mount['flags'] & 1
                          and mount.get('filesystem') == 'ext2')
        if readonly_times:
            times = metadata.get('image_times', {})
            if any(type(times.get(field)) is not int or not 0 <= times[field] <= 0xffffffff
                   for field in ('atime', 'mtime', 'ctime')):
                raise ValueError('Invalid sourced ext2 inode timestamps')
            for field in ('atime', 'mtime', 'ctime'):
                values['st_' + field] = struct.pack('<I', times[field])
                values['st_' + field + '_nsec'] = bytes(4)
            event['source'].update(image_times=dict(times), readonly_image_mount=dict(mount))
            event['guarded_fields'] = [field for field in event['guarded_fields']
                                       if not field.startswith(('st_atime', 'st_mtime', 'st_ctime'))]
        labels = [None] * SIZE
        for field, (offset, length) in LAYOUT.items():
            labels[offset:offset + length] = [field] * length
        if regular_rdev:
            # Only this buffer's regular-file rdev is known. Special-node and
            # other buffers retain the global unknown-field guard.
            offset, length = LAYOUT['st_rdev']
            labels[offset:offset + length] = [None] * length
        if readonly_times:
            for field in ('st_atime', 'st_atime_nsec', 'st_mtime', 'st_mtime_nsec', 'st_ctime', 'st_ctime_nsec'):
                offset, length = LAYOUT[field]
                labels[offset:offset + length] = [None] * length
        for field, value in values.items():
            self.mu.mem_write(address + LAYOUT[field][0], value)
        # Unknown ranges retain prior guest bytes; guards forbid their use.
        self.after_write(address, SIZE)
        self.track(address, labels)
        return {**event, 'returned': 0, 'reason': 'guarded_stat64_sourced_subset',
                'written_fields': sorted(values)}
