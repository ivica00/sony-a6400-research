"""Kernel-backed mapping for the Unicorn USB/descriptor emulator (offline).

The live nflasha3 ``vmlinux.bin`` (4,085,888 B, SHA-256 ``d7a9ae09…``) is a raw
ARM kernel image: file offset 0 is the kernel's physical load address
``0x00108000`` and the kernel virtual address is ``physical + 0x60000000`` (the
page offset used by this Sony CE Linux build).  The identity is proven by the
live kallsyms decode of the same image: ``_stext = 0x60108160``,
``linux_banner = 0x603c8028`` (= ``0x60108000 + 0x2c0028``, where the banner
string sits in the file) and ``_etext = 0x6048d024`` (matching the
``/proc/iomem`` ``Kernel text`` end ``0x0048d023``).

This module maps a hash-checked kernel image at its exact virtual base and
resolves the original kallsyms table, so a kernel C module test (E0407b-1
family) can run against the live kernel's real text/data layout instead of a
hand-built placeholder.  It never writes images, never patches kernel code and
does not claim that a mapped image is a booted kernel.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

KERNEL_IMAGE_BYTES = 4085888
KERNEL_IMAGE_SHA256 = 'd7a9ae09d2195c1b5151e60f3ff1344715b619631cfad608d9a5fcf7a876c618'
KERNEL_PHYSICAL_LOAD = 0x00108000
KERNEL_PAGE_OFFSET = 0x60000000
KERNEL_VIRTUAL_BASE = KERNEL_PAGE_OFFSET + KERNEL_PHYSICAL_LOAD
ARM_IMAGE_FIRST_WORD = 0xE321F0D3  # msr cpsr_c, #0xd3 in the ARM kernel head

PAGE = 0x1000
UC_PROT_READ = 1
UC_PROT_WRITE = 2
UC_PROT_EXEC = 4

#: Symbols used to validate the mapping against the observed kernel image.
VALIDATION_SYMBOLS = ('_stext', '_etext', 'linux_banner')


class KernelBackingError(RuntimeError):
    """The kernel image, symbols or mapping do not match the observed layout."""


def _align_up(value: int, alignment: int = PAGE) -> int:
    return (value + alignment - 1) // alignment * alignment


class KernelSymbolTable:
    """Original kernel symbols decoded from the image's kallsyms tables."""

    def __init__(self, symbols: dict[str, int], *, source_sha256: str | None = None,
                 duplicate_names: int = 0):
        if not symbols:
            raise KernelBackingError('empty kernel symbol table')
        self.symbols = dict(symbols)
        self.source_sha256 = source_sha256
        self.duplicate_names = duplicate_names
        self._ordered = sorted(self.symbols.items(), key=lambda item: item[1])

    @classmethod
    def from_kallsyms(cls, image: bytes, *, source_sha256: str | None = None) -> 'KernelSymbolTable':
        from tools.research.decode_kernel_kallsyms import decode
        result = decode(image)
        symbols: dict[str, int] = {}
        duplicates = 0
        for symbol in result['symbols']:
            # kallsyms can repeat a local name across translation units; the
            # first (lowest-address) entry is kept and the duplication is counted.
            if symbol['name'] in symbols:
                duplicates += 1
                continue
            symbols[symbol['name']] = symbol['address']
        return cls(symbols, source_sha256=source_sha256, duplicate_names=duplicates)

    def __len__(self) -> int:
        return len(self.symbols)

    def address(self, name: str) -> int:
        try:
            return self.symbols[name]
        except KeyError as error:
            raise KernelBackingError(f'kernel symbol {name!r} not present') from error

    def names_matching(self, fragment: str, limit: int = 32) -> list[str]:
        if limit <= 0:
            raise KernelBackingError('positive limit required')
        return [name for name in self.symbols if fragment in name][:limit]

    def next_address(self, address: int) -> int | None:
        for _, candidate in self._ordered:
            if candidate > address:
                return candidate
        return None

    def span(self, name: str, limit: int = 256) -> int:
        """Bytes available from a symbol up to the next symbol (bounded)."""
        address = self.address(name)
        next_address = self.next_address(address)
        if next_address is None:
            return limit
        return min(next_address - address, limit)


class KernelImage:
    """Hash-checked raw ARM kernel image with its observed virtual layout."""

    def __init__(self, data: bytes, *, virtual_base: int = KERNEL_VIRTUAL_BASE,
                 sha256: str | None = None, source: str | None = None):
        if len(data) < 0x1000:
            raise KernelBackingError('kernel image too small')
        if int.from_bytes(data[0:4], 'little') != ARM_IMAGE_FIRST_WORD:
            raise KernelBackingError('image does not start with the observed ARM kernel entry '
                                     '(msr cpsr_c, #0xd3)')
        self.data = data
        self.virtual_base = virtual_base
        self.virtual_end = virtual_base + len(data)
        self.sha256 = sha256 or hashlib.sha256(data).hexdigest()
        self.source = source

    @classmethod
    def from_path(cls, path: str | Path, *, expected_sha256: str | None = None,
                  virtual_base: int = KERNEL_VIRTUAL_BASE,
                  expected_size: int | None = None) -> 'KernelImage':
        raw = Path(path).read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if expected_sha256 is not None and sha != expected_sha256:
            raise KernelBackingError('kernel image identity mismatch')
        if expected_size is not None and len(raw) != expected_size:
            raise KernelBackingError('kernel image size mismatch')
        return cls(raw, virtual_base=virtual_base, sha256=sha, source=str(path))

    def offset_of(self, vaddr: int, size: int = 1) -> int:
        if not self.virtual_base <= vaddr < self.virtual_end:
            raise KernelBackingError(f'address 0x{vaddr:08x} outside the mapped kernel image')
        offset = vaddr - self.virtual_base
        if offset + size > len(self.data):
            raise KernelBackingError('read crosses the kernel image end')
        return offset

    def bytes_at(self, vaddr: int, size: int) -> bytes:
        offset = self.offset_of(vaddr, size)
        return self.data[offset:offset + size]

    def map_into(self, uc, *, text_end: int | None = None) -> list[dict]:
        """Map the image read-only-text/read-write-data at its virtual base.

        ``uc`` is a ``unicorn.Uc`` (ARM).  ``text_end`` (usually ``_etext``)
        splits an R+X text mapping from an R+W data mapping; without it the
        whole image is mapped R+X.
        """
        ranges = []
        base = self.virtual_base & ~(PAGE - 1)
        end = _align_up(self.virtual_end)
        text_limit = min(end, _align_up(text_end)) if text_end else end
        if text_limit > base:
            uc.mem_map(base, text_limit - base, UC_PROT_READ | UC_PROT_EXEC)
            ranges.append({'start': base, 'end': text_limit,
                           'prot': UC_PROT_READ | UC_PROT_EXEC, 'role': 'kernel text'})
        if end > text_limit:
            uc.mem_map(text_limit, end - text_limit, UC_PROT_READ | UC_PROT_WRITE)
            ranges.append({'start': text_limit, 'end': end,
                           'prot': UC_PROT_READ | UC_PROT_WRITE, 'role': 'kernel data'})
        uc.mem_write(self.virtual_base, self.data)
        return ranges

    def banner_offset(self) -> int | None:
        index = self.data.find(b'Linux version')
        return index if index >= 0 else None

    def banner_string(self) -> str | None:
        offset = self.banner_offset()
        if offset is None:
            return None
        raw = self.data[offset:offset + 200].split(b'\x00', 1)[0]
        return raw.decode('latin1', errors='replace')


class KernelBacking:
    """Kernel image + symbol table pair used to back a module/descriptor harness."""

    def __init__(self, image: KernelImage, symbols: KernelSymbolTable | None = None):
        self.image = image
        self.symbols = symbols

    @classmethod
    def from_evidence(cls, root: str | Path, *, decode_symbols: bool = True,
                      label: str = 'nflasha3') -> 'KernelBacking':
        from src.a6400.execution.nflasha_boot_set import NflashaBootSet
        boot_set = NflashaBootSet.from_evidence(root, label)
        kernel = boot_set.kernel_file()
        image = KernelImage(kernel.data, sha256=kernel.sha256,
                            source=f'{label}:{kernel.path}')
        symbols = (KernelSymbolTable.from_kallsyms(kernel.data,
                                                   source_sha256=kernel.sha256)
                   if decode_symbols else None)
        return cls(image, symbols)

    def verify(self) -> dict:
        """Cross-check the symbol table against the image bytes and identity."""
        report = {'sha256': self.image.sha256, 'virtual_base': self.image.virtual_base,
                  'bytes': len(self.image.data)}
        report['linux_banner_file_offset'] = self.image.banner_offset()
        report['linux_banner_string'] = self.image.banner_string()
        if self.symbols is not None:
            resolved = {}
            for name in VALIDATION_SYMBOLS:
                try:
                    resolved[name] = self.symbols.address(name)
                except KernelBackingError:
                    resolved[name] = None
            report['symbols'] = resolved
            banner = resolved.get('linux_banner')
            report['linux_banner_symbol_matches_file'] = (
                banner is not None
                and self.image.banner_offset() is not None
                and banner - self.image.virtual_base == self.image.banner_offset())
            stext, etext = resolved.get('_stext'), resolved.get('_etext')
            report['text_range_valid'] = bool(
                stext is not None and etext is not None
                and self.image.virtual_base <= stext < etext <= self.image.virtual_end)
        return report

    def resolve(self, name: str) -> int:
        if self.symbols is None:
            raise KernelBackingError('no symbol table loaded')
        return self.symbols.address(name)

    def read(self, vaddr: int, size: int) -> bytes:
        return self.image.bytes_at(vaddr, size)

    def read_symbol(self, name: str, size: int | None = None) -> bytes:
        address = self.resolve(name)
        return self.read(address, size if size is not None else self.symbols.span(name))

    def disassemble_symbol(self, name: str, count: int = 16) -> list[str]:
        from capstone import CS_ARCH_ARM, CS_MODE_ARM, Cs
        if count <= 0:
            raise KernelBackingError('positive instruction count required')
        address = self.resolve(name)
        raw = self.read(address, min(4 * count * 4, 1024))
        md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
        lines = []
        for instruction in md.disasm(raw, address):
            lines.append(f'0x{instruction.address:08x}  {instruction.mnemonic} '
                         f'{instruction.op_str}')
            if len(lines) >= count:
                break
        return lines

    def map_into(self, uc) -> dict:
        """Map the kernel at its virtual base and return the mapping receipt."""
        text_end = None
        if self.symbols is not None:
            try:
                text_end = self.symbols.address('_etext')
            except KernelBackingError:
                text_end = None
        ranges = self.image.map_into(uc, text_end=text_end)
        return {'virtual_base': self.image.virtual_base,
                'bytes': len(self.image.data), 'ranges': ranges,
                'symbols': len(self.symbols) if self.symbols is not None else 0}

    def module_harness_binding(self, names: tuple[str, ...]) -> dict:
        """Addresses a kernel module test can call/read directly."""
        binding = {}
        for name in names:
            try:
                address = self.resolve(name)
            except KernelBackingError:
                binding[name] = None
                continue
            binding[name] = {'address': address,
                             'file_offset': address - self.image.virtual_base}
        return binding


#: Symbols of the USB/gadget descriptor path used by E0405ab/E0407b1 tests.
USB_GADGET_SYMBOLS = (
    'usb_gadgetcore_register_driver',
    'usb_gadgetcore_unregister_driver',
    'dev_get_drvdata',
    'printk',
)
