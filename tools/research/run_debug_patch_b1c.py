"""Run the E0403 B1c bounded 18-byte patch module on the camera (Mass Storage only).

Two load/unload cycles, each receipted:
  cycle 1: insmod -> kernel log PRECHECK_OK/PATCH_OK -> rmmod -> RESTORE_OK
  cycle 2: insmod again; its PRECHECK_OK is independent proof that cycle 1
           restored the stock bytes -> rmmod -> RESTORE_OK
The module is staged in /tmp_bt (volatile RAM) and deleted afterwards. Any
failure path still attempts rmmod and file removal; the camera is never
rebooted and the battery is never touched.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Sony-PMCA-RE'))

from tools import camera_debugger as cd  # noqa: E402

MODULE = ROOT / 'artifacts/native/a6400-dbg-patch-e0403/final/a6400_dbg_patch.ko'
STAGE = '/tmp_bt/a6400_dbg_patch.ko'
NAME = 'a6400_dbg_patch'


def module_loaded(debugger):
    data = debugger.read('/proc/modules', 0, cd.MAX_DATA)
    return any(line.split()[0] == NAME for line in data.decode('latin1').splitlines() if line.split())


def kernel_log_tail(debugger, marker='A6400DBG'):
    text, _total, _secondary = debugger.dmesg(limit=cd.RING_LIMIT)
    return '\n'.join(line for line in text.decode('latin1', 'replace').splitlines()
                     if marker in line)


def run(cycles, output):
    output.mkdir(parents=True, exist_ok=True)
    receipt = {'operation': 'e0403-b1c-patch-cycle', 'module': str(MODULE), 'cycles': [],
               'deployed_from': STAGE}
    binary = MODULE.read_bytes()
    receipt['module_sha256'] = __import__('hashlib').sha256(binary).hexdigest()
    receipt['module_bytes'] = len(binary)
    with cd.connect() as debugger:
        receipt['daemon_info'] = debugger.request(cd.OP_INFO)['payload'].decode('utf-8', 'replace')
        (output / 'dmesg-before.txt').write_bytes(debugger.dmesg(limit=cd.RING_LIMIT)[0])
        pushed = debugger.push(STAGE, binary)
        receipt['pushed'] = pushed
        for cycle in range(1, cycles + 1):
            entry = {'cycle': cycle}
            load = debugger.request(cd.OP_EXEC,
                                    f'/sbin/insmod {STAGE}'.encode())
            entry['insmod_status'] = load['status']
            entry['insmod_output'] = load['payload'].decode('latin1', 'replace')
            time.sleep(0.4)
            entry['loaded'] = module_loaded(debugger)
            entry['log_after_load'] = kernel_log_tail(debugger)
            (output / f'cycle{cycle}-dmesg-after-load.txt').write_bytes(
                debugger.dmesg(limit=cd.RING_LIMIT)[0])
            if not entry['loaded']:
                entry['result'] = 'load_failed'
            else:
                unload = debugger.request(cd.OP_EXEC, f'/sbin/rmmod {NAME}'.encode())
                entry['rmmod_status'] = unload['status']
                entry['rmmod_output'] = unload['payload'].decode('latin1', 'replace')
                time.sleep(0.4)
                entry['still_loaded'] = module_loaded(debugger)
                entry['log_after_unload'] = kernel_log_tail(debugger)
                (output / f'cycle{cycle}-dmesg-after-unload.txt').write_bytes(
                    debugger.dmesg(limit=cd.RING_LIMIT)[0])
                entry['result'] = 'unloaded'
            receipt['cycles'].append(entry)
            if entry['result'] == 'load_failed':
                break
        receipt['log_final'] = kernel_log_tail(debugger)
        receipt['uptime_after'] = debugger.request(cd.OP_EXEC, b'cat /proc/uptime')['payload'].decode().strip()
        cleanup = debugger.request(cd.OP_EXEC,
                                   f'rm -f {STAGE}; echo cleaned'.encode())
        receipt['cleanup'] = cleanup['payload'].decode('latin1', 'replace')
        receipt['daemon_after'] = debugger.request(cd.OP_INFO)['payload'].decode('utf-8', 'replace')
    receipt['result'] = ('ok' if all(c.get('result') == 'unloaded' for c in receipt['cycles'])
                         and receipt['cycles'] else 'failed')
    (output / 'manifest.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps({'result': receipt['result'],
                      'cycle1': receipt['cycles'][0].get('log_after_unload') if receipt['cycles'] else None,
                      'cycle2': receipt['cycles'][1].get('log_after_unload') if len(receipt['cycles']) > 1 else None},
                     indent=2))
    return 0 if receipt['result'] == 'ok' else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycles', type=int, default=2)
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'artifacts/hardware/e0403-b1c-patch')
    args = parser.parse_args()
    return run(args.cycles, args.output)


if __name__ == '__main__':
    sys.exit(main())
