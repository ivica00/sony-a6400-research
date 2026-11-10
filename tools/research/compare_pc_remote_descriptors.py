"""Offline diff: original PC Remote descriptors vs the composite candidate.

Reads retained captures only. No USB, camera or WPD access.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PC_REMOTE = ROOT / 'artifacts/hardware/uvc-ptp-coexistence-e0152/pc-remote-hub-descriptors.json'
COMPOSITE = ROOT / 'artifacts/hardware/uvc-ptp-endpoint84-e0210/composite-hub-descriptors.json'


def iad_present(raw):
    """Walk a configuration descriptor chain and report an IAD (type 11)."""
    if len(raw) < 9:
        return None
    index = 9
    while index + 1 < len(raw):
        length = raw[index]
        if length < 2 or index + length > len(raw):
            return None
        if raw[index + 1] == 11:
            return True
        index += length
    return False


def config_summary(config):
    raw = bytes.fromhex(config['raw_hex'])
    interfaces = []
    for interface in config.get('interfaces', []):
        interfaces.append({
            'number': interface['number'],
            'alternate': interface['alternate'],
            'class': interface['class'],
            'subclass': interface['subclass'],
            'protocol': interface['protocol'],
            'endpoints': [{
                'address': endpoint['address'],
                'attributes': endpoint['attributes'],
                'max_packet': endpoint['max_packet'],
                'interval': endpoint['interval'],
            } for endpoint in interface.get('endpoints', [])],
        })
    return {
        'value': config['value'],
        'raw_bytes': len(raw),
        'iad_present': iad_present(raw),
        'interface_count': len(interfaces),
        'interfaces': interfaces,
    }


def device_summary(device):
    descriptor = bytes.fromhex(device.get('device_descriptor_hex', ''))
    vid = device.get('vid', 0)
    pid = device.get('pid', 0)
    if isinstance(vid, str):
        vid = int(vid, 0)
    if isinstance(pid, str):
        pid = int(pid, 0)
    return {
        'vid': hex(vid),
        'pid': hex(pid),
        'device_descriptor_bytes': len(descriptor),
        'device_class': list(descriptor[4:7]) if len(descriptor) >= 7 else None,
        'configurations': [config_summary(c) for c in device.get('configurations', [])],
    }


def diff_summaries(pc, composite):
    pc_config = pc['configurations'][0]
    composite_config = composite['configurations'][0]
    pc_ptp = pc_config['interfaces'][0] if pc_config['interfaces'] else None
    composite_ptp = composite_config['interfaces'][0] if composite_config['interfaces'] else None
    return {
        'device_class_pc': pc['device_class'],
        'device_class_composite': composite['device_class'],
        'device_class_changed': pc['device_class'] != composite['device_class'],
        'interface_count_pc': pc_config['interface_count'],
        'interface_count_composite': composite_config['interface_count'],
        'iad_pc': pc_config['iad_present'],
        'iad_composite': composite_config['iad_present'],
        'ptp_interface_equal': pc_ptp == composite_ptp,
        'ptp_interface_pc': pc_ptp,
        'ptp_interface_composite': composite_ptp,
        'composite_extra_interfaces': composite_config['interfaces'][1:] if composite_config['interface_count'] > 1 else [],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pc', type=Path, default=PC_REMOTE)
    parser.add_argument('--composite', type=Path, default=COMPOSITE)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    pc_data = json.loads(args.pc.read_text())
    composite_data = json.loads(args.composite.read_text())
    pc = device_summary(pc_data['devices'][0])
    composite = device_summary(composite_data['devices'][0])
    result = diff_summaries(pc, composite)
    report = {'status': 'offline_descriptor_diff', 'pc_capture': str(args.pc), 'composite_capture': str(args.composite),
              'pc': pc, 'composite': composite, 'diff': result}
    if args.output_dir:
        out = args.output_dir.resolve()
        if not out.is_relative_to(ROOT / 'artifacts'):
            parser.error('Output must be under artifacts')
        out.mkdir(parents=True, exist_ok=False)
        (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
