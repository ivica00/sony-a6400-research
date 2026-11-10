"""Camera-verified display surface contract and read-only frame extraction.

This module models only the surfaces whose identity is backed by retained
evidence.  It does not render pixels, does not invent geometry and does not
fill missing bytes.  A frame is either read from guest memory at a mapped
display surface or reported as ``unmapped``/``unwritten``.

Evidence anchors:
* E0074 - OSD layer double buffers, PA 0x23a80000 / 0x23b16000, 640x480
  RGBA4444, 614400 bytes each.
* E0044 - captured GRM pool list: ``gl_common`` at PA 0x202e0000, 32 MiB;
  two ``empty`` pools at the OSD physical addresses above.
* E0081/E0082 - a Sugilite buffer candidate at PA 0x202e1000
  (gl_common + 0x1000).  A safe ptrace read of the live camera's mapping
  shows this is a patterned internal buffer, not a rendered display frame;
  it is retained as ``role='internal'`` only.
* Safe ptrace capture of im.elf's OSD A/B mappings decodes to a complete
  PlayMemories screen (640x480 RGBA4444), confirming the OSD layer as the
  camera display surface.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass, field
import hashlib
import struct
from typing import Callable, Dict, Iterable, List, Optional, Tuple

RGBA4444 = 'rgba4444'
RGB565 = 'rgb565'
ARGB8888 = 'argb8888'
SUPPORTED_FORMATS = (RGBA4444, RGB565, ARGB8888)

#: Physical pool backing the Sugilite GPU stream (E0044, gl_common).
GL_COMMON_POOL = {
    'name': 'gl_common',
    'physical_base': 0x202E0000,
    'size': 0x02000000,
    'evidence': 'E0044',
}


@dataclass(frozen=True)
class DisplaySurface:
    """One evidence-backed display surface.

    ``format_source`` distinguishes camera-confirmed formats from bounded
    hypotheses.  Callers must surface the distinction instead of presenting a
    hypothesis as a verified scanout contract.
    """

    name: str
    physical_base: int
    width: int
    height: int
    pixel_format: str
    bytes_per_pixel: int
    evidence: str
    format_source: str = 'evidence-hypothesis'
    note: str = ''
    role: str = 'display'

    @property
    def stride(self) -> int:
        return self.width * self.bytes_per_pixel

    @property
    def byte_size(self) -> int:
        return self.stride * self.height

    @property
    def pixel_count(self) -> int:
        return self.width * self.height


#: v1 display contract.  OSD A/B are camera-documented; the Sugilite colour
#: buffer format remains a hypothesis until confirmed by a live capture.
DISPLAY_SURFACES: Dict[str, DisplaySurface] = {
    'osd_a': DisplaySurface(
        name='osd_a', physical_base=0x23A80000, width=640, height=480,
        pixel_format=RGBA4444, bytes_per_pixel=2,
        evidence='E0074,E0044', format_source='camera-documented',
        note='OSD layer double buffer A (E0074)'),
    'osd_b': DisplaySurface(
        name='osd_b', physical_base=0x23B16000, width=640, height=480,
        pixel_format=RGBA4444, bytes_per_pixel=2,
        evidence='E0074,E0044', format_source='camera-documented',
        note='OSD layer double buffer B (E0074)'),
    'sugilite_color0': DisplaySurface(
        name='sugilite_color0', physical_base=0x202E1000, width=960, height=540,
        pixel_format=RGBA4444, bytes_per_pixel=2,
        evidence='E0081,E0082,ptrace-e0298', format_source='evidence-hypothesis',
        note='Internal Sugilite buffer; live ptrace shows patterned data, not a display frame',
        role='internal'),
}

#: Preferred presentation order when no write has been observed yet.  Only
#: camera-verified display surfaces are presented; internal buffers are never
#: selected as a screen.
DEFAULT_SURFACE_ORDER = ('osd_a', 'osd_b')


def display_contract(name: str = 'camera-e0074-e0044') -> Dict[str, object]:
    """Return a serialisable display profile for an explicit contract name."""
    if name in (None, '', 'none'):
        return {'name': 'none', 'surfaces': {}, 'pool': None}
    if name != 'camera-e0074-e0044':
        raise ValueError(f'Unknown display contract: {name}')
    return {
        'name': name,
        'surfaces': {
            key: {
                'name': surface.name,
                'physical_base': surface.physical_base,
                'width': surface.width,
                'height': surface.height,
                'pixel_format': surface.pixel_format,
                'bytes_per_pixel': surface.bytes_per_pixel,
                'evidence': surface.evidence,
                'format_source': surface.format_source,
                'note': surface.note,
                'role': surface.role,
            }
            for key, surface in DISPLAY_SURFACES.items()
        },
        'pool': dict(GL_COMMON_POOL),
        'presentation_order': list(DEFAULT_SURFACE_ORDER),
    }


def _build_rgba4444_table() -> Tuple[bytes, ...]:
    table = []
    for value in range(0x10000):
        red = ((value >> 12) & 0xF) * 17
        green = ((value >> 8) & 0xF) * 17
        blue = ((value >> 4) & 0xF) * 17
        alpha = (value & 0xF) * 17
        table.append(bytes((red, green, blue, alpha)))
    return tuple(table)


def _build_rgb565_table() -> Tuple[bytes, ...]:
    table = []
    for value in range(0x10000):
        red = (value >> 11) & 0x1F
        green = (value >> 5) & 0x3F
        blue = value & 0x1F
        table.append(bytes((red * 255 // 31, green * 255 // 63, blue * 255 // 31, 255)))
    return tuple(table)


_RGBA4444_TABLE: Optional[Tuple[bytes, ...]] = None
_RGB565_TABLE: Optional[Tuple[bytes, ...]] = None


def _rgba4444_table() -> Tuple[bytes, ...]:
    global _RGBA4444_TABLE
    if _RGBA4444_TABLE is None:
        _RGBA4444_TABLE = _build_rgba4444_table()
    return _RGBA4444_TABLE


def _rgb565_table() -> Tuple[bytes, ...]:
    global _RGB565_TABLE
    if _RGB565_TABLE is None:
        _RGB565_TABLE = _build_rgb565_table()
    return _RGB565_TABLE


def _require_exact(raw: bytes, width: int, height: int, bytes_per_pixel: int) -> None:
    expected = width * height * bytes_per_pixel
    if len(raw) < expected:
        raise ValueError(f'Display surface is short: {len(raw)} < {expected} bytes')
    if len(raw) > expected:
        raise ValueError(f'Display surface is long: {len(raw)} > {expected} bytes')


def rgba4444_to_rgba(raw: bytes, width: int, height: int) -> bytes:
    """Decode little-endian RGBA4444 pixels (E0074) into packed RGBA bytes."""
    _require_exact(raw, width, height, 2)
    words = array('H')
    words.frombytes(raw[:width * height * 2])
    table = _rgba4444_table()
    return b''.join(map(table.__getitem__, words))


def rgb565_to_rgba(raw: bytes, width: int, height: int) -> bytes:
    """Decode little-endian RGB565 pixels into packed RGBA bytes (alpha 255)."""
    _require_exact(raw, width, height, 2)
    words = array('H')
    words.frombytes(raw[:width * height * 2])
    table = _rgb565_table()
    return b''.join(map(table.__getitem__, words))


def argb8888_to_rgba(raw: bytes, width: int, height: int) -> bytes:
    """Decode little-endian 32-bit pixels into packed RGBA bytes.

    The byte order follows the ARM Linux ``/dev/fb0`` 32-bit layout used by the
    existing framebuffer model (BGRA in memory yields RGBA output here).
    """
    _require_exact(raw, width, height, 4)
    out = bytearray(width * height * 4)
    for index in range(0, width * height):
        base = index * 4
        blue, green, red, alpha = raw[base:base + 4]
        target = index * 4
        out[target] = red
        out[target + 1] = green
        out[target + 2] = blue
        out[target + 3] = alpha
    return bytes(out)


def decode_surface(surface: DisplaySurface, raw: bytes) -> bytes:
    """Decode a surface's raw bytes without guessing its format."""
    if surface.pixel_format == RGBA4444:
        return rgba4444_to_rgba(raw, surface.width, surface.height)
    if surface.pixel_format == RGB565:
        return rgb565_to_rgba(raw, surface.width, surface.height)
    if surface.pixel_format == ARGB8888:
        return argb8888_to_rgba(raw, surface.width, surface.height)
    raise ValueError(f'Unsupported display format: {surface.pixel_format}')


def surface_to_image(surface: DisplaySurface, rgba: bytes):
    """Build a PIL image from already decoded RGBA bytes (no drawing)."""
    from PIL import Image
    return Image.frombytes('RGBA', (surface.width, surface.height), rgba)


@dataclass
class DisplayMapping:
    physical_start: int
    virtual_start: int
    length: int
    device: str = 'stream'
    path: str = '/dev/stream'

    def contains_physical(self, address: int, size: int = 1) -> bool:
        return self.physical_start <= address and address + size <= self.physical_start + self.length


@dataclass
class SurfaceState:
    count: int = 0
    first_pc: Optional[int] = None
    last_pc: Optional[int] = None
    first_instruction: Optional[int] = None
    last_instruction: Optional[int] = None
    first_tid: Optional[int] = None
    last_tid: Optional[int] = None

    def record(self, pc: int, tid: Optional[int], instruction: Optional[int]) -> None:
        if self.count == 0:
            self.first_pc = pc
            self.first_tid = tid
            self.first_instruction = instruction
        self.count += 1
        self.last_pc = pc
        self.last_tid = tid
        self.last_instruction = instruction

    def to_dict(self) -> Dict[str, object]:
        return {
            'count': self.count,
            'first_pc': self.first_pc,
            'last_pc': self.last_pc,
            'first_instruction': self.first_instruction,
            'last_instruction': self.last_instruction,
            'first_tid': self.first_tid,
            'last_tid': self.last_tid,
        }


@dataclass
class Frame:
    surface: DisplaySurface
    raw: bytes
    rgba: bytes
    virtual_start: int
    physical_start: int
    instruction: Optional[int]
    status: str
    provenance: Dict[str, object]
    content_sha256: str
    raw_sha256: str

    def metadata(self) -> Dict[str, object]:
        return {
            'surface': self.surface.name,
            'physical_base': self.surface.physical_base,
            'virtual_start': self.virtual_start,
            'width': self.surface.width,
            'height': self.surface.height,
            'pixel_format': self.surface.pixel_format,
            'format_source': self.surface.format_source,
            'evidence': self.surface.evidence,
            'stride': self.surface.stride,
            'byte_size': self.surface.byte_size,
            'instruction': self.instruction,
            'status': self.status,
            'provenance': self.provenance,
            'content_sha256': self.content_sha256,
            'raw_sha256': self.raw_sha256,
        }


class DisplayModel:
    """Maps verified physical surfaces into guest VA space and reads frames.

    The model is passive: it never writes guest memory.  The owning probe is
    responsible for calling :meth:`note_write` from a memory-write hook and
    :meth:`register_mapping` when a device mapping is established.
    """

    def __init__(self, profile: Dict[str, object]):
        if not isinstance(profile, dict):
            raise ValueError('Display profile must be a mapping')
        self.name = str(profile.get('name', 'camera-e0074-e0044'))
        surfaces = profile.get('surfaces') or {}
        if not surfaces:
            raise ValueError('Display profile has no surfaces')
        self.surfaces: Dict[str, DisplaySurface] = {}
        for key, item in surfaces.items():
            self.surfaces[key] = DisplaySurface(
                name=item['name'], physical_base=int(item['physical_base']),
                width=int(item['width']), height=int(item['height']),
                pixel_format=item['pixel_format'], bytes_per_pixel=int(item['bytes_per_pixel']),
                evidence=item['evidence'], format_source=item.get('format_source', 'evidence-hypothesis'),
                note=item.get('note', ''), role=item.get('role', 'display'))
        self.pool = profile.get('pool')
        order = tuple(profile.get('presentation_order') or DEFAULT_SURFACE_ORDER)
        self.presentation_order = tuple(key for key in order if key in self.surfaces)
        self.mappings: List[DisplayMapping] = []
        self.states: Dict[str, SurfaceState] = {key: SurfaceState() for key in self.surfaces}
        self.unknown_writes = 0
        self.installed_ranges: List[Tuple[int, int]] = []

    # -- mapping -------------------------------------------------------
    def register_mapping(self, virtual_start: int, length: int, physical_start: int,
                         device: str = 'stream', path: str = '/dev/stream') -> List[Tuple[int, int]]:
        """Register a guest mapping and return the VA ranges of display surfaces."""
        if length <= 0:
            raise ValueError('Display mapping must be positive')
        mapping = DisplayMapping(int(physical_start), int(virtual_start), int(length), device, path)
        self.mappings.append(mapping)
        return self.surface_ranges(mapping)

    def surface_ranges(self, mapping: DisplayMapping) -> List[Tuple[int, int]]:
        ranges = []
        for surface in self.surfaces.values():
            if not mapping.contains_physical(surface.physical_base, surface.byte_size):
                continue
            start = mapping.virtual_start + (surface.physical_base - mapping.physical_start)
            ranges.append((start, start + surface.byte_size))
        return ranges

    def all_surface_ranges(self) -> List[Tuple[int, int]]:
        ranges: List[Tuple[int, int]] = []
        for mapping in self.mappings:
            ranges.extend(self.surface_ranges(mapping))
        return ranges

    def surface_for_address(self, address: int, size: int = 1) -> Optional[str]:
        for mapping in self.mappings:
            for key, surface in self.surfaces.items():
                if not mapping.contains_physical(surface.physical_base, surface.byte_size):
                    continue
                start = mapping.virtual_start + (surface.physical_base - mapping.physical_start)
                if start <= address and address + size <= start + surface.byte_size:
                    return key
        return None

    def note_write(self, address: int, size: int, pc: int, tid: Optional[int],
                   instruction: Optional[int]) -> Optional[str]:
        key = self.surface_for_address(address, size)
        if key is None:
            self.unknown_writes += 1
            return None
        self.states[key].record(pc, tid, instruction)
        return key

    # -- selection / reading ------------------------------------------
    def mapped_surfaces(self) -> List[Tuple[str, DisplaySurface, DisplayMapping]]:
        result = []
        for key in self.surfaces:
            surface = self.surfaces[key]
            for mapping in self.mappings:
                if mapping.contains_physical(surface.physical_base, surface.byte_size):
                    result.append((key, surface, mapping))
                    break
        return result

    def display_mapped(self) -> List[Tuple[str, DisplaySurface, DisplayMapping]]:
        """Mapped surfaces that are verified display layers (not internal buffers)."""
        return [entry for entry in self.mapped_surfaces() if entry[1].role == 'display']

    def select(self, prefer: Optional[Iterable[str]] = None) -> Optional[Tuple[str, DisplaySurface, DisplayMapping]]:
        """Prefer the most recently guest-written mapped display surface, else order."""
        mapped = self.display_mapped()
        if not mapped:
            return None
        written = [entry for entry in mapped if self.states[entry[0]].count > 0]
        if written:
            return max(written, key=lambda entry: (self.states[entry[0]].count,
                                                  self.states[entry[0]].last_instruction or -1))
        order = tuple(prefer) if prefer is not None else self.presentation_order
        for key in order:
            for entry in mapped:
                if entry[0] == key:
                    return entry
        return mapped[0]

    def raw_status(self, key: str, raw: bytes) -> str:
        if self.states[key].count > 0:
            return 'written'
        if any(raw):
            return 'snapshot-content'
        return 'unwritten'

    def read_frame(self, memory_reader: Callable[[int, int], bytes], key: Optional[str] = None,
                   instruction: Optional[int] = None) -> Optional[Frame]:
        """Read one frame from guest memory.  Never invents or pads bytes."""
        selection = self.select() if key is None else next(
            ((k, s, m) for k, s, m in self.mapped_surfaces() if k == key), None)
        if selection is None:
            return None
        name, surface, mapping = selection
        virtual = mapping.virtual_start + (surface.physical_base - mapping.physical_start)
        raw = bytes(memory_reader(virtual, surface.byte_size))
        if len(raw) != surface.byte_size:
            raise ValueError('Display read returned a short buffer')
        rgba = decode_surface(surface, raw)
        status = self.raw_status(name, raw)
        return Frame(surface=surface, raw=raw, rgba=rgba, virtual_start=virtual,
                     physical_start=surface.physical_base, instruction=instruction,
                     status=status, provenance=self.states[name].to_dict(),
                     content_sha256=hashlib.sha256(rgba).hexdigest(),
                     raw_sha256=hashlib.sha256(raw).hexdigest())

    # -- checkpoint support -------------------------------------------
    def to_state(self) -> Dict[str, object]:
        return {
            'name': self.name,
            'mappings': [mapping.__dict__ for mapping in self.mappings],
            'states': {key: state.to_dict() for key, state in self.states.items()},
            'unknown_writes': self.unknown_writes,
        }

    def from_state(self, state: Dict[str, object]) -> None:
        if not isinstance(state, dict):
            raise ValueError('Display checkpoint state must be a mapping')
        self.mappings = [DisplayMapping(int(item['physical_start']), int(item['virtual_start']),
                                        int(item['length']), item.get('device', 'stream'),
                                        item.get('path', '/dev/stream'))
                         for item in state.get('mappings', [])]
        for key, item in (state.get('states') or {}).items():
            if key not in self.states:
                continue
            record = SurfaceState()
            for field_name in ('count', 'first_pc', 'last_pc', 'first_instruction',
                               'last_instruction', 'first_tid', 'last_tid'):
                setattr(record, field_name, item.get(field_name))
            self.states[key] = record
        self.unknown_writes = int(state.get('unknown_writes', 0))

    # -- reporting ----------------------------------------------------
    def report(self) -> Dict[str, object]:
        return {
            'contract': self.name,
            'pool': self.pool,
            'surfaces': {
                key: {
                    'physical_base': surface.physical_base,
                    'width': surface.width,
                    'height': surface.height,
                    'pixel_format': surface.pixel_format,
                    'format_source': surface.format_source,
                    'evidence': surface.evidence,
                    'role': surface.role,
                    'mapped': any(surface.name == entry[1].name for entry in self.mapped_surfaces()),
                    'state': self.states[key].to_dict(),
                }
                for key, surface in self.surfaces.items()
            },
            'mappings': [mapping.__dict__ for mapping in self.mappings],
            'unknown_writes': self.unknown_writes,
            'limitations': ('Read-only extraction of evidence-backed surfaces; '
                            'no GPU execution, no host rendering, no unverified scanout.'),
        }
