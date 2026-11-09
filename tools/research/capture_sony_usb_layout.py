"""Read Sony USB descriptors without claiming interfaces or changing modes.

Run once in MSC and once in PC Remote to compare endpoint assignments before
building a combined UVC/PTP descriptor set. Does not open a PTP session.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def capture():
    sys.path.insert(0, str(ROOT / 'Sony-PMCA-RE'))
    from pmca.commands.usb import importDriver
    import usb.core

    devices = []
    with importDriver('libusb'):
        for device in usb.core.find(find_all=True, idVendor=0x054C):
            configurations = []
            for config in device:
                interfaces = []
                for interface in config:
                    interfaces.append({
                        'number': interface.bInterfaceNumber,
                        'alternate': interface.bAlternateSetting,
                        'class': interface.bInterfaceClass,
                        'subclass': interface.bInterfaceSubClass,
                        'protocol': interface.bInterfaceProtocol,
                        'endpoints': [{
                            'address': hex(ep.bEndpointAddress),
                            'attributes': ep.bmAttributes,
                            'max_packet': ep.wMaxPacketSize,
                            'interval': ep.bInterval,
                        } for ep in interface],
                    })
                configurations.append({'value': config.bConfigurationValue,
                                       'interfaces': interfaces})
            devices.append({'vid': hex(device.idVendor),
                            'pid': hex(device.idProduct),
                            'configurations': configurations})
    return {'captured_utc': datetime.now(timezone.utc).isoformat(),
            'devices': devices, 'read_only': True, 'mode_switch': False,
            'limitations': ['Descriptors do not prove sensor activity, PTP control, or concurrent UVC/PTP operation.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = capture()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['devices'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
