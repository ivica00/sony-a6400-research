"""Strict ELF identity allowing only same-layout build-id/comment payload changes."""
import hashlib
import io
from elftools.elf.elffile import ELFFile


def normalize_elf_metadata(data):
    """Validate ELF32 LE ARM layout and zero ``.note.gnu.build-id`` / ``.comment``."""
    elf = ELFFile(io.BytesIO(data))
    if elf.elfclass != 32 or not elf.little_endian or elf['e_machine'] != 'EM_ARM':
        return {'valid': False, 'reason': 'not ELF32 little-endian ARM'}
    clean = bytearray(data)
    sections = {}
    for name, kind in (('.note.gnu.build-id', 'SHT_NOTE'), ('.comment', 'SHT_PROGBITS')):
        sec = elf.get_section_by_name(name)
        if sec is None:
            sections[name] = None
            continue
        if sec['sh_type'] != kind:
            return {'valid': False, 'reason': 'metadata section layout/type differs'}
        if sec['sh_flags'] & 4:
            return {'valid': False, 'reason': 'metadata section marked executable'}
        start, size = sec['sh_offset'], sec['sh_size']
        reserved = [
            (0, elf['e_ehsize']),
            (elf['e_shoff'], elf['e_shentsize'] * elf['e_shnum']),
            (elf['e_phoff'], elf['e_phentsize'] * elf['e_phnum']),
        ]
        reserved += [
            (s['sh_offset'], s['sh_size'])
            for s in elf.iter_sections()
            if s.name != name and s['sh_type'] not in ('SHT_NOBITS', 'SHT_NULL')
        ]
        if any(n and start < offset + n and offset < start + size for offset, n in reserved):
            return {'valid': False, 'reason': 'metadata overlaps other ELF content'}
        sections[name] = (sec.header, sec.data(), start, size)
        clean[start:start + size] = b'\0' * size
    return {
        'valid': True,
        'sections': sections,
        'normalized_sha256': hashlib.sha256(clean).hexdigest(),
    }


def compare_metadata_only(actual, expected):
    if len(actual) != len(expected):
        return {'equivalent': False, 'reason': 'different file size'}
    left = normalize_elf_metadata(actual)
    if not left['valid']:
        return {'equivalent': False, 'reason': left['reason']}
    right = normalize_elf_metadata(expected)
    if not right['valid']:
        return {'equivalent': False, 'reason': right['reason']}
    allowed = []
    for name in ('.note.gnu.build-id', '.comment'):
        a, b = left['sections'][name], right['sections'][name]
        if a is None or b is None:
            if a is not None or b is not None:
                return {'equivalent': False, 'reason': 'metadata section missing from one file'}
            continue
        if a[0] != b[0]:
            return {'equivalent': False, 'reason': 'metadata section layout/type differs'}
        if a[1] != b[1]:
            allowed.append({'section': name, 'offset': a[2], 'bytes': a[3]})
    return {
        'equivalent': left['normalized_sha256'] == right['normalized_sha256'],
        'metadata_differences': allowed,
        'normalized_camera_sha256': left['normalized_sha256'],
        'normalized_expected_sha256': right['normalized_sha256'],
    }
