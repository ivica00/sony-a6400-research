"""ELF32 process-image mapping; no host-side dynamic relocations or imports."""
import hashlib
import io
from pathlib import Path

from elftools.elf.elffile import ELFFile
from unicorn import UC_PROT_READ, UC_PROT_WRITE, UC_PROT_EXEC

PAGE_SIZE = 4096


def inspect_image(path, expected_hash):
    data = Path(path).read_bytes()
    actual_hash = hashlib.sha256(data).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError(f'Input hash mismatch: {path}')
    elf = ELFFile(io.BytesIO(data))
    if elf.elfclass != 32 or not elf.little_endian or elf['e_machine'] != 'EM_ARM':
        raise ValueError('Requires little-endian ELF32 ARM')
    if elf['e_type'] not in ('ET_EXEC', 'ET_DYN'):
        raise ValueError('Requires executable or shared-object ELF')
    segments = [dict(segment.header) for segment in elf.iter_segments() if segment['p_type'] == 'PT_LOAD']
    interpreter = next((segment.get_interp_name() for segment in elf.iter_segments()
                        if segment['p_type'] == 'PT_INTERP'), None)
    return {'data': data, 'sha256': actual_hash, 'type': elf['e_type'], 'entry': elf['e_entry'],
            'phoff': elf['e_phoff'], 'phnum': elf['e_phnum'], 'phent': elf['e_phentsize'],
            'segments': segments, 'interpreter': interpreter}


def map_image(mu, image, bias):
    if image['type'] == 'ET_EXEC' and bias:
        raise ValueError('ET_EXEC must retain its linked virtual addresses')
    if bias < 0 or bias % PAGE_SIZE:
        raise ValueError('Invalid load bias')
    pages, mappings = set(), []
    for segment in image['segments']:
        address, offset = segment['p_vaddr'], segment['p_offset']
        filesz, memsz, align = segment['p_filesz'], segment['p_memsz'], segment['p_align']
        if filesz > memsz or offset + filesz > len(image['data']):
            raise ValueError('Segment exceeds file or memory bounds')
        if address % PAGE_SIZE != offset % PAGE_SIZE:
            raise ValueError('File/virtual page offsets differ')
        if align not in (0, 1) and (align & (align - 1) or (address - offset) % align or bias % align):
            raise ValueError('ELF segment alignment constraint violated')
        if not memsz:
            continue
        start = (bias + address) & ~(PAGE_SIZE - 1)
        end = (bias + address + memsz + PAGE_SIZE - 1) & ~(PAGE_SIZE - 1)
        if start < 0 or end > 0x100000000:
            raise ValueError('Segment exceeds ARM32 address space')
        segment_pages = set(range(start, end, PAGE_SIZE))
        if pages & segment_pages:
            raise ValueError('Shared PT_LOAD pages require an explicit mapping policy')
        pages |= segment_pages
        flags = segment['p_flags']
        permissions = ((UC_PROT_READ if flags & 4 else 0) |
                       (UC_PROT_WRITE if flags & 2 else 0) |
                       (UC_PROT_EXEC if flags & 1 else 0))
        mappings.append({'address': start, 'size': end - start, 'permissions': permissions,
                         'segment_vaddr': address, 'file_offset': offset,
                         'file_size': filesz, 'memory_size': memsz})
    if not mappings:
        raise ValueError('No loadable segments')
    entry = bias + image['entry']
    if not any(s['p_vaddr'] <= (image['entry'] & ~1) < s['p_vaddr'] + s['p_memsz']
               and s['p_flags'] & 1 for s in image['segments']):
        raise ValueError('Entry is outside executable segments')
    completed = []
    try:
        for mapping in mappings:
            mu.mem_map(mapping['address'], mapping['size'], mapping['permissions'])
            completed.append(mapping)
            if mapping['file_size']:
                # Include the file-backed prefix of a partial first page, like elf_map.
                prefix = mapping['file_offset'] % PAGE_SIZE
                offset = mapping['file_offset'] - prefix
                mu.mem_write(mapping['address'], image['data'][offset:offset + prefix + mapping['file_size']])
            # Newly mapped pages are zero-filled, including segment BSS and final padding.
    except Exception:
        for mapping in reversed(completed):
            mu.mem_unmap(mapping['address'], mapping['size'])
        raise
    phdr = None
    table_end = image['phoff'] + image['phnum'] * image['phent']
    for segment in image['segments']:
        if segment['p_offset'] <= image['phoff'] and table_end <= segment['p_offset'] + segment['p_filesz']:
            phdr = bias + segment['p_vaddr'] + image['phoff'] - segment['p_offset']
            break
    return {'entry': entry, 'bias': bias, 'phdr': phdr, 'phnum': image['phnum'],
            'phent': image['phent'], 'sha256': image['sha256'], 'mappings': mappings}
