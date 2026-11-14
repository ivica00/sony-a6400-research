"""CXD90045 machine-ID and ATAGS boot contract recovery (offline, E0416).

The updater and main kernels are raw ARM images: file offset 0 is the physical load
address ``0x00108000`` and the virtual base is ``0x00108000 + 0x60000000 =
0x60108000`` (proved by the live/updater kallsyms ``_stext``/``linux_banner``).
Both kernels carry one ``struct machine_desc`` in ``.arch.info.init`` whose first two
words are the observed machine ID and the ``ARM-CXD900X0`` name pointer:

* nflasha3 raw kernel: ID ``0x00000DA9`` (3497), struct at file offset ``0x3A85F4``
  (virtual ``0x604B05F4``); the words after the name resolve to
  ``cxd900x0_fixup`` / ``cxd900x0_map_io`` / ``cxd900x0_init_irq`` / a timer object /
  ``cxd900x0_init``.
* nflasha1 updater kernel (decompressed zImage): ID ``0x00000DA9``, name at file
  offset ``0x2D4D11`` referenced from struct file offset ``0x331FF8``.

The ATAGS block address is the third value of nflasha1 ``boot/loadaddr.txt``
(``0x00103000``); the tag list itself is not present in any read-only dump, so it is
reconstructed from the standard ARM layout plus the updater ``boot/kemco.txt`` cmdline
(memory banks from the observed ``mem=`` options).  This module is pure offline
analysis: it never writes images and never claims the loader emitted these exact bytes.
"""
from __future__ import annotations

import struct

from src.a6400.execution.arm_atags import (DEFAULT_BOOT_PARAMS, atags_receipt,
                                           build_atags, parse_mem_parameters)
from src.a6400.execution.nflasha_boot_set import (KERNEL_PAGE_OFFSET,
                                                  NflashaBootSet)

MACHINE_NAME = b'ARM-CXD900X0'
UPDATER_LOADADDR = {'kernel_load': 0x00108000, 'initrd_load': 0x00700000,
                    'boot_params': 0x00103000}
INITRD_LOAD = UPDATER_LOADADDR['initrd_load']
BOOT_PARAMS = UPDATER_LOADADDR['boot_params']


class MachineContractError(RuntimeError):
    """The machine descriptor or boot contract could not be established."""


def _find_all(data: bytes, needle: bytes) -> list[int]:
    hits = []
    start = 0
    while True:
        index = data.find(needle, start)
        if index < 0:
            return hits
        hits.append(index)
        start = index + 1


class MachineDescriptor:
    """Recovered ``struct machine_desc`` identity of one raw ARM kernel image."""

    def __init__(self, machine_id: int, name: str, *, image_sha256: str,
                 virtual_base: int, name_file_offset: int,
                 struct_file_offset: int, pointer_words: list[int],
                 name_offset_in_struct: int):
        self.machine_id = machine_id
        self.name = name
        self.image_sha256 = image_sha256
        self.virtual_base = virtual_base
        self.name_file_offset = name_file_offset
        self.struct_file_offset = struct_file_offset
        self.pointer_words = pointer_words
        self.name_offset_in_struct = name_offset_in_struct

    def as_dict(self) -> dict:
        return {
            'machine_id': self.machine_id,
            'machine_id_hex': f'0x{self.machine_id:08x}',
            'name': self.name,
            'image_sha256': self.image_sha256,
            'virtual_base': self.virtual_base,
            'name_file_offset': self.name_file_offset,
            'struct_file_offset': self.struct_file_offset,
            'struct_vaddr': self.virtual_base + self.struct_file_offset,
            'name_vaddr': self.virtual_base + self.name_file_offset,
            'name_offset_in_struct': self.name_offset_in_struct,
            'pointer_words': [{'file_offset': offset, 'value': value}
                              for offset, value in self.pointer_words],
        }


def recover_machine_descriptor(image: bytes, *, virtual_base: int,
                               image_sha256: str,
                               machine_name: bytes = MACHINE_NAME,
                               max_machine_id: int = 0x4000) -> MachineDescriptor:
    """Locate the machine descriptor by its name pointer and validate the ID word.

    The layout used here is the observed subset: ``[+0] = machine ID`` and
    ``[+4] = name pointer``.  Additional struct words that point into the image are
    returned as evidence; no unknown field is interpreted.
    """
    name_offset = image.find(machine_name)
    if name_offset < 0:
        raise MachineContractError(f'machine name {machine_name!r} not found')
    name_vaddr = virtual_base + name_offset
    needle = struct.pack('<I', name_vaddr)
    references = _find_all(image, needle)
    candidates = []
    for reference in references:
        struct_offset = reference - 4
        if struct_offset < 0:
            continue
        machine_id = struct.unpack_from('<I', image, struct_offset)[0]
        if not 0 < machine_id < max_machine_id:
            continue
        # Collect the following words that point into the image (text/data evidence).
        pointer_words = []
        for index in range(1, 16):
            word_offset = struct_offset + index * 4
            if word_offset + 4 > len(image):
                break
            value = struct.unpack_from('<I', image, word_offset)[0]
            if virtual_base <= value < virtual_base + len(image):
                pointer_words.append((word_offset, value))
        candidates.append((struct_offset, machine_id, pointer_words))
    if not candidates:
        raise MachineContractError('no plausible machine descriptor (ID word) found')
    if len(candidates) > 1:
        distinct = {machine_id for _, machine_id, _ in candidates}
        if len(distinct) > 1:
            raise MachineContractError(
                f'ambiguous machine descriptors with different IDs: {sorted(distinct)}')
    struct_offset, machine_id, pointer_words = candidates[0]
    return MachineDescriptor(machine_id, machine_name.decode('ascii'),
                             image_sha256=image_sha256, virtual_base=virtual_base,
                             name_file_offset=name_offset,
                             struct_file_offset=struct_offset,
                             pointer_words=pointer_words,
                             name_offset_in_struct=4)


class UpdaterBootContract:
    """Reconstructed updater/main boot contract (machine ID, load addresses, ATAGS)."""

    def __init__(
        self,
        boot_set: NflashaBootSet,
        *,
        cmdline_extra: str = '',
        config_boot_set: NflashaBootSet | None = None,
    ):
        self.boot_set = boot_set
        self.config_boot_set = config_boot_set or boot_set
        self.cmdline_extra = cmdline_extra.strip()
        load = self.config_boot_set.load_addresses()
        if load is None:
            raise MachineContractError(
                f'{self.config_boot_set.label} boot set has no boot/loadaddr.txt'
            )
        self.load_addresses = load
        raw = boot_set.raw_kernel_image()
        sha = boot_set.kernel_file().sha256
        # The decompressed image hash differs from the stored zImage hash; the
        # identity of the zImage stays the boot-set contract.
        self.machine = recover_machine_descriptor(
            raw, virtual_base=KERNEL_PAGE_OFFSET + load['kernel_load'],
            image_sha256=sha)
        self.raw_kernel = raw
        cmdline = self.config_boot_set.read('boot/kemco.txt').decode('latin1')
        self.cmdline = ' '.join(line.strip() for line in cmdline.splitlines()
                                if line.strip())
        # kemco.txt terminates its parameter list with '*'; drop that token so
        # runner-side overrides (e.g. init=/bin/ash) are actually parsed.
        self.cmdline = self.cmdline.rstrip().rstrip('*').rstrip()
        # Sony boot-params contract at 0x00103000 (E0425): setup_arch validates
        # strncmp("kemco", ptr, 5) and then parses the string from ptr+5, so the
        # payload is the raw kemco.txt text itself (starting with "kemco") with
        # only the init= token rewritten; '*' and CR/LF are handled by the kernel.
        import re as _re
        self.kemco_cmdline = ' '.join(line.strip() for line in cmdline.splitlines()
                                      if line.strip()).rstrip().rstrip('*').rstrip()
        sony = self.kemco_cmdline
        if self.cmdline_extra:
            extra = self.cmdline_extra
            if 'init=' in extra:
                sony = _re.sub(r'(^|\s)init=\S+', ' ', sony)
            if 'amba2.console=' in extra:
                sony = _re.sub(r'(^|\s)amba2\.console=\S+', ' ', sony)
            sony = (sony + ' ' + extra).strip()
        self.sony_cmdline = sony
        self.sony_payload = sony.encode('latin1') + b'\x00'
        if self.cmdline_extra:
            # Kernel COMMAND_LINE_SIZE in this build truncates long cmdlines
            # (~768 bytes observed), so prepend overrides instead of appending
            # them after the ~810-byte kemco line; an init= override also
            # replaces the existing init= token (last token would otherwise win).
            extra = self.cmdline_extra
            if 'init=' in extra:
                import re as _re
                self.cmdline = _re.sub(r'(^|\s)init=\S+', ' ', self.cmdline)
            if 'amba2.console=' in extra:
                import re as _re
                self.cmdline = _re.sub(r'(^|\s)amba2\.console=\S+', ' ', self.cmdline)
            self.cmdline = (extra + ' ' + self.cmdline).strip()
        self.memory = parse_mem_parameters(self.cmdline)
        self.banks = [(record['start'], record['size']) for record in self.memory
                      if not record.get('reserved')]
        self.reservations = [record for record in self.memory if record.get('reserved')]
        self.initrd = (
            boot_set.initrd_file().data
            if hasattr(boot_set, 'initrd_file')
            else boot_set.read('boot/initrd.img')
        )
        self.atags = build_atags(self.cmdline, self.banks,
                                 boot_params=load['boot_params'])
        self.atags_receipt = atags_receipt(self.atags, base=load['boot_params'])

    def as_dict(self) -> dict:
        return {
            'machine': self.machine.as_dict(),
            'load_addresses': dict(self.load_addresses),
            'kernel_raw_bytes': len(self.raw_kernel),
            'initrd_bytes': len(self.initrd),
            'cmdline': self.cmdline,
            'memory_banks': [list(bank) for bank in self.banks],
            'reserved_regions': self.reservations,
            'atags': self.atags_receipt,
        }

    def verify(self) -> dict:
        report = self.as_dict()
        report['checks'] = {
            'machine_id_nonzero': 0 < self.machine.machine_id < 0x4000,
            'boot_params_is_0x00103000': self.load_addresses['boot_params'] == BOOT_PARAMS,
            'kernel_load_is_0x00108000': (self.load_addresses['kernel_load']
                                          == UPDATER_LOADADDR['kernel_load']),
            'initrd_load_is_0x00700000': (self.load_addresses['initrd_load']
                                          == UPDATER_LOADADDR['initrd_load']),
            'atags_has_two_memory_banks': len(self.atags_receipt['memory_banks']) == 2,
            'cmdline_has_ttyAM0': 'console=ttyAM0,115200n8' in self.cmdline,
            'raw_kernel_starts_with_arm_head': (int.from_bytes(
                self.raw_kernel[0:4], 'little') == 0xE321F0D3),
        }
        return report
