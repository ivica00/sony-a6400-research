"""One-click USB debugger setup and unknown-camera onboarding bundle generator.

Flow:
1. Ensure ``Sony-PMCA-RE`` (``pmca``) is importable (fetching if missing).
2. Auto-detect the connected Sony camera in normal Mass Storage mode
   (model name, product code, firmware version).
3. Enter Senser once to read ``/usr/kmod/usb_extcmd.ko``,
   ``/usr/lib/libusbcmd.so``, and ``/etc/ld.so.preload`` (handling error 130).
4. Branch A (supported & ABI-compatible):
   Ensure prebuilt payloads exist locally (downloading & SHA-256 verifying from
   GitHub Releases if missing), upload & verify read-back, update
   ``/etc/ld.so.preload``, and run post-boot ``camera_debugger.py info`` check.
5. Branch B (new/unsupported model or ABI mismatch):
   Write nothing to the camera; collect read-only driver/libc/proc telemetry
   into ``artifacts/onboarding/<MODEL>-FW<VER>-<TS>.zip`` for developer review.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.a6400.targets.usb_debugger_compat import (  # noqa: E402
    DebuggerTargetSpec,
    PAYLOAD_ASSETS,
    PMCA_ARCHIVE_URL,
    VERIFIED_LIBUSBCMD_SHA256,
    VERIFIED_USB_EXTCMD_NORMALIZED_SHA256,
    find_debugger_target_by_model,
    load_reference_usb_extcmd,
    verify_camera_debugger_compatibility,
)
from tools.deploy_native_usb_debugger import (  # noqa: E402
    read_preload_safe,
    upload_and_verify_debugger,
)
from tools.research.elf_metadata_identity import normalize_elf_metadata  # noqa: E402

ONBOARDING_PROC_FILES = (
    '/proc/version',
    '/proc/cpuinfo',
    '/proc/modules',
    '/proc/partitions',
    '/proc/cmdline',
    '/proc/iomem',
)


def _download_bytes(url: str, timeout: int = 30) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()


def ensure_pmca_on_path(root: Path = ROOT, fetcher=_download_bytes) -> Path:
    """Locate ``Sony-PMCA-RE`` or fetch its archive into ``.cache/Sony-PMCA-RE``."""
    candidates = (
        root / 'Sony-PMCA-RE',
        root.parent / 'Sony-PMCA-RE-master',
        root.parent / 'Sony-PMCA-RE',
        root / '.cache' / 'Sony-PMCA-RE',
    )
    for candidate in candidates:
        if (candidate / 'pmca').is_dir():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            return candidate

    cache_dir = root / '.cache' / 'Sony-PMCA-RE'
    cache_dir.mkdir(parents=True, exist_ok=True)
    archive_bytes = fetcher(PMCA_ARCHIVE_URL)
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            parts = Path(member.filename).parts
            if len(parts) < 2 or 'pmca' not in parts:
                continue
            rel = Path(*parts[1:])
            target = cache_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(member))
    if not (cache_dir / 'pmca').is_dir():
        raise RuntimeError('Downloaded Sony-PMCA-RE archive did not contain pmca/')
    if str(cache_dir) not in sys.path:
        sys.path.insert(0, str(cache_dir))
    return cache_dir


def ensure_payload_binaries(
    spec: DebuggerTargetSpec,
    root: Path = ROOT,
    fetcher=_download_bytes,
) -> dict[str, Path]:
    """Ensure debugger payloads exist locally and match pinned SHA-256 digests."""
    resolved: dict[str, Path] = {}
    for rel in (spec.payload_daemon, spec.payload_launcher):
        meta = PAYLOAD_ASSETS.get(rel)
        if meta is None:
            raise KeyError(f'No pinned asset metadata for payload {rel!r}')
        dest = root / rel
        expected_sha = str(meta['sha256'])
        expected_size = int(meta['size'])
        if dest.is_file():
            data = dest.read_bytes()
            if len(data) == expected_size and hashlib.sha256(data).hexdigest() == expected_sha:
                resolved[rel] = dest
                continue
            raise RuntimeError(
                f'Local payload {rel} failed integrity check '
                f'(got {len(data)} B / {hashlib.sha256(data).hexdigest()}, '
                f'expected {expected_size} B / {expected_sha})'
            )

        url = str(meta['url'])
        print(f'Downloading prebuilt {meta["filename"]} from {url}...')
        data = fetcher(url)
        actual_sha = hashlib.sha256(data).hexdigest()
        if len(data) != expected_size or actual_sha != expected_sha:
            raise RuntimeError(
                f'Downloaded payload {rel} failed SHA-256 verification '
                f'(got {len(data)} B / {actual_sha}, expected {expected_size} B / {expected_sha})'
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        resolved[rel] = dest
    return resolved


def detect_msc_camera(driver_name: str | None = None) -> dict[str, str]:
    """Query connected Sony camera model, product code, and firmware in MSC mode."""
    from pmca.commands.usb import importDriver, getDevice
    from pmca.usb.sony import SonyExtCmdCamera, SonyExtCmdDevice, SonyUpdaterCamera

    with importDriver(driver_name) as driver:
        device = getDevice(driver)
        if not device or not isinstance(device, SonyExtCmdDevice):
            raise RuntimeError(
                'No Sony camera found in Mass Storage / MTP mode. '
                'Connect the camera in normal Mass Storage mode and try again.'
            )
        ext = SonyExtCmdCamera(device)
        info = ext.getCameraInfo()
        updater = SonyUpdaterCamera(device)
        updater.init()
        firmware_old, _ = updater.getFirmwareVersion()
        return {
            'model_name': str(info.modelName).strip(),
            'model_code': str(info.modelCode).strip(),
            'firmware_version': str(firmware_old).strip(),
        }


def _safe_slug(text: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '-', text.strip()).strip('-') or 'unknown'


def build_onboarding_bundle(
    cam,
    identity: dict[str, str],
    actual_ko: bytes,
    actual_lib: bytes,
    previous_preload: bytes,
    preload_existed: bool,
    compat_result: dict | None = None,
    root: Path = ROOT,
) -> Path:
    """Create a read-only onboarding ``.zip`` for an unsupported/unverified body."""
    ts = datetime.now().strftime('%Y%m%d-%H%M%S')
    slug = f"{_safe_slug(identity['model_name'])}-FW{_safe_slug(identity['firmware_version'])}-{ts}"
    out_dir = root / 'artifacts/onboarding'
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f'{slug}.zip'

    ko_norm = normalize_elf_metadata(actual_ko)
    lib_sha = hashlib.sha256(actual_lib).hexdigest()
    ko_sha = hashlib.sha256(actual_ko).hexdigest()

    libc_bytes = None
    libc_error = None
    for libc_path in ('/lib/libc.so.6', '/lib/libc.so'):
        try:
            libc_bytes = cam.readFile(libc_path)
            break
        except Exception as exc:
            libc_error = str(exc)

    proc_dumps: dict[str, str] = {}
    for proc_path in ONBOARDING_PROC_FILES:
        try:
            proc_dumps[proc_path] = cam.readFile(proc_path).decode('utf-8', errors='replace')
        except Exception as exc:
            proc_dumps[proc_path] = f'<read error: {exc}>'

    report = {
        'identity': {
            'model_name': identity['model_name'],
            'model_code': identity['model_code'],
            'firmware_version': identity['firmware_version'],
        },
        'preload_existed': preload_existed,
        'usb_extcmd': {
            'bytes': len(actual_ko),
            'sha256': ko_sha,
            'normalized_valid': bool(ko_norm.get('valid')),
            'normalized_sha256': ko_norm.get('normalized_sha256'),
            'normalized_reason': ko_norm.get('reason'),
            'matches_verified_baseline_normalized': (
                ko_norm.get('normalized_sha256') == VERIFIED_USB_EXTCMD_NORMALIZED_SHA256
            ),
        },
        'libusbcmd': {
            'bytes': len(actual_lib),
            'sha256': lib_sha,
            'matches_verified_baseline': lib_sha == VERIFIED_LIBUSBCMD_SHA256,
        },
        'libc': {
            'bytes': len(libc_bytes) if libc_bytes is not None else 0,
            'sha256': hashlib.sha256(libc_bytes).hexdigest() if libc_bytes is not None else None,
            'error': None if libc_bytes is not None else libc_error,
        },
        'existing_compat_result': compat_result,
    }

    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('camera_identity.json', json.dumps(report['identity'], indent=2))
        zf.writestr('compatibility_report.json', json.dumps(report, indent=2))
        zf.writestr('usb_extcmd.ko', actual_ko)
        zf.writestr('libusbcmd.so', actual_lib)
        if libc_bytes is not None:
            zf.writestr('libc.so.6', libc_bytes)
        zf.writestr('ld.so.preload', previous_preload)
        for proc_path, text in proc_dumps.items():
            zf.writestr('proc/' + Path(proc_path).name + '.txt', text)

    return zip_path


def run_setup(
    *,
    check_only: bool = False,
    skip_post_boot_test: bool = False,
    root: Path = ROOT,
) -> int:
    ensure_pmca_on_path(root)
    from pmca.commands.usb import senserShellCommand

    print('[1/4] Detecting Sony camera in Mass Storage mode...')
    identity = detect_msc_camera()
    print(
        f"      Detected: {identity['model_name']} "
        f"(code={identity['model_code']}, FW={identity['firmware_version']})"
    )

    spec = find_debugger_target_by_model(
        identity['model_name'],
        identity['firmware_version'],
    )
    if spec is not None and not check_only:
        print('[2/4] Ensuring prebuilt debugger binaries...')
        ensure_payload_binaries(spec, root=root)
    else:
        print('[2/4] Skipping payload download (read-only / onboarding mode).')

    outcome: dict[str, object] = {'branch': None}

    def on_senser(cam):
        previous_preload, preload_existed = read_preload_safe(cam)
        actual_ko = cam.readFile('/usr/kmod/usb_extcmd.ko')
        actual_lib = cam.readFile('/usr/lib/libusbcmd.so')

        compat = None
        if spec is not None:
            _, ref_ko = load_reference_usb_extcmd(spec, root)
            compat = verify_camera_debugger_compatibility(spec, actual_ko, actual_lib, ref_ko)

        if spec is not None and compat is not None and compat['compatible']:
            outcome['branch'] = 'supported'
            if check_only:
                print('[3/4] Read-only compatibility check PASSED (no files written).')
                return
            dest = root / 'artifacts/hardware' / (
                f'native-usb-debug-deploy-{spec.target_id}-'
                + datetime.now().strftime('%Y%m%d-%H%M%S')
            )
            dest.mkdir(parents=True, exist_ok=False)
            (dest / 'ld.so.preload.before').write_bytes(previous_preload)
            (dest / 'kmod__usb_extcmd.ko').write_bytes(actual_ko)
            (dest / 'lib__libusbcmd.so').write_bytes(actual_lib)
            manifest = {
                'target_id': spec.target_id,
                'model_name': spec.model_name,
                'qualification': spec.qualification,
                'preload_existed_before': preload_existed,
                'bootstrap_mode': 'Senser',
                'operating_transport': 'native Sony USB external command',
                'feature': 35,
                'network_listeners': False,
                'compatibility': compat,
                'files': {},
            }
            upload_and_verify_debugger(cam, spec, previous_preload, dest, manifest)
            outcome['manifest_dir'] = dest
            return

        outcome['branch'] = 'onboarding'
        bundle_path = build_onboarding_bundle(
            cam,
            identity,
            actual_ko,
            actual_lib,
            previous_preload,
            preload_existed,
            compat_result=compat,
            root=root,
        )
        outcome['bundle_path'] = bundle_path

    print('[3/4] Inspecting camera driver/ABI via Senser...')
    senserShellCommand(driverName='libusb', complete=on_senser)

    if outcome['branch'] == 'onboarding':
        bundle_path = outcome['bundle_path']
        print('\n[RESULT] Camera is not yet qualified for automatic install.')
        print('         No files were modified on your camera.')
        print(f'         Please send this onboarding bundle to the developer:\n         {bundle_path}')
        return 0

    if check_only:
        return 0

    print(f"[4/4] Deployed and verified! Receipt: {outcome.get('manifest_dir')}")
    if skip_post_boot_test:
        return 0

    input(
        '\nPower-cycle your camera (OFF -> unplug USB -> ON -> replug in Mass Storage mode), '
        'then press Enter to run the post-boot debugger check...'
    )
    for cmd in (['info'], ['exec', 'uname -a']):
        subprocess.run(
            [sys.executable, str(root / 'tools/camera_debugger.py'), *cmd],
            check=True,
            cwd=root,
        )
    print('\n[READY] Native root USB debugger is active in normal Mass Storage mode!')
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description='One-click native Sony USB debugger setup and onboarding collector.'
    )
    parser.add_argument(
        '--check-only',
        action='store_true',
        help='Read-only compatibility check or onboarding collection (never writes to camera).',
    )
    parser.add_argument(
        '--no-wait',
        action='store_true',
        help='Skip interactive post-boot camera_debugger.py verification prompt.',
    )
    args = parser.parse_args(argv)
    return run_setup(check_only=args.check_only, skip_post_boot_test=args.no_wait)


if __name__ == '__main__':
    sys.exit(main())
