"""Read inode identities and metadata from hash-checked Linux ext2 images."""
import hashlib
import math
from pathlib import Path
import stat
import struct


class Ext2Metadata:
    def __init__(self, path, expected_hash):
        self.data = Path(path).read_bytes()
        if hashlib.sha256(self.data).hexdigest() != expected_hash:
            raise ValueError('ext2 source hash mismatch')
        self.sha256 = expected_hash
        if self.data[1080:1082] != b'\x53\xef':
            raise ValueError('Not a supported ext2 image')
        if len(self.data) < 2048:
            raise ValueError('Truncated ext2 superblock')
        u32 = lambda offset: struct.unpack_from('<I', self.data, offset)[0]
        log_block_size = u32(1048)
        if log_block_size > 2:
            raise ValueError('Unsupported ext2 block size')
        self.block_size = 1024 << log_block_size
        self.inodes_count, self.blocks_count = u32(1024), u32(1028)
        self.blocks_per_group, self.inodes_per_group = u32(1056), u32(1064)
        revision, creator_os = u32(1100), u32(1096)
        self.inode_size = struct.unpack_from('<H', self.data, 1112)[0] if revision else 128
        if (self.block_size not in (1024, 2048, 4096) or creator_os != 0 or revision not in (0, 1)
                or self.inode_size < 128 or self.inode_size > self.block_size
                or not self.blocks_per_group or not self.inodes_per_group):
            raise ValueError('Unsupported ext2 geometry or creator')
        if revision and (u32(1120) & ~2 or u32(1124) & ~3):
            raise ValueError('Unsupported ext2 incompatible/read-only features')
        if self.blocks_count * self.block_size > len(self.data):
            raise ValueError('Truncated ext2 image')
        first_data_block = u32(1044)
        if first_data_block != (1 if self.block_size == 1024 else 0):
            raise ValueError('Invalid ext2 first data block')
        groups = math.ceil((self.blocks_count - first_data_block) / self.blocks_per_group)
        table_start = max(self.block_size, 2048)
        if (groups <= 0 or table_start + groups * 32 > len(self.data)
                or self.inodes_count > groups * self.inodes_per_group):
            raise ValueError('Invalid ext2 group geometry')
        self.inode_tables = [u32(table_start + index * 32 + 8) for index in range(groups)]
        if any(not 0 < block < self.blocks_count for block in self.inode_tables):
            raise ValueError('Invalid ext2 inode table')

    def _block(self, number):
        if not 0 < number < self.blocks_count:
            raise ValueError('Invalid ext2 block reference')
        return self.data[number * self.block_size:(number + 1) * self.block_size]

    def inode(self, number):
        if not 1 <= number <= self.inodes_count:
            raise ValueError('Invalid ext2 inode reference')
        group, index = divmod(number - 1, self.inodes_per_group)
        offset = self.inode_tables[group] * self.block_size + index * self.inode_size
        raw = self.data[offset:offset + self.inode_size]
        if len(raw) != self.inode_size:
            raise ValueError('Truncated ext2 inode')
        mode, uid = struct.unpack_from('<HH', raw)
        size, atime, ctime, mtime, dtime = struct.unpack_from('<5I', raw, 4)
        gid, links = struct.unpack_from('<HH', raw, 24)
        blocks, flags = struct.unpack_from('<II', raw, 28)
        if flags & 0x80000:  # extents are not ext2 block pointers
            raise ValueError('Extent inode is unsupported')
        if dtime:
            raise ValueError('Deleted inode in active directory tree')
        uid |= struct.unpack_from('<H', raw, 120)[0] << 16
        gid |= struct.unpack_from('<H', raw, 122)[0] << 16
        if stat.S_ISREG(mode):
            size |= struct.unpack_from('<I', raw, 108)[0] << 32
        # Linux ext2_iget uses i_block[0] for old dev_t, otherwise i_block[1].
        # Decode major/minor only; this does not establish a mounted st_dev.
        device = {}
        if stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
            old, new = struct.unpack_from('<II', raw, 40)
            major, minor = ((old >> 8) & 0xff, old & 0xff) if old else (
                (new >> 8) & 0xfff, (new & 0xff) | ((new >> 12) & 0xfff00))
            device = {'device_number': {'major': major, 'minor': minor},
                      'device_encoding': 'old' if old else 'new'}
        return {**device, 'inode': number, 'inode_file_offset': offset, 'mode': mode, 'uid': uid, 'gid': gid,
                'size': size, 'nlink': links, 'blocks_512': blocks, 'block_size': self.block_size,
                'image_times': {'atime': atime, 'mtime': mtime, 'ctime': ctime},
                'pointers': struct.unpack_from('<15I', raw, 40)}

    def _directory_data(self, inode):
        if inode['size'] > 16 * 1024 * 1024:
            raise ValueError('Directory exceeds research bound')
        def pointers(number, depth):
            if depth == 0:
                yield number
            else:
                for pointer in struct.unpack('<' + 'I' * (self.block_size // 4), self._block(number)):
                    if pointer:
                        yield from pointers(pointer, depth - 1)
                    else:
                        # A hole in a populated directory is unsupported.
                        yield 0
        needed = math.ceil(inode['size'] / self.block_size)
        chunks = []
        for slot, pointer in enumerate(inode['pointers']):
            if len(chunks) >= needed:
                break
            for number in pointers(pointer, max(0, slot - 11)):
                chunks.append(self._block(number))
                if len(chunks) == needed:
                    break
        if len(chunks) != needed:
            raise ValueError('Incomplete directory block list')
        return b''.join(chunks)[:inode['size']]

    def index(self):
        result, seen_directories = {}, set()
        def walk(number, path):
            inode = self.inode(number)
            result[path] = {key: value for key, value in inode.items() if key != 'pointers'}
            if not stat.S_ISDIR(inode['mode']):
                return
            if number in seen_directories:
                raise ValueError('Unexpected directory cycle/hard link')
            seen_directories.add(number)
            data = self._directory_data(inode)
            offset = 0
            while offset < len(data):
                if len(data) - offset < 8:
                    raise ValueError('Truncated ext2 directory entry')
                child, length, name_length, file_type = struct.unpack_from('<IHBB', data, offset)
                if (length < 8 or length % 4 or offset + length > len(data)
                        or offset % self.block_size + length > self.block_size
                        or name_length > length - 8):
                    raise ValueError('Malformed ext2 directory entry')
                name = data[offset + 8:offset + 8 + name_length].decode('ascii')
                if child and name not in ('.', '..'):
                    if not name or '/' in name or '\0' in name:
                        raise ValueError('Invalid ext2 filename')
                    child_path = path.rstrip('/') + '/' + name
                    if child_path in result:
                        raise ValueError('Duplicate ext2 directory name')
                    walk(child, child_path)
                offset += length
        walk(2, '/')
        return result
