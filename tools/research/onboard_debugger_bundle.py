"""Developer-side helper to inspect an end-user onboarding ``.zip`` bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.a6400.targets.usb_debugger_compat import (  # noqa: E402
    VERIFIED_LIBUSBCMD_SHA256,
    VERIFIED_LIBUSBCMD_SIZE,
    VERIFIED_USB_EXTCMD_NORMALIZED_SHA256,
    VERIFIED_USB_EXTCMD_SIZE,
)
from tools.research.elf_metadata_identity import normalize_elf_metadata  # noqa: E402


def _target_id_from_model(model_name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', model_name.strip().lower()).strip('_')


def inspect_and_unpack_bundle(bundle_path: Path, root: Path = ROOT) -> dict:
    """Extract an onboarding ``.zip`` into ``artifacts/hardware/`` and evaluate ABI match."""
    with zipfile.ZipFile(bundle_path, 'r') as zf:
        identity = json.loads(zf.read('camera_identity.json').decode('utf-8'))
        actual_ko = zf.read('usb_extcmd.ko')
        actual_lib = zf.read('libusbcmd.so')

        model_name = identity['model_name']
        fw_ver = identity['firmware_version']
        target_id = _target_id_from_model(model_name)
        pull_dir = root / 'artifacts/hardware' / f'{target_id}-{fw_ver}-pull'
        pull_dir.mkdir(parents=True, exist_ok=True)
        for member in zf.infolist():
            if member.is_dir():
                continue
            dest = pull_dir / member.filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(member))

    ko_norm = normalize_elf_metadata(actual_ko)
    ko_sha = hashlib.sha256(actual_ko).hexdigest()
    lib_sha = hashlib.sha256(actual_lib).hexdigest()

    ko_ok = (
        len(actual_ko) == VERIFIED_USB_EXTCMD_SIZE
        and bool(ko_norm.get('valid'))
        and ko_norm.get('normalized_sha256') == VERIFIED_USB_EXTCMD_NORMALIZED_SHA256
    )
    lib_ok = len(actual_lib) == VERIFIED_LIBUSBCMD_SIZE and lib_sha == VERIFIED_LIBUSBCMD_SHA256

    snippet = None
    if ko_ok and lib_ok:
        snippet = (
            f'    "{target_id}": DebuggerTargetSpec(\n'
            f'        target_id="{target_id}",\n'
            f'        model_name="{model_name}",\n'
            f'        firmware_versions=("{fw_ver}",),\n'
            f'        qualification="qualified_offline",\n'
            f'        usb_extcmd_size=VERIFIED_USB_EXTCMD_SIZE,\n'
            f'        usb_extcmd_normalized_sha256=VERIFIED_USB_EXTCMD_NORMALIZED_SHA256,\n'
            f'        usb_extcmd_exact_sha256s=(\n'
            f'            "{ko_sha}",\n'
            f'        ),\n'
            f'        usb_extcmd_reference_paths=(\n'
            f'            "artifacts/hardware/{target_id}-{fw_ver}-pull/usb_extcmd.ko",\n'
            f'        ),\n'
            f'        libusbcmd_size=VERIFIED_LIBUSBCMD_SIZE,\n'
            f'        libusbcmd_sha256=VERIFIED_LIBUSBCMD_SHA256,\n'
            f'    ),'
        )

    return {
        'target_id': target_id,
        'model_name': model_name,
        'firmware_version': fw_ver,
        'pull_dir': pull_dir,
        'baseline_compatible': ko_ok and lib_ok,
        'usb_extcmd_match': ko_ok,
        'libusbcmd_match': lib_ok,
        'usb_extcmd_sha256': ko_sha,
        'usb_extcmd_normalized_sha256': ko_norm.get('normalized_sha256'),
        'libusbcmd_sha256': lib_sha,
        'spec_snippet': snippet,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Unpack and evaluate a camera onboarding zip.')
    parser.add_argument('bundle', type=Path, help='Path to onboarding .zip bundle.')
    args = parser.parse_args(argv)
    result = inspect_and_unpack_bundle(args.bundle)
    print(f"Unpacked to: {result['pull_dir']}")
    print(f"Model: {result['model_name']} (FW {result['firmware_version']})")
    print(f"usb_extcmd.ko baseline match: {result['usb_extcmd_match']}")
    print(f"libusbcmd.so  baseline match: {result['libusbcmd_match']}")
    if result['spec_snippet']:
        print('\nReady to add to src/a6400/targets/usb_debugger_compat.py:\n')
        print(result['spec_snippet'])
    else:
        print('\nABI differs from verified baseline — inspect unpacked binaries before adding.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
