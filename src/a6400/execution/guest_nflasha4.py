"""Read-only/observed-dump policy for the camera's `/dev/nflasha4` MPR node.

Evidence (E0305):
* `/dev/nflasha4` is block 252:4, raw MPR, 12,582,912 bytes; one read-only
  camera dump (`artifacts/hardware/mpr-readonly/nflasha4-12582912.bin`) with
  re-read equality and manifest identity.
* The first flash ioctl the original app issues is `0x80014123`. The a6400
  `emmc.ko` handler locks, reads EXT_CSD byte 0xB5 through
  `emmc_seq_get_erased_mem_cont` and copies it with `__put_user_1`; a direct
  read-only probe on the camera returned `0x00` (ERASED_MEM_CONT = 0x00).

This policy serves reads from that dump and only that one read-only ioctl byte.
It never fabricates partition content, never serves a write/erase and never
answers another ioctl; those remain explicit boundaries.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

PARTITION_SIZE = 12582912
ERASED_STATE_IOCTL = 0x80014123
IMAGE_RELATIVE_PATH = 'artifacts/hardware/mpr-readonly/nflasha4-12582912.bin'
MANIFEST_RELATIVE_PATH = 'artifacts/hardware/mpr-readonly/manifest.json'


class Nflasha4DumpError(RuntimeError):
    """Explicit boundary for an unsupported dump-policy operation."""


class Nflasha4Dump:
    """Hash-checked read-only view of the single captured MPR partition."""

    def __init__(self, image: bytes, erased_state_byte: int, *,
                 image_sha256: str | None = None,
                 evidence: dict | None = None,
                 expected_size: int = PARTITION_SIZE):
        if len(image) != expected_size:
            raise ValueError(
                f'MPR image must be exactly {expected_size} bytes, got {len(image)}')
        actual = hashlib.sha256(image).hexdigest()
        if image_sha256 is not None and actual != image_sha256:
            raise ValueError('MPR image sha256 does not match the recorded identity')
        self.image = bytes(image)
        self.size = expected_size
        self.image_sha256 = actual
        self.erased_state_byte = int(erased_state_byte) & 0xff
        self.evidence = dict(evidence or {})

    @classmethod
    def from_evidence(cls, root: str | Path) -> 'Nflasha4Dump':
        """Load the dump and the observed ioctl byte from the preserved evidence."""
        root = Path(root)
        manifest_path = root / MANIFEST_RELATIVE_PATH
        image_path = root / IMAGE_RELATIVE_PATH
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest.get('status') != 'complete':
            raise ValueError('MPR dump manifest is not complete; refusing partial content')
        if int(manifest.get('declared_size', -1)) != PARTITION_SIZE:
            raise ValueError('MPR dump manifest size does not match the partition identity')
        observation = manifest.get('erased_state_ioctl_observation') or {}
        result_hex = observation.get('result_hex')
        if not result_hex:
            raise ValueError('MPR erased-state ioctl observation missing from manifest')
        erased_state = int(result_hex, 16)
        image = image_path.read_bytes()
        return cls(image, erased_state, image_sha256=manifest.get('sha256'),
                   evidence={
                       'manifest': MANIFEST_RELATIVE_PATH,
                       'image': IMAGE_RELATIVE_PATH,
                       'ioctl': hex(ERASED_STATE_IOCTL),
                       'observed_result': f'0x{erased_state:02x}',
                       'observation': 'read-only camera probe; helper removed',
                   })

    def read(self, offset: int, count: int) -> bytes:
        if not isinstance(offset, int) or not isinstance(count, int):
            raise Nflasha4DumpError('nflasha4_dump_invalid_read_arguments')
        if offset < 0 or offset > self.size:
            raise Nflasha4DumpError(f'nflasha4_dump_offset_out_of_range:{offset}')
        if count < 0:
            raise Nflasha4DumpError('nflasha4_dump_negative_count')
        return self.image[offset:min(offset + count, self.size)]

    def ioctl_erased_state(self, cmd: int) -> int:
        if cmd != ERASED_STATE_IOCTL:
            raise Nflasha4DumpError(f'nflasha4_ioctl_not_supplied:0x{cmd:08x}')
        return self.erased_state_byte

    def flush_result(self, dirty: bool) -> int:
        """Answer fsync/fdatasync only when this model served no write on the fd.

        The dump policy never serves a write, writev or pwrite; therefore a
        flush of the modelled page state has nothing to write and returns 0.
        Any dirty/unknown state is an explicit boundary rather than a silent
        success.
        """
        if dirty:
            raise Nflasha4DumpError('nflasha4_write_flush_not_supplied')
        return 0
