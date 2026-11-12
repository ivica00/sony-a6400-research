"""Build the RAM-only B1c helper module from the verified usbg_video.ko carrier.

The carrier contributes only its ``.modinfo`` (exact vermagic) and
``.gnu.linkonce.this_module`` struct; its code is left linked but unreachable
because the module struct's init/exit relocations are redirected to the helper
object while the original symbols are renamed to ``carrier_*``.

Run this with ``--audit-only`` after the PowerShell wrapper has compiled and
linked the module; it performs a fail-closed static audit against the pinned
carrier and the live kallsyms export list.
"""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection

ROOT = Path(__file__).resolve().parents[2]
CARRIER = ROOT / 'firmware/extracted_zve10_v203_linuxnames/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/usbg_video.ko'
CARRIER_SHA = 'd385a051bf01b0e5ea37412623ae85cfe3cda76ab0d11e61d111994ca9fbf4fb'
KALLSYMS = ROOT / 'artifacts/analysis/e0401-kallsyms-now.txt'
OUT = ROOT / 'artifacts/native/a6400-dbg-patch-e0403'
MODULE_NAME = 'a6400_dbg_patch'
THIS_MODULE = '.gnu.linkonce.this_module'
THIS_MODULE_SIZE = 316
NAME_OFFSET = 12
NAME_LENGTH = 60

# E0407b1 tree module: same carrier flow, new object, new output directory.
TREE_SOURCE = ROOT / 'tools/native_camera/a6400_dbg_tree.c'
TREE_OUT = ROOT / 'artifacts/native/e0407b1-tree'
TREE_NAME = 'a6400_dbg_tree'
TREE_TEST_ELF = TREE_OUT / 'test/tree_test.elf'
TREE_TEST_OBJECT = TREE_OUT / 'a6400_dbg_tree_test.o'
TREE_PAYLOAD = ROOT / 'artifacts/tests/e0407b1-tree/tree_test_payload.json'
# Imports the tree building block is allowed to add on top of the carrier's
# own (unreachable) import set.
TREE_ALLOWED_IMPORTS = {
    '__kmalloc', 'kfree', 'memcpy', 'memset',
    'probe_kernel_read', 'probe_kernel_write', 'printk',
}
TREE_REQUIRED_IMPORTS = {
    '__kmalloc', 'kfree', 'memcpy', 'memset',
    'probe_kernel_read', 'probe_kernel_write', 'printk',
}
TREE_DEFINED_FUNCTIONS = ('init_module', 'cleanup_module')
TREE_VERMAGIC = 'vermagic=3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7 '


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def symbol_name(strtab, entry):
    name_offset = struct.unpack_from('<I', entry, 0)[0]
    end = strtab.find(b'\0', name_offset)
    return strtab[name_offset:end].decode('latin1')


def append_string(blob, text):
    offset = len(blob)
    return blob + text.encode('ascii') + b'\0', offset


def exported_symbols(path):
    exported = set()
    if not path.is_file():
        return exported
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1] in ('T', 't', 'W', 'w', 'D', 'd', 'R', 'r', 'B', 'b'):
            exported.add(parts[2])
            if parts[2].startswith('__ksymtab_'):
                exported.add(parts[2][len('__ksymtab_'):])
    return exported


def prepare_carrier(carrier_path, output_path, module_name=MODULE_NAME):
    exports = exported_symbols(KALLSYMS)
    raw = bytearray(carrier_path.read_bytes())
    with carrier_path.open('rb') as handle:
        elf = ELFFile(handle)
        symtab_section = elf.get_section_by_name('.symtab')
        strtab_section = elf.get_section_by_name('.strtab')
        this_module = elf.get_section_by_name(THIS_MODULE)
        reloc_section = elf.get_section_by_name('.rel' + THIS_MODULE)
        if not (symtab_section and strtab_section and this_module and reloc_section):
            raise SystemExit('carrier is missing required sections')
        sym_offset, sym_size, sym_entsize = (symtab_section['sh_offset'],
                                             symtab_section['sh_size'],
                                             symtab_section['sh_entsize'])
        str_offset, str_size = strtab_section['sh_offset'], strtab_section['sh_size']
        rel_offset, rel_size = reloc_section['sh_offset'], reloc_section['sh_size']
        module_offset, module_size = this_module['sh_offset'], this_module['sh_size']
        if module_size != THIS_MODULE_SIZE:
            raise SystemExit(f'unexpected this_module size {module_size}')
        symtab = bytes(raw[sym_offset:sym_offset + sym_size])
        strtab = bytes(raw[str_offset:str_offset + str_size])
        entry_count = sym_size // 16
        entries = [symtab[index * 16:(index + 1) * 16] for index in range(entry_count)]
        names = [symbol_name(strtab, entry) for entry in entries]
        if 'init_module' not in names or 'cleanup_module' not in names:
            raise SystemExit('carrier has no init_module/cleanup_module symbols')
        init_index = names.index('init_module')
        exit_index = names.index('cleanup_module')
        new_strtab = strtab
        offsets = {}
        for text in ('init_module', 'cleanup_module',
                     'carrier_init_module', 'carrier_cleanup_module'):
            new_strtab, offsets[text] = append_string(new_strtab, text)
        renamed_imports = []
        for index, name in enumerate(names):
            if not name:
                continue
            if struct.unpack_from('<H', entries[index], 14)[0] != 0:  # not SHN_UNDEF
                continue
            if name in exports:
                continue
            alias = '__' + name
            if alias in exports:
                new_strtab, name_offset = append_string(new_strtab, alias)
                entry = bytearray(entries[index])
                struct.pack_into('<I', entry, 0, name_offset)
                entries[index] = bytes(entry)
                renamed_imports.append((name, alias))
        # Rename the carrier entry points and retarget the module struct to two
        # new undefined symbols that the helper object defines.
        renamed = list(entries)
        for index, new_name in ((init_index, 'carrier_init_module'),
                                (exit_index, 'carrier_cleanup_module')):
            entry = bytearray(renamed[index])
            struct.pack_into('<I', entry, 0, offsets[new_name])
            renamed[index] = bytes(entry)
        new_init_index = entry_count
        new_exit_index = entry_count + 1
        for index, name in ((new_init_index, 'init_module'), (new_exit_index, 'cleanup_module')):
            renamed.append(struct.pack('<IIIBBH', offsets[name], 0, 0,
                                       0x12, 0, 0))  # STB_GLOBAL | STT_FUNC, SHN_UNDEF
        relocations = bytearray(raw[rel_offset:rel_offset + rel_size])
        retargeted = 0
        for offset in range(0, len(relocations), 8):
            r_info = struct.unpack_from('<I', relocations, offset + 4)[0]
            sym_index = r_info >> 8
            if sym_index == init_index:
                struct.pack_into('<I', relocations, offset + 4,
                                 (new_init_index << 8) | (r_info & 0xFF))
                retargeted += 1
            elif sym_index == exit_index:
                struct.pack_into('<I', relocations, offset + 4,
                                 (new_exit_index << 8) | (r_info & 0xFF))
                retargeted += 1
        if retargeted < 2:
            raise SystemExit(f'only {retargeted} init/exit relocations found')
        # Patch the embedded module name in place.
        name = module_name.encode('ascii')
        if len(name) >= NAME_LENGTH:
            raise SystemExit('module name too long')
        raw[module_offset + NAME_OFFSET:module_offset + NAME_OFFSET + NAME_LENGTH] = \
            name + b'\0' * (NAME_LENGTH - len(name))
        raw[rel_offset:rel_offset + rel_size] = relocations
        symtab_blob = b''.join(renamed)
        while len(raw) % 4:
            raw.append(0)
        new_sym_offset = len(raw)
        raw.extend(symtab_blob)
        while len(raw) % 4:
            raw.append(0)
        new_str_offset = len(raw)
        raw.extend(new_strtab)
        # Update the section headers for the replaced tables.
        shoff = struct.unpack_from('<I', raw, 0x20)[0]
        shentsize = struct.unpack_from('<H', raw, 0x2E)[0]
        shnum = struct.unpack_from('<H', raw, 0x30)[0]
        shstr = elf.get_section_by_name('.shstrtab').data()
        for index in range(shnum):
            base = shoff + index * shentsize
            name_off = struct.unpack_from('<I', raw, base)[0]
            end = shstr.find(b'\0', name_off)
            target = shstr[name_off:end].decode('latin1')
            if target == '.symtab':
                struct.pack_into('<II', raw, base + 16, new_sym_offset, len(symtab_blob))
            elif target == '.strtab':
                struct.pack_into('<II', raw, base + 16, new_str_offset, len(new_strtab))
    output_path.write_bytes(bytes(raw))
    return {'carrier_sha256': digest(carrier_path), 'retargeted_relocations': retargeted,
            'renamed_imports': renamed_imports,
            'renamed_symbols': ['init_module->carrier_init_module',
                                'cleanup_module->carrier_cleanup_module'],
            'module_name': module_name}


def audit(module_path, carrier_path, receipt, module_name=MODULE_NAME, tree=False,
          output_dir=None):
    with module_path.open('rb') as handle:
        elf = ELFFile(handle)
        if elf.header.e_type != 'ET_REL' or elf.header.e_machine != 'EM_ARM':
            raise SystemExit('module is not a little-endian ARM ET_REL')
        if not elf.little_endian:
            raise SystemExit('module is not little-endian')
        this_module = elf.get_section_by_name(THIS_MODULE)
        if this_module is None or this_module['sh_size'] != THIS_MODULE_SIZE:
            raise SystemExit('this_module section missing or wrong size')
        name = this_module.data()[NAME_OFFSET:NAME_OFFSET + NAME_LENGTH].split(b'\0')[0]
        if name != module_name.encode():
            raise SystemExit(f'module name is {name!r}')
        modinfo = elf.get_section_by_name('.modinfo').data()
        carrier_modinfo = ELFFile(carrier_path.open('rb')).get_section_by_name('.modinfo').data()
        vermagic = [part for part in modinfo.split(b'\0') if part.startswith(b'vermagic=')]
        carrier_vermagic = [part for part in carrier_modinfo.split(b'\0')
                            if part.startswith(b'vermagic=')]
        if not vermagic or vermagic != carrier_vermagic:
            raise SystemExit('vermagic differs from the pinned carrier')
        symtab = elf.get_section_by_name('.symtab')
        defined = {}
        undefined = {}
        for symbol in symtab.iter_symbols():
            if not symbol.name:
                continue
            if symbol['st_shndx'] == 'SHN_UNDEF':
                undefined[symbol.name] = symbol['st_info']['type']
            elif symbol['st_info']['type'] == 'STT_FUNC':
                defined[symbol.name] = symbol['st_value']
        for entry in ('init_module', 'cleanup_module'):
            if entry not in defined:
                raise SystemExit(f'{entry} is not a defined function')
        exports = exported_symbols(KALLSYMS)
        missing = sorted(name for name in undefined if name not in exports and not name.startswith('__this_module'))
        if missing:
            raise SystemExit('undefined symbols not exported by the live kernel: '
                             + ', '.join(missing))
        extra = {}
        if tree:
            extra = audit_tree(elf, module_path, carrier_path, output_dir, undefined,
                               defined, modinfo)
        receipt.update({
            'module_bytes': module_path.stat().st_size,
            'module_sha256': digest(module_path),
            'vermagic': vermagic[0].decode('latin1'),
            'init_value': hex(defined['init_module']),
            'cleanup_value': hex(defined['cleanup_module']),
            'undefined_symbols': sorted(undefined),
            'audit': 'ok',
        })
        receipt.update(extra)
    return receipt


def audit_tree(elf, module_path, carrier_path, output_dir, undefined, defined, modinfo):
    """Additive E0407b1 checks: the tree object must not smuggle new imports."""
    # 1. Required imports are present and the module still resolves every
    #    undefined symbol through the carrier set or the documented allowlist.
    present = set(undefined)
    missing_required = sorted(TREE_REQUIRED_IMPORTS - present)
    if missing_required:
        raise SystemExit('tree module is missing expected imports: '
                         + ', '.join(missing_required))
    carrier_undefined = set()
    redirected = (Path(output_dir) / 'carrier_redirected.ko') if output_dir else None
    if redirected is not None and redirected.is_file():
        with redirected.open('rb') as handle:
            carrier_symtab = ELFFile(handle).get_section_by_name('.symtab')
            carrier_undefined = {symbol.name for symbol in carrier_symtab.iter_symbols()
                                 if symbol.name and symbol['st_shndx'] == 'SHN_UNDEF'}
    if not carrier_undefined:
        raise SystemExit('tree audit needs carrier_redirected.ko to prove the import set')
    added = present - carrier_undefined
    unexpected = sorted(added - TREE_ALLOWED_IMPORTS - {'__this_module'})
    if unexpected:
        raise SystemExit('tree module adds unexpected imports: ' + ', '.join(unexpected))
    # 2. GPL license and pinned vermagic, independent of the carrier's copy.
    license_parts = [part for part in modinfo.split(b'\0') if part.startswith(b'license=')]
    if b'license=GPL' not in license_parts:
        raise SystemExit('tree module does not carry license=GPL')
    vermagic = [part for part in modinfo.split(b'\0') if part.startswith(b'vermagic=')]
    if not vermagic or vermagic[0].decode('latin1') != TREE_VERMAGIC:
        raise SystemExit('tree module vermagic is not the pinned image vermagic')
    # 3. The two entry points must be real functions (defined above) and the
    #    object must not define a second descriptor serializer or free path.
    for forbidden in ('save_desc_tbl', 'free_desc_tbl', 'make_config_desc',
                      'make_device_desc', 'usb_gadgetcore_ioctl'):
        if forbidden in defined:
            raise SystemExit(f'tree module must not define {forbidden}')
    # 4. Every relocation target is either a defined symbol (including local
    #    literal-pool/rodata labels), a carrier import or one of the allowlisted
    #    tree imports.  This is the relocation-level counterpart to the
    #    undefined-symbol check above.
    defined_all = {symbol.name for symbol in
                   elf.get_section_by_name('.symtab').iter_symbols()
                   if symbol.name and symbol['st_shndx'] != 'SHN_UNDEF'}
    relocation_count = 0
    targets = set()
    for section in elf.iter_sections():
        if section['sh_type'] not in ('SHT_REL', 'SHT_RELA'):
            continue
        linked = elf.get_section(section['sh_link'])
        for relocation in section.iter_relocations():
            relocation_count += 1
            symbol = linked.get_symbol(relocation['r_info_sym'])
            if symbol.name:
                targets.add(symbol.name)
    unknown_targets = sorted(targets - defined_all - present)
    if unknown_targets:
        raise SystemExit('relocations target unknown symbols: '
                         + ', '.join(unknown_targets))
    return {
        'tree_audit': 'ok',
        'tree_required_imports': sorted(TREE_REQUIRED_IMPORTS),
        'tree_added_imports': sorted(added - {'__this_module'}),
        'tree_carrier_undefined_count': len(carrier_undefined),
        'tree_defined_functions': sorted(name for name in defined),
        'tree_relocation_count': relocation_count,
        'tree_relocation_targets': sorted(targets),
        'tree_relocation_unknown_targets': [],
    }


def emit_tree_test_payload(elf_path=TREE_TEST_ELF, source=TREE_SOURCE,
                           output=TREE_PAYLOAD, object_path=TREE_TEST_OBJECT):
    """Extract the linked ARM test image so Unicorn executes the compiled bytes."""
    raw = elf_path.read_bytes()
    with elf_path.open('rb') as handle:
        elf = ELFFile(handle)
        if elf.header.e_machine != 'EM_ARM' or not elf.little_endian:
            raise SystemExit('tree test image is not little-endian ARM')
        if elf.header.e_type != 'ET_EXEC':
            raise SystemExit('tree test image is not a linked ET_EXEC')
        sections = []
        for section in elf.iter_sections():
            if not (section['sh_flags'] & 0x2):      # SHF_ALLOC
                continue
            if section['sh_size'] == 0:
                continue
            data = b'' if section['sh_type'] == 'SHT_NOBITS' else section.data()
            sections.append({'name': section.name,
                             'addr': section['sh_addr'],
                             'size': section['sh_size'],
                             'data': data.hex()})
        symbols = {}
        for table in elf.iter_sections():
            if isinstance(table, SymbolTableSection):
                for symbol in table.iter_symbols():
                    if symbol.name and symbol['st_shndx'] != 'SHN_UNDEF':
                        symbols[symbol.name] = symbol['st_value']
    payload = {
        'schema': 'e0407b1-tree-test-payload-v1',
        'elf_sha256': hashlib.sha256(raw).hexdigest(),
        'source_sha256': digest(source),
        'object_sha256': digest(object_path) if object_path.is_file() else None,
        'sections': sections,
        'symbols': symbols,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=1) + '\n', encoding='utf-8')
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit-only', action='store_true')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--name', default=None)
    parser.add_argument('--output-dir', type=Path, default=None)
    parser.add_argument('--source', type=Path, default=None,
                        help='C source recorded in the receipt')
    parser.add_argument('--tree-source', type=Path, default=None,
                        help='build the E0407b1 tree module from this source')
    parser.add_argument('--emit-tree-test-payload', action='store_true',
                        help='extract the linked ARM test image for the Unicorn model')
    args = parser.parse_args()
    if args.emit_tree_test_payload:
        payload = emit_tree_test_payload()
        print(TREE_PAYLOAD)
        print(json.dumps({key: payload[key] for key in
                          ('schema', 'elf_sha256', 'source_sha256', 'object_sha256')},
                         indent=2))
        return 0
    tree = args.tree_source is not None
    name = args.name or (TREE_NAME if tree else MODULE_NAME)
    output_dir = args.output_dir or (TREE_OUT if tree else OUT)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'final').mkdir(parents=True, exist_ok=True)
    module = output_dir / 'final' / (name + '.ko')
    receipt = {'carrier': str(CARRIER), 'module': str(module)}
    if args.tree_source is not None:
        if not args.tree_source.is_file():
            raise SystemExit(f'tree source missing: {args.tree_source}')
        receipt['tree_source'] = str(args.tree_source)
        receipt['tree_source_sha256'] = digest(args.tree_source)
    elif args.source is not None:
        receipt['source'] = str(args.source)
        receipt['source_sha256'] = digest(args.source)
    if not args.audit_only:
        if digest(CARRIER) != CARRIER_SHA:
            raise SystemExit('carrier identity mismatch')
        receipt.update(prepare_carrier(CARRIER, output_dir / 'carrier_redirected.ko', name))
    if args.prepare_only:
        manifest = output_dir / 'carrier-manifest.json'
        manifest.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print(manifest)
        return 0
    receipt = audit(module, CARRIER, receipt, name, tree=tree, output_dir=output_dir)
    manifest = output_dir / 'manifest.json'
    manifest.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(manifest)
    keys = ['module_bytes', 'module_sha256', 'vermagic', 'audit']
    if tree:
        keys += ['tree_audit', 'tree_added_imports']
    print(json.dumps({key: receipt[key] for key in keys}, indent=2))


if __name__ == '__main__':
    sys.exit(main())
