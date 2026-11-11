"""Build the ZV-E10 UVC enablement manifest for a6400 (E0321).

Offline only: hash-pins the ZV-E10 UVC chain, parses the a6400 `devno.ko`
device-node table and emits a fail-closed manifest.  No camera access, no
deployment, no module loading.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from elftools.elf.elffile import ELFFile

from src.a6400.execution.zve10_uvc_enablement import (
    ZVE10_UVC_COMPONENTS,
    ZVE10_REQUIRED_USB_NODES,
    A6400_PROVIDER_MODULES,
    compare_components,
    enablement_verdict,
    hash_file,
    module_vermagic,
    parse_devno_table,
)

A6400_IMAGE = (ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/'
               '0700_part_image/dev/nflasha15_unpacked')
A6400_DEVNO = (ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/'
               '0700_part_image/dev/nflasha7_unpacked/kmod/devno.ko')
ZVE10_IMAGE = (ROOT / 'firmware/extracted_zve10_v203_linuxnames/'
               'firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked')
ZVE10_DEVNO = (ROOT / 'firmware/extracted_zve10_v203_linuxnames/'
               'firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/'
               'kmod/devno.ko')
OUTPUT = ROOT / 'artifacts/analysis/e0321-uvc-enablement-manifest.json'


def devno_table_bytes(path):
    """Return the raw `udif_devnodes` object bytes from a devno.ko module."""
    with open(path, 'rb') as handle:
        elf = ELFFile(handle)
        symtab = elf.get_section_by_name('.symtab')
        if symtab is None:
            return b''
        for symbol in symtab.iter_symbols():
            if symbol.name == 'udif_devnodes':
                section = elf.get_section(symbol['st_shndx'])
                data = section.data()
                start = symbol['st_value']
                return data[start:start + symbol['st_size']]
    return b''


def locate_component(base, name):
    for folder in ('kmod', 'lib'):
        candidate = base / folder / name
        if candidate.is_file():
            return candidate
    return None


def build_manifest():
    present = {}
    component_paths = {}
    for name in ZVE10_UVC_COMPONENTS:
        if name == 'devno.ko':
            path = A6400_DEVNO
        else:
            path = locate_component(A6400_IMAGE, name)
        if path is not None:
            present[name] = hash_file(path)
            component_paths[name] = {
                'tree': 'a6400',
                'path': str(path.relative_to(ROOT)),
            }
    components = compare_components(present)

    zve10_reference = {}
    for name, pinned in ZVE10_UVC_COMPONENTS.items():
        if name == 'devno.ko':
            path = ZVE10_DEVNO
        else:
            path = locate_component(ZVE10_IMAGE, name)
        if path is None:
            zve10_reference[name] = 'missing'
            continue
        found = hash_file(path)
        zve10_reference[name] = (
            'verified' if found['size'] == pinned['size'] and
            found['sha256'] == pinned['sha256'] else 'hash_mismatch')

    a6400_devno = parse_devno_table(devno_table_bytes(A6400_DEVNO),
                                    A6400_DEVNO.read_bytes())
    zve10_devno = parse_devno_table(devno_table_bytes(ZVE10_DEVNO),
                                    ZVE10_DEVNO.read_bytes())

    zve10_vermagic = module_vermagic(ZVE10_IMAGE / 'kmod/usbg_video.ko')
    a6400_vermagic = module_vermagic(A6400_IMAGE / 'kmod/usbg_cmn.ko')
    verdict = enablement_verdict(
        components, a6400_devno, a6400_vermagic == zve10_vermagic)

    providers = {}
    for module in A6400_PROVIDER_MODULES:
        path = A6400_IMAGE / 'kmod' / module
        providers[module] = ('present' if path.is_file() else 'missing')

    manifest = {
        'e': 'E0321',
        'objective': 'enable ZV-E10 2.03 UVC chain on the a6400 target',
        'zve10_components': {
            name: {
                'size': row['size'],
                'sha256': row['sha256'],
                'role': row['role'],
            } for name, row in ZVE10_UVC_COMPONENTS.items()
        },
        'component_check': components,
        'zve10_reference_check': zve10_reference,
        'component_paths': component_paths,
        'required_usb_nodes': ZVE10_REQUIRED_USB_NODES,
        'a6400_devno_sha256': hash_file(A6400_DEVNO)['sha256'],
        'a6400_usb_nodes': {
            path: {'major': row['major'], 'minor': row['minor']}
            for path, row in sorted(a6400_devno.items())
            if path.startswith('usb/')
        },
        'zve10_usb_nodes': {
            path: {'major': row['major'], 'minor': row['minor']}
            for path, row in sorted(zve10_devno.items())
            if path.startswith('usb/')
        },
        'vermagic': {'zve10_usbg_video': zve10_vermagic,
                     'a6400_usbg_cmn': a6400_vermagic,
                     'equal': zve10_vermagic == a6400_vermagic},
        'a6400_provider_modules': providers,
        'verdict': verdict,
        'boundaries': [
            'no module load, no camera write, no mode change',
            'symbol/vermagic parity is not loadability proof',
            'usbg_video ioctl/buffer behaviour remains fail-closed (E0319/E0320)',
            'host USB enumeration/SET_CONFIG contract still open (E0318)',
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def main():
    manifest = build_manifest()
    verdict = manifest['verdict']
    print('verdict:', verdict['verdict'])
    for reason in verdict['reasons']:
        print(' -', reason)
    print('component check:')
    for name, row in manifest['component_check'].items():
        print(' ', name, row['status'])
    print('manifest:', OUTPUT.relative_to(ROOT))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
