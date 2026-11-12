"""Build the protocol-v2 native USB debugger (E0401) with the WSL ARM toolchain.

Outputs the daemon executable and launcher shared object under
artifacts/native/usb-debugger-e0401/, records source/binary hashes, and performs
a fail-closed static audit of the produced ELF: ARM EABI identity, dynamic
library dependencies, undefined-symbol resolution against the pinned Sony libc,
and absence of an executable writable segment / text relocations.

The tool never deploys to or executes anything on the camera.
"""
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'tools/native_camera/a6400_usb_debugd.c'
STARTUP = ROOT / 'tools/native_camera/debug_start.S'
LAUNCHER_SOURCE = ROOT / 'tools/native_camera/hook/usb_debug_launcher.c'
SONY_LIBC = ROOT / 'tools/sony_sysroot/lib/libc.so'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path):
    return path.relative_to(ROOT).as_posix()


def run(compiler, output, sources, extra):
    command = [*compiler, *extra, '-o', relative(output), *[relative(p) for p in sources]]
    if os.name != 'posix':
        linux_root = '/mnt/' + ROOT.drive[0].lower() + ROOT.as_posix()[2:]
        command = ['wsl.exe', '--cd', linux_root, '--exec', *command]
    subprocess.run(command, cwd=ROOT, check=True)


def elf_audit(executable, launcher, libc):
    """Fail-closed static checks; returns a JSON-serialisable receipt."""
    receipt = {'executable': {}, 'launcher': {}}
    with libc.open('rb') as handle:
        libc_elf = ELFFile(handle)
        libc_dynamic = libc_elf.get_section_by_name('.dynsym')
        libc_exports = {symbol.name for symbol in libc_dynamic.iter_symbols()
                        if symbol.name and symbol['st_shndx'] != 'SHN_UNDEF'}
    for role, path in (('executable', executable), ('launcher', launcher)):
        with path.open('rb') as handle:
            elf = ELFFile(handle)
            if elf.header.e_machine != 'EM_ARM':
                raise ValueError(f'{role}: not an ARM ELF')
            if elf.little_endian is not True:
                raise ValueError(f'{role}: expected little-endian ELF')
            if elf.header.e_type not in ('ET_EXEC', 'ET_DYN'):
                raise ValueError(f'{role}: unexpected ELF type {elf.header.e_type}')
            if elf.header.e_flags & 0x400:  # EF_ARM_ABI_FLOAT_HARD
                raise ValueError(f'{role}: hard-float EABI is not the camera ABI')
            dynamic = elf.get_section_by_name('.dynsym')
            undefined = {symbol.name for symbol in dynamic.iter_symbols()
                         if symbol.name and symbol['st_shndx'] == 'SHN_UNDEF'}
            if undefined - libc_exports:
                missing = sorted(undefined - libc_exports)
                raise ValueError(f'{role}: unresolved against pinned Sony libc: {missing}')
            needed = []
            attributes = {}
            for section in elf.iter_sections():
                if section.name == '.dynamic':
                    for tag in section.iter_tags():
                        if tag.entry.d_tag == 'DT_NEEDED':
                            needed.append(tag.needed)
                        if tag.entry.d_tag.startswith('DT_FLAGS'):
                            attributes[tag.entry.d_tag] = tag.entry.d_val
                if section.name == '.attributes':
                    attributes['aeabi'] = section.data().hex()
            for segment in elf.iter_segments():
                if segment.header.p_type == 'PT_LOAD' and segment.header.p_flags & 0x2 \
                        and segment.header.p_flags & 0x1:
                    raise ValueError(f'{role}: writable+executable PT_LOAD segment')
                if segment.header.p_type == 'PT_TEXTREL':
                    raise ValueError(f'{role}: text relocation segment present')
            defined = {}
            symtab = elf.get_section_by_name('.symtab')
            if isinstance(symtab, SymbolTableSection):
                for symbol in symtab.iter_symbols():
                    if symbol.name and symbol['st_shndx'] != 'SHN_UNDEF':
                        defined[symbol.name] = symbol['st_value']
            if '_start' not in defined and role == 'executable':
                raise ValueError('executable has no _start entry symbol')
            receipt[role] = {
                'file': path.name,
                'bytes': path.stat().st_size,
                'sha256': digest(path),
                'e_type': elf.header.e_type,
                'e_machine': elf.header.e_machine,
                'entry': hex(elf.header.e_entry),
                'needed': needed,
                'undefined_symbols': len(undefined),
                'defined_symbols': len(defined),
                'aeabi': attributes.get('aeabi'),
                'dyn_flags': {k: hex(v) for k, v in attributes.items() if k != 'aeabi'},
            }
    if 'libc.so.6' not in receipt['executable']['needed']:
        raise ValueError('executable does not request the camera libc')
    return receipt


def main():
    audit_only = '--audit-only' in sys.argv[1:]
    output_dir = ROOT / 'artifacts/native/usb-debugger-e0401'
    output_dir.mkdir(parents=True, exist_ok=True)
    executable = output_dir / 'a6400_usb_debugd.elf'
    launcher = output_dir / 'usb_debug_launcher.so'
    compiler = ['arm-linux-gnueabi-gcc']
    common = ['-std=gnu11', '-march=armv7-a', '-mfloat-abi=softfp', '-O2', '-Wall', '-Wextra',
              '-Werror', '-nostdlib', '-U_FORTIFY_SOURCE', '-D_FORTIFY_SOURCE=0',
              '-U_TIME_BITS', '-D_TIME_BITS=32', '-U_FILE_OFFSET_BITS', '-D_FILE_OFFSET_BITS=32']
    if not audit_only:
        run(compiler, executable, [STARTUP, SOURCE, SONY_LIBC],
            [*common, '-fno-stack-protector', '-Wl,-e,_start,-z,defs,-z,max-page-size=4096',
             '-Wl,--dynamic-linker=/lib/ld-linux.so.3', '-lgcc'])
        run(compiler, launcher, [LAUNCHER_SOURCE, SONY_LIBC],
            [*common, '-fPIC', '-shared', '-Wl,-soname,usb_debug_launcher.so,-z,defs,-z,max-page-size=4096'])
    receipt = elf_audit(executable, launcher, SONY_LIBC)
    manifest = {
        'built_utc': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z'),
        'deployed': False,
        'sources': {relative(p): {'bytes': p.stat().st_size, 'sha256': digest(p)}
                    for p in (SOURCE, STARTUP, LAUNCHER_SOURCE, SONY_LIBC)},
        'artifacts': receipt,
    }
    manifest_path = output_dir / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(manifest_path)
    print(json.dumps(receipt['executable'], indent=2))


if __name__ == '__main__':
    sys.exit(main())
