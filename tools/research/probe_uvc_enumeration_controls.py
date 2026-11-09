"""Verify compiled enumeration-only bridge does not enter video controls."""
import argparse
import hashlib
import json
from pathlib import Path
from tools.research.uvc_callback_bridge_probe import Machine, KERNEL, KSHA, ROOT, REQUEST


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build-dir', type=Path, required=True)
    args = p.parse_args()
    build = args.build_dir.resolve()
    manifest = json.loads((build / 'manifest.json').read_text())
    assert manifest['enumeration_only']
    raw = KERNEL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == KSHA
    m = Machine(build / 'uvc_callback_bridge.elf', raw)
    assert m.prepare() == 0 and m.activate() == 0
    checks = []
    for interface in (0, 1):
        for which in (7, 8):
            for request in (bytes([0xa1, 0x81, 0, 1, interface, 0, 26, 0]), bytes([0x21, 1, 0, 2, interface, 0, 26, 0]), bytes([0xa1, 0x85, 0, 1, interface, 0, 2, 0])):
                m.cpu.mem_write(REQUEST, request)
                before = len(m.events)
                result = m.call(m.callback(interface, which), m.shadow(interface), REQUEST, 0x205000)
                assert result == 2 and len(m.events) == before
                assert bytes(m.cpu.mem_read(REQUEST, 8)) == request
                checks.append(dict(shadow=interface, callback=which, request=request.hex(), result=result))
    (build / 'control-rejection.json').write_text(json.dumps(dict(status='compiled_enumeration_controls_rejected', checks=checks, limitations=['Callback targets are explicit recorders; test verifies no dispatch or request mutation.', 'No physical host STALL, Windows driver behavior or teardown proof.']), indent=2) + '\n')
    print(f'{len(checks)} compiled control-rejection cases passed')


if __name__ == '__main__':
    main()
