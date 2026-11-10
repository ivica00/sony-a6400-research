"""Read-only FAT12/16/32 image reader for the camera's vfat partitions.

Bounded, read-only parsing of the preserved nflasha1 dump. No write path, no
mount side effects and no host filesystem access: the image bytes are supplied
by the caller, and lookups stay inside that byte string.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

NFLASHA1_SIZE = 8323072
NFLASHA1_IMAGE = 'artifacts/hardware/nflasha1-readonly/nflasha1-8323072.bin'
NFLASHA1_MANIFEST = 'artifacts/hardware/nflasha1-readonly/manifest.json'


class VfatError(RuntimeError):
    """Explicit boundary for an unsupported or invalid vfat state."""


class VfatEntry:
    __slots__ = ('name', 'long_name', 'attr', 'size', 'start_cluster', 'is_dir')

    def __init__(self, name, long_name, attr, size, start_cluster):
        self.name = name
        self.long_name = long_name
        self.attr = attr
        self.size = size
        self.start_cluster = start_cluster
        self.is_dir = bool(attr & 0x10)

    @property
    def display_name(self):
        return self.long_name or self.name

    def __repr__(self):
        return f'<VfatEntry {self.display_name!r} dir={self.is_dir} size={self.size}>'


class VfatImage:
    """FAT12/16/32 read-only view; supports the camera's 16 KiB-cluster nflasha1."""

    def __init__(self, image: bytes, *, expected_size: int | None = NFLASHA1_SIZE,
                 image_sha256: str | None = None, evidence: dict | None = None):
        if expected_size is not None and len(image) != expected_size:
            raise ValueError(f'vfat image must be {expected_size} bytes, got {len(image)}')
        actual = hashlib.sha256(image).hexdigest()
        if image_sha256 is not None and actual != image_sha256:
            raise ValueError('vfat image sha256 does not match the recorded identity')
        self.image = bytes(image)
        self.image_sha256 = actual
        self.evidence = dict(evidence or {})
        self._parse_bpb()

    def _parse_bpb(self):
        image = self.image
        if image[0x1fe:0x200] != b'\x55\xaa':
            raise VfatError('vfat_missing_boot_signature')
        self.bytes_per_sector = struct.unpack_from('<H', image, 0x0b)[0]
        self.sectors_per_cluster = image[0x0d]
        reserved = struct.unpack_from('<H', image, 0x0e)[0]
        fats = image[0x10]
        root_entries = struct.unpack_from('<H', image, 0x11)[0]
        total16 = struct.unpack_from('<H', image, 0x13)[0]
        self.fat_size16 = struct.unpack_from('<H', image, 0x16)[0]
        total32 = struct.unpack_from('<I', image, 0x20)[0]
        fat_size32 = struct.unpack_from('<I', image, 0x24)[0]
        if self.bytes_per_sector not in (512, 1024, 2048, 4096):
            raise VfatError('vfat_unsupported_sector_size')
        if self.sectors_per_cluster == 0:
            raise VfatError('vfat_unsupported_cluster_size')
        self.total_sectors = total16 or total32
        self.fat_size = self.fat_size16 or fat_size32
        self.root_dir_sectors = (root_entries * 32 + self.bytes_per_sector - 1) // self.bytes_per_sector
        self.fat_start = reserved * self.bytes_per_sector
        self.root_dir_start = (reserved + fats * self.fat_size) * self.bytes_per_sector
        self.data_start = self.root_dir_start + self.root_dir_sectors * self.bytes_per_sector
        if self.fat_size == 0 or self.total_sectors == 0 or fats == 0:
            raise VfatError('vfat_incomplete_bpb')
        data_sectors = self.total_sectors - (self.data_start // self.bytes_per_sector)
        self.cluster_count = data_sectors // self.sectors_per_cluster
        if self.cluster_count < 4085:
            self.fat_type = 12
        elif self.cluster_count < 65525:
            self.fat_type = 16
        else:
            self.fat_type = 32
        if self.fat_type == 32:
            self.root_cluster = struct.unpack_from('<I', image, 0x2c)[0]
        self.cluster_bytes = self.sectors_per_cluster * self.bytes_per_sector

    # --- layout helpers -------------------------------------------------
    def _cluster_offset(self, cluster):
        return self.data_start + (cluster - 2) * self.cluster_bytes

    def _next_cluster(self, cluster):
        fat = self.image
        if self.fat_type == 12:
            offset = self.fat_start + cluster + cluster // 2
            if offset + 1 >= len(fat):
                raise VfatError('vfat_fat_read_out_of_range')
            value = struct.unpack_from('<H', fat, offset)[0]
            if cluster & 1:
                value >>= 4
            return value & 0x0fff
        if self.fat_type == 16:
            offset = self.fat_start + cluster * 2
            return struct.unpack_from('<H', fat, offset)[0]
        offset = self.fat_start + cluster * 4
        return struct.unpack_from('<I', fat, offset)[0]

    def _cluster_chain(self, start, limit=1 << 20):
        chain = []
        cluster = start
        seen = set()
        while 2 <= cluster < self.cluster_count + 2 and cluster not in seen:
            seen.add(cluster)
            chain.append(cluster)
            if len(chain) > limit:
                raise VfatError('vfat_cluster_chain_limit')
            nxt = self._next_cluster(cluster)
            if self.fat_type == 12 and nxt >= 0xff8:
                break
            if self.fat_type == 16 and nxt >= 0xfff8:
                break
            if self.fat_type == 32 and nxt >= 0x0ffffff8:
                break
            if nxt == 0:
                break
            cluster = nxt
        return chain

    def _read_chain(self, start, size=None):
        data = bytearray()
        for cluster in self._cluster_chain(start):
            offset = self._cluster_offset(cluster)
            data.extend(self.image[offset:offset + self.cluster_bytes])
            if size is not None and len(data) >= size:
                break
        return bytes(data if size is None else data[:size])

    # --- directory parsing ---------------------------------------------
    def _directory_bytes(self, entry_or_root):
        if entry_or_root is None:  # root directory
            if self.fat_type == 32:
                return self._read_chain(self.root_cluster)
            start = self.root_dir_start
            end = start + self.root_dir_sectors * self.bytes_per_sector
            return self.image[start:end]
        return self._read_chain(entry_or_root.start_cluster)

    def list_dir(self, entry_or_root=None):
        data = self._directory_bytes(entry_or_root)
        entries = []
        lfn = []
        for offset in range(0, len(data) - 31, 32):
            raw = data[offset:offset + 32]
            first = raw[0]
            if first == 0x00:
                break
            if first == 0xe5:
                lfn = []
                continue
            attr = raw[11]
            if attr == 0x0f:  # long file name component
                part = raw[1:11] + raw[14:26] + raw[28:32]
                chunks = [part[i:i + 2] for i in range(0, len(part), 2)]
                chars = []
                for chunk in chunks:
                    if chunk in (b'\x00\x00', b'\xff\xff'):
                        continue
                    chars.append(chunk.decode('utf-16-le', errors='ignore'))
                lfn.append(''.join(chars))
                continue
            if attr & 0x08:  # volume label
                lfn = []
                continue
            base = raw[0:8].decode('latin-1').rstrip(' ')
            ext = raw[8:11].decode('latin-1').rstrip(' ')
            name = base + ('.' + ext if ext else '')
            long_name = ''.join(reversed(lfn)) if lfn else None
            lfn = []
            size = struct.unpack_from('<I', raw, 28)[0]
            start = struct.unpack_from('<H', raw, 26)[0]
            if self.fat_type == 32:
                start |= struct.unpack_from('<H', raw, 20)[0] << 16
            entries.append(VfatEntry(name, long_name, attr, size, start))
        return entries

    def read_file(self, entry):
        if entry.is_dir:
            raise VfatError('vfat_read_on_directory')
        return self._read_chain(entry.start_cluster, entry.size) if entry.size else b''

    def walk(self, entry=None, prefix=''):
        """Yield (relative_path, entry) for files and directories below entry."""
        for child in self.list_dir(entry):
            if child.name in ('.', '..'):
                continue
            path = f'{prefix}/{child.display_name}'.lstrip('/')
            yield path, child
            if child.is_dir:
                yield from self.walk(child, path)

    @classmethod
    def from_evidence(cls, root: str | Path, *,
                      manifest_relative: str = NFLASHA1_MANIFEST,
                      image_relative: str = NFLASHA1_IMAGE,
                      expected_size: int = NFLASHA1_SIZE) -> 'VfatImage':
        root = Path(root)
        manifest = json.loads((root / manifest_relative).read_text(encoding='utf-8'))
        if manifest.get('status') != 'complete':
            raise ValueError('vfat dump manifest is not complete; refusing partial content')
        if int(manifest.get('declared_size', -1)) != expected_size:
            raise ValueError('vfat dump manifest size does not match the partition identity')
        image = (root / image_relative).read_bytes()
        return cls(image, expected_size=expected_size, image_sha256=manifest.get('sha256'),
                   evidence={'manifest': manifest_relative, 'image': image_relative})
