"""Read verified current LIRO gyro-path code and RAM; no firmware calls or writes."""
import hashlib
import json
from pathlib import Path
import time
from tools.camera_debugger import connect


def main():
    root = Path(__file__).resolve().parents[2]
    image = root / 'artifacts/hardware/av-cam-camera-original.bin'
    blob = image.read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    if digest != 'dd8f8d0cc74ad4b70100e5728cf8b159b5155e7fb50eaf1147b99c9054740209':
        raise ValueError('This probe is scoped to the analyzed current image')
    base, alias = 0x635c6000, 0x60000000
    ranges = [('initialization_and_guarded_lifecycle', 0x63a7013c, 0x1a8),
              ('raw_getters_guard_and_init', 0x63a70574, 0x2ac),
              ('backup_config_descriptor', 0x6457963c, 0x3c)]
    result = dict(image_sha256=digest, cpu_freeze=False, writes=False, code=[], samples=[])
    with connect() as debugger:
        for name, address, size in ranges:
            live = debugger.read('/dev/mem', address - alias, size)
            expected = blob[address - base:address - base + size]
            if len(live) != size or live != expected:
                raise ValueError('Live code/descriptor differs: ' + name)
            result['code'].append(dict(name=name, address=hex(address), size=size,
                                       source_equal=True, data=live.hex()))
        for _ in range(3):
            before = time.time_ns()
            raw = debugger.read('/dev/mem', 0x043bc30c, 0xd0)
            if len(raw) != 0xd0:
                raise ValueError('Short state read')
            result['samples'].append(dict(host_before_ns=before, host_after_ns=time.time_ns(),
                                           address='0x643bc30c', data=raw.hex(),
                                           guard=raw[0xc6],
                                           raw_buffer=raw[0x90:0x98].hex(),
                                           gyro_axis_matrix=list(raw[0xbd:0xc6])))
            time.sleep(0.2)
    destination = root / 'artifacts/hardware/gyro-verified-state-survey.json'
    destination.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('Verified original code/descriptor and captured three non-atomic states')
    print('Enable guard values:', [sample['guard'] for sample in result['samples']])


if __name__ == '__main__':
    main()
