"""Static audit of the UVC/PTP candidate descriptor matrix and native endpoint rule."""
import hashlib
import json
import re
from pathlib import Path
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT

SOURCE = ROOT / 'tools/native_camera/uvc_ptp_descriptors.c'


def main():
    text = SOURCE.read_text(encoding='utf-8')
    checks = []
    def check(name, value):
        if not value:
            raise AssertionError(name)
        checks.append(name)

    ptp = [int(x, 16) for x in re.findall(r'ptp_endpoints\[\d\]\.address=0x([0-9a-fA-F]+)', text)]
    video = int(re.search(r'video_endpoint\.address=0x([0-9a-fA-F]+)', text).group(1), 16)
    vs_header = int(re.search(r'vs_extra\[6\]=0x([0-9a-fA-F]+)', text).group(1), 16)
    iad = [int(x) for x in re.search(r'iad\[8\]=\{([^}]*)\}', text).group(1).split(',')]
    interface_count = int(re.search(r'config\.interface_count=(\d+)', text).group(1))
    hs_ptp = [int(x) for x in re.findall(r'ptp_endpoints\[\d\]\.max_packet=(\d+)', text)]
    hs_video = int(re.search(r'video_endpoint\.max_packet=(\d+)', text).group(1))
    fs_packets = [int(x) for x in re.findall(r'fs_endpoints\[\d\]\.max_packet=(\d+)', text)]
    fs_interval = int(re.search(r'fs_endpoints\[2\]\.interval=(\d+)', text).group(1))
    vc_ifnr = int(re.search(r'vc_extra\[12\]=(\d+)', text).group(1))
    alternates = {}
    for index, endpoint_count in re.findall(r'alternates\[(\d)\]\.endpoint_count=(\d+)', text):
        alternates[int(index)] = int(endpoint_count)
    classes = {}
    for index, klass in re.findall(r'alternates\[(\d)\]\.klass=(\w+)', text):
        classes[int(index)] = int(klass, 0)
    subclasses = {}
    for index, sub in re.findall(r'alternates\[(\d)\]\.subclass=(\w+)', text):
        subclasses[int(index)] = int(sub, 0)

    endpoints = ptp + [video]
    directionless = [address & 15 for address in endpoints]
    check('ptp-endpoints-81-02-83', ptp == [0x81, 0x02, 0x83])
    check('video-endpoint-84', video == 0x84)
    check('vs-header-matches-video-endpoint', vs_header == video)
    check('directionless-endpoints-unique', len(set(directionless)) == len(directionless))
    check('old-82-would-collide-with-ptp-out-02', (0x82 & 15) == (0x02 & 15))
    check('iad-length-type', iad[:2] == [8, 11])
    check('iad-groups-vc1-vs2', iad[2:4] == [1, 2])
    check('iad-uvc-class-subclass', iad[4:6] == [14, 3])
    check('three-interfaces', interface_count == 3 and sorted(alternates) == [0, 2])
    check('vc-bainterfacenr-is-2', vc_ifnr == 2)
    check('ptp-class-6-1-1', classes.get(0) == 6 and subclasses.get(0) == 1)
    check('vc-class-14-1', classes.get(1) == 0x0e and subclasses.get(1) == 1)
    check('vs-class-14-2', classes.get(2) == 0x0e and subclasses.get(2) == 2)
    check('hs-ptp-maxpacket-512-512-32', hs_ptp == [512, 512, 32])
    check('hs-video-maxpacket-512', hs_video == 512)
    check('fs-ptp-maxpacket-64-64', fs_packets == [64, 64])
    check('fs-third-inherits-hs-32', hs_ptp[2] == 32)
    check('fs-interrupt-interval-10', fs_interval == 10)

    matrix = {
        'interfaces': [
            {'number': 0, 'class': 6, 'subclass': 1, 'protocol': 1,
             'endpoints': [hex(x) for x in ptp]},
            {'number': 1, 'class': 0x0e, 'subclass': 1, 'protocol': 0, 'endpoints': []},
            {'number': 2, 'class': 0x0e, 'subclass': 2, 'protocol': 0,
             'endpoints': [hex(video)]},
        ],
        'iad': iad,
        'directionless_addresses': directionless,
        'old_video_endpoint': '0x82',
        'hs_max_packets': hs_ptp + [hs_video],
        'fs_max_packets': fs_packets,
    }
    out = ROOT / 'artifacts/analysis/uvc-ptp-descriptor-matrix-e0240'
    out.mkdir(parents=True, exist_ok=True)
    report = {
        'status': 'offline_descriptor_matrix_passed',
        'source': 'tools/native_camera/uvc_ptp_descriptors.c',
        'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        'checks': checks,
        'matrix': matrix,
        'original_scan_execution': 'artifacts/analysis/uvc-ptp-config-endpoints-e0210/manifest.json',
        'limitations': [
            'Static source audit; it does not execute the Sony serializer or allocate endpoints.',
            'Original SET_CONFIGURATION endpoint scan execution is recorded separately by probe_uvc_ptp_config_endpoints.',
            'Descriptor acceptance is not Windows binding, streaming or PTP transaction proof.',
        ],
    }
    (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'{len(checks)} descriptor-matrix checks passed; endpoints '
          + ','.join(hex(x) for x in endpoints) + '; directionless ' + ','.join(str(x) for x in directionless))


if __name__ == '__main__':
    main()
