"""Read-only nflasha boot-set unpacking (normal boot set, nflasha3, and nflasha1).

The a6400 keeps two boot sets:

* ``/dev/nflasha3`` (252:3, 48 MiB vfat, mounted ``/system`` at runtime) is the
  main boot set: raw ARM kernel image ``vmlinux.bin`` + ext2 ``initrd.img`` plus
  camera payloads (``sabin/``, ``av-cam.bin``, ...).  E0414 dumped it read-only;
  this module parses the dump through :class:`~src.a6400.execution.guest_vfat.VfatImage`.
* ``/dev/nflasha1`` (252:1, 8,323,072 B vfat) is the updater boot set:
  zImage ``boot/vmlinux.bin`` + cramfs ``boot/initrd.img`` + ``boot/kemco.txt``
  + ``boot/loadaddr.txt`` (``0x00108000,0x00700000,0x00103000``).

Load-address contract: on this Sony CE Linux 3.0.27 build the kernel physical
load address is ``0x00108000`` (also the ``Kernel text`` start in
``/proc/iomem``) and the kernel virtual address is ``physical + 0x60000000``:
the live kallsyms decode of the same image reports ``_stext = 0x60108160`` and
``linux_banner = 0x603c8028`` (= ``0x60108000 + file offset 0x2c0028``).
``0x00700000`` is the initrd load address (``initrd=0x700000,8M`` in the live
cmdline) and ``0x00103000`` is the boot-parameter block address.

Read-only: bytes are only read from the local dumps, never written.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from src.a6400.execution.guest_vfat import VfatImage

DUMP_DIR = 'artifacts/dumps/a6400-nflasha-readonly'
MANIFEST = 'manifest.json'

#: Boot-set partition identities from the 2026-11-12 read-only dumps (E0414).
BOOT_SETS = {
    'nflasha1': {
        'image': 'nflasha1-8323072.bin',
        'declared_size': 8323072,
        'sha256': 'b264e1e61bde1808dbe4b14df834933040af6a48f90e89bb08338ca07515451f',
        'role': 'updater boot set (zImage + cramfs updater ramfs)',
    },
    'nflasha3': {
        'image': 'nflasha3-50331648.bin',
        'declared_size': 50331648,
        'sha256': 'cd4178d4518e13c64630d9de62fdbfbc05c0774f1ee8291f9fc56998910719a6',
        'role': 'main boot set (raw ARM kernel + ext2 initrd + camera payloads)',
    },
}

KERNEL_PHYSICAL_LOAD = 0x00108000
INITRD_LOAD = 0x00700000
BOOT_PARAMS = 0x00103000
KERNEL_PAGE_OFFSET = 0x60000000
#: Kernel virtual base of the nflasha3 raw image (0x60000000 + 0x00108000).
KERNEL_VIRTUAL_BASE = KERNEL_PAGE_OFFSET + KERNEL_PHYSICAL_LOAD

ZIMAGE_MAGIC = 0x016F2818
EXTLINUX_BOOT_FLAG = 0x016F2818
ARM_IMAGE_FIRST_WORD = 0xE321F0D3  # msr cpsr_c, #0xd3 (ARM kernel head.S)
CRAMFS_MAGIC_LE = 0x28CD3D45
EXT2_MAGIC = b'\x53\xef'


class BootSetError(ValueError):
    """The boot-set dump or its contents do not match the declared contract."""


def zimage_header(data: bytes) -> dict:
    """Parse the observed ARM zImage header fields."""
    if len(data) < 0x30:
        raise BootSetError('zImage header truncated')
    magic = int.from_bytes(data[0x24:0x28], 'little')
    if magic != ZIMAGE_MAGIC:
        raise BootSetError('ARM zImage magic 0x016F2818 not found at +0x24')
    start = int.from_bytes(data[0x28:0x2C], 'little')
    end = int.from_bytes(data[0x2C:0x30], 'little')
    gzip_offset = data.find(b'\x1f\x8b\x08')
    if gzip_offset < 0:
        raise BootSetError('no gzip payload in the zImage')
    return {'magic': magic, 'start': start, 'end': end, 'gzip_offset': gzip_offset,
            'bytes': len(data)}


def decompress_zimage(data: bytes) -> bytes:
    """Return the raw (uncompressed) kernel image carried by an ARM zImage.

    Bounded, offline, exact: the gzip stream is decompressed with ``zlib`` and the
    result must start with the observed ARM kernel head word.  No bytes are invented.
    """
    import zlib
    header = zimage_header(data)
    payload = data[header['gzip_offset']:]
    try:
        raw = zlib.decompress(payload, 16 + zlib.MAX_WBITS)
    except zlib.error as error:
        raise BootSetError(f'zImage gzip payload does not decompress: {error}') from error
    if len(raw) < 0x1000:
        raise BootSetError('decompressed kernel image too small')
    if int.from_bytes(raw[0:4], 'little') != ARM_IMAGE_FIRST_WORD:
        raise BootSetError('decompressed image does not start with the ARM kernel head')
    return raw


def parse_loadaddr(text: str) -> dict:
    """Parse ``boot/loadaddr.txt`` (``0x00108000,0x00700000,0x00103000``)."""
    fields = [item.strip() for item in text.strip().split(',')]
    if len(fields) != 3:
        raise BootSetError(f'loadaddr.txt: expected 3 comma-separated values, got {len(fields)}')
    try:
        values = [int(item, 0) for item in fields]
    except ValueError as error:
        raise BootSetError(f'loadaddr.txt: non-numeric value: {error}') from error
    return {'kernel_load': values[0], 'initrd_load': values[1], 'boot_params': values[2]}


def detect_image_format(data: bytes) -> str:
    """Classify a boot image by its observed header (no guessing beyond the bytes)."""
    if len(data) >= 0x28 and int.from_bytes(data[0x24:0x28], 'little') == ZIMAGE_MAGIC:
        return 'zimage'
    if len(data) >= 4 and int.from_bytes(data[0:4], 'little') == ARM_IMAGE_FIRST_WORD:
        return 'raw_arm_kernel'
    if len(data) >= 4 and int.from_bytes(data[0:4], 'little') == CRAMFS_MAGIC_LE:
        return 'cramfs'
    if len(data) >= 0x43a and data[0x438:0x43a] == EXT2_MAGIC:
        return 'ext2'
    if data[:4] == b'\x7fELF':
        return 'elf'
    return 'unknown'


def detect_kernel_format(data: bytes) -> str:
    return detect_image_format(data)


class BootFile:
    __slots__ = ('path', 'size', 'sha256', '_reader')

    def __init__(self, path: str, size: int, sha256: str, reader):
        self.path = path
        self.size = size
        self.sha256 = sha256
        self._reader = reader

    @property
    def data(self) -> bytes:
        return self._reader()

    def as_dict(self) -> dict:
        return {'path': self.path, 'size': self.size, 'sha256': self.sha256}


class NflashaBootSet:
    """Read-only boot-set view backed by a hash-checked E0414 dump."""

    def __init__(self, label: str, image: bytes, identity: dict):
        self.label = label
        self.identity = identity
        self.vfat = VfatImage(image, expected_size=identity['declared_size'],
                              image_sha256=identity['sha256'])
        self.files: dict[str, BootFile] = {}
        for path, entry in self.vfat.walk():
            if entry.is_dir:
                continue
            data = self.vfat.read_file(entry)
            self.files[path] = BootFile(
                path, entry.size, hashlib.sha256(data).hexdigest(),
                (lambda data=data: data))

    @classmethod
    def from_evidence(cls, root: str | Path, label: str) -> 'NflashaBootSet':
        if label not in BOOT_SETS:
            raise BootSetError(f'unknown boot set {label!r}')
        root = Path(root)
        directory = root / DUMP_DIR
        manifest_path = directory / MANIFEST
        image_path = directory / BOOT_SETS[label]['image']
        if not manifest_path.is_file() or not image_path.is_file():
            raise BootSetError('boot-set dump not present under the evidence root')
        import json
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest.get('status', '') not in ('', 'complete') and \
                all(device.get('status') != 'complete' for device in
                    manifest.get('devices', {}).values()):
            raise BootSetError('dump manifest is not complete')
        image = image_path.read_bytes()
        identity = BOOT_SETS[label]
        if len(image) != identity['declared_size']:
            raise BootSetError('boot-set image size does not match the declared identity')
        if hashlib.sha256(image).hexdigest() != identity['sha256']:
            raise BootSetError('boot-set image sha256 does not match the declared identity')
        return cls(label, image, identity)

    def read(self, path: str) -> bytes:
        if path not in self.files:
            raise BootSetError(f'{path!r} not present in {self.label}')
        return self.files[path].data

    def load_addresses(self) -> dict | None:
        """Parse ``boot/loadaddr.txt`` when this set carries one (nflasha1)."""
        if 'boot/loadaddr.txt' not in self.files:
            return None
        return parse_loadaddr(self.read('boot/loadaddr.txt').decode('ascii'))

    def kernel_file(self) -> BootFile:
        candidates = [path for path in self.files
                      if path.endswith('vmlinux.bin') or path.endswith('kernel.img')]
        if len(candidates) != 1:
            raise BootSetError(f'expected one kernel image in {self.label}, found {candidates}')
        return self.files[candidates[0]]

    def initrd_file(self) -> BootFile:
        candidates = [path for path in self.files if path.endswith('initrd.img')]
        if len(candidates) != 1:
            raise BootSetError(f'expected one initrd image in {self.label}, found {candidates}')
        return self.files[candidates[0]]

    def raw_kernel_image(self) -> bytes:
        """Kernel bytes as the kernel expects them in RAM (zImage decompressed)."""
        kernel = self.kernel_file().data
        if detect_image_format(kernel) == 'zimage':
            return decompress_zimage(kernel)
        return kernel

    def classified(self) -> dict:
        result = {}
        for path, boot_file in sorted(self.files.items()):
            result[path] = {
                'size': boot_file.size,
                'sha256': boot_file.sha256,
                'format': detect_image_format(boot_file.data),
            }
        return result

    def summary(self) -> dict:
        kernel = self.kernel_file()
        initrd = self.initrd_file()
        load = self.load_addresses()
        return {
            'label': self.label,
            'role': self.identity['role'],
            'image_sha256': self.identity['sha256'],
            'files': self.classified(),
            'kernel': {'path': kernel.path, 'bytes': kernel.size,
                       'sha256': kernel.sha256,
                       'format': detect_image_format(kernel.data)},
            'initrd': {'path': initrd.path, 'bytes': initrd.size,
                       'sha256': initrd.sha256,
                       'format': detect_image_format(initrd.data)},
            'load_addresses': load,
            'kernel_virtual_base': (KERNEL_VIRTUAL_BASE if load is None else
                                    KERNEL_PAGE_OFFSET + load['kernel_load']),
        }
