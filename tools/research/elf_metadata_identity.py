"""Strict ELF identity allowing only same-layout build-id/comment payload changes."""
import io
import hashlib
from elftools.elf.elffile import ELFFile


def compare_metadata_only(actual, expected):
    if len(actual)!=len(expected):
        return {'equivalent':False,'reason':'different file size'}
    left,right=ELFFile(io.BytesIO(actual)),ELFFile(io.BytesIO(expected))
    for elf in (left,right):
        if elf.elfclass!=32 or not elf.little_endian or elf['e_machine']!='EM_ARM':
            return {'equivalent':False,'reason':'not ELF32 little-endian ARM'}
    clean_left,clean_right=bytearray(actual),bytearray(expected)
    allowed=[]
    for name,kind in (('.note.gnu.build-id','SHT_NOTE'),('.comment','SHT_PROGBITS')):
        a,b=left.get_section_by_name(name),right.get_section_by_name(name)
        if a is None or b is None:
            if a is not None or b is not None:
                return {'equivalent':False,'reason':'metadata section missing from one file'}
            continue
        if a['sh_type']!=kind or b['sh_type']!=kind or a.header!=b.header:
            return {'equivalent':False,'reason':'metadata section layout/type differs'}
        if a['sh_flags'] & 4:
            return {'equivalent':False,'reason':'metadata section marked executable'}
        start,size=a['sh_offset'],a['sh_size']
        # No overlap with any other section's file bytes or the ELF/section table.
        for elf in (left,right):
            reserved=[(0,elf['e_ehsize']),
                      (elf['e_shoff'],elf['e_shentsize']*elf['e_shnum']),
                      (elf['e_phoff'],elf['e_phentsize']*elf['e_phnum'])]
            reserved += [(s['sh_offset'],s['sh_size']) for s in elf.iter_sections()
                         if s.name!=name and s['sh_type'] not in ('SHT_NOBITS','SHT_NULL')]
            if any(n and start<offset+n and offset<start+size for offset,n in reserved):
                return {'equivalent':False,'reason':'metadata overlaps other ELF content'}
        if a.data()!=b.data():
            allowed.append({'section':name,'offset':start,'bytes':size})
        clean_left[start:start+size]=b'\0'*size
        clean_right[start:start+size]=b'\0'*size
    return {'equivalent':clean_left==clean_right,'metadata_differences':allowed,
            'normalized_camera_sha256':hashlib.sha256(clean_left).hexdigest(),
            'normalized_expected_sha256':hashlib.sha256(clean_right).hexdigest()}
