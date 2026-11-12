"""Dump Windows WPD device IDs and try to open them (host-side, read-only).

Purpose (E0355 task 3): the PMCA host PTP client reported "No Sony camera found"
while the composite MI_00 child was present as `WPD: MTP USB Device [OK]` in PnP
(VID_054C&PID_0322&MI_00). This tool distinguishes the possible causes without a
camera run:

  * WPD manager lists no device at all            -> driver/composite binding issue
  * WPD lists a device but its ID parses wrong    -> device-ID filter issue
  * WPD lists and parses it but Open fails        -> WPD/MTP session issue
  * WPD lists/opens it                            -> the PTP opener only needs to
                                                     select by instance ID

It never writes to the device: it only enumerates and calls PortableDevice::Open/
Close. Run with the repository venv python from the repo root:

    .\\venv\\Scripts\\python.exe -m tools.research.wpd_device_dump
    .\\venv\\Scripts\\python.exe -m tools.research.wpd_device_dump --open-ids

Exit codes: 0 = enumeration completed (even with zero devices), 2 = WPD/COM
unavailable, 3 = bad arguments.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / 'Sony-PMCA-RE') not in sys.path:
    sys.path.insert(0, str(ROOT / 'Sony-PMCA-RE'))

VID_PID_RE = re.compile(r'(?:#|\\|\\)vid_([0-9a-f]{4})&pid_([0-9a-f]{4})(?:&|#|\\|\\)',
                         re.IGNORECASE)
MI_RE = re.compile(r'(?:&|\\)mi_([0-9a-f]{2})(?:&|#|\\\\)', re.IGNORECASE)


def parse_device_id(device_id: str):
    """Return (vid, pid, mi) parsed case-insensitively from a WPD DeviceID."""
    match = VID_PID_RE.search(device_id or '')
    if not match:
        return None, None, None
    mi = MI_RE.search(device_id)
    return int(match.group(1), 16), int(match.group(2), 16), (int(mi.group(1), 16) if mi else None)


def enumerate_wpd():
    """Enumerate WPD devices through the PMCA WPD binding (comtypes)."""
    from pmca.usb.driver.windows.wpd import _listDevices  # noqa: PLC0415
    return list(_listDevices())


def open_wpd(device):
    """Open/close a WPD device read-only; returns (ok, detail)."""
    from pmca.usb.driver.windows.wpd import PortableDevice, CreateObject, PortableDeviceValues  # noqa: PLC0415
    device_object = CreateObject(PortableDevice)
    try:
        device_object.Open(device.handle, CreateObject(PortableDeviceValues))
    except Exception as exc:  # COM errors are reported, never swallowed as success
        return False, f'{type(exc).__name__}: {exc}'
    try:
        device_object.Close()
    except Exception:
        pass
    return True, 'open/close ok'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--open-ids', action='store_true',
                        help='also attempt PortableDevice::Open on every enumerated device')
    parser.add_argument('--json', action='store_true', help='emit JSON instead of text')
    args = parser.parse_args(argv)

    try:
        devices = enumerate_wpd()
    except ImportError:
        print('WPD binding unavailable: pmca/comtypes import failed', file=sys.stderr)
        return 2
    except Exception as exc:
        print(f'WPD enumeration failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2

    records = []
    for device in devices:
        handle = str(device.handle)
        vid, pid, mi = parse_device_id(handle)
        record = {
            'device_id': handle,
            'vid': vid,
            'pid': pid,
            'mi': mi,
            'sony': vid == 0x054C,
            'composite_child': mi is not None,
        }
        if args.open_ids:
            ok, detail = open_wpd(device)
            record['open_ok'] = ok
            record['open_detail'] = detail
        records.append(record)

    if args.json:
        import json
        print(json.dumps({'device_count': len(records), 'devices': records}, indent=2))
    else:
        print(f'WPD devices: {len(records)}')
        for record in records:
            extra = '' if 'open_ok' not in record else f" open_ok={record['open_ok']} ({record['open_detail']})"
            print(f"  vid={record['vid']} pid={record['pid']} mi={record['mi']} "
                  f"sony={record['sony']} composite={record['composite_child']}{extra}")
            print(f"    {record['device_id']}")
        sony = [r for r in records if r['sony']]
        if not sony:
            print('No VID_054C WPD device listed. If PnP shows MI_00 as "MTP USB Device", '
                  'the composite child is not exposed through PortableDeviceManager in this '
                  'state; the PTP path cannot use WPD (see E0355).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
