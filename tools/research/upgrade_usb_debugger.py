"""Staged, reversible upgrade of the native USB debugger over USB (E0401).

Sequence, each step receipted:
 1. connect to the running protocol-v1 daemon and preserve the installed binary;
 2. push the new daemon to /tmp_bt (RAM) with read-back verification;
 3. start it; it retries the feature registration/lock until the old instance exits;
 4. confirm the new process is alive before stopping the old one (no debugger loss);
 5. send the old daemon's stop operation, wait for the new protocol;
 6. optionally overwrite /setting/a6400_usb_debugd.elf for boot persistence and
    read it back.

The tool never enters service/updater mode and never writes outside /tmp_bt or
the single /setting daemon path (only with --install-setting).
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Sony-PMCA-RE'))

from tools import camera_debugger as cd  # noqa: E402

DEFAULT_BINARY = ROOT / 'artifacts/native/usb-debugger-e0401/a6400_usb_debugd.elf'
STAGE_PATH = '/tmp_bt/a6400_usb_debugd_v2.elf'
SETTING_PATH = '/setting/a6400_usb_debugd.elf'


def identify_daemons(debugger):
    processes = debugger.request(cd.OP_PS)['payload'].decode('latin1').splitlines()
    found = []
    for line in processes:
        parts = line.split()
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        pid, comm = int(parts[0]), parts[1]
        if not comm.startswith('a6400_usb'):
            continue
        try:
            cmdline = debugger.read(f'/proc/{pid}/cmdline', 0, 512).rstrip(b'\0')
        except Exception:
            cmdline = b''
        found.append({'pid': pid, 'comm': comm, 'cmdline': cmdline.decode('latin1')})
    return found


def wait_for_protocol2(timeout=15):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            with cd.connect() as debugger:
                info = debugger.request(cd.OP_INFO)['payload'].decode('utf-8', 'replace')
            if 'protocol=2' in info:
                return info
            last = 'old protocol still answering'
        except Exception as exc:
            last = f'{type(exc).__name__}: {exc}'
        time.sleep(0.5)
    raise RuntimeError(f'new debugger did not register: {last}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=DEFAULT_BINARY)
    parser.add_argument('--install-setting', action='store_true',
                        help='Overwrite /setting/a6400_usb_debugd.elf for boot persistence')
    parser.add_argument('--install-only', action='store_true',
                        help='Only install the binary at /setting (no staged restart)')
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'artifacts/hardware/e0401-debugger-upgrade')
    args = parser.parse_args()
    binary = args.binary.read_bytes()
    if not binary.startswith(b'\x7fELF') or len(binary) > 1024 * 1024:
        raise SystemExit('Expected an ELF debugger binary under 1 MiB')
    binary_sha = hashlib.sha256(binary).hexdigest()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'daemon-v2.elf').write_bytes(binary)
    receipt = {'operation': 'usb-debugger-staged-upgrade', 'binary_sha256': binary_sha,
               'binary_bytes': len(binary), 'steps': []}

    def step(name, **values):
        entry = {'step': name, **values}
        receipt['steps'].append(entry)
        print(f'[{name}] ' + json.dumps(values, sort_keys=True))
        return entry

    if args.install_only:
        with cd.connect() as debugger:
            before_info = debugger.request(cd.OP_INFO)['payload'].decode('utf-8', 'replace')
            step('connected', info=before_info.strip().splitlines()[:2])
            preserved = b''
            offset = 0
            while True:
                chunk = debugger.read('/setting/a6400_usb_debugd.elf', offset, cd.MAX_DATA)
                if not chunk:
                    break
                preserved += chunk
                offset += len(chunk)
            (args.output / 'setting-a6400_usb_debugd.elf.before').write_bytes(preserved)
            step('preserved_installed', bytes=len(preserved),
                 sha256=hashlib.sha256(preserved).hexdigest())
            result = debugger.push(SETTING_PATH, binary)
            step('installed_setting_binary', path=SETTING_PATH, **result)
            readback = b''
            offset = 0
            while True:
                chunk = debugger.read(SETTING_PATH, offset, cd.MAX_DATA)
                if not chunk:
                    break
                readback += chunk
                offset += len(chunk)
            step('setting_readback', bytes=len(readback),
                 sha256=hashlib.sha256(readback).hexdigest(),
                 matches_source=readback == binary)
            if readback != binary:
                raise SystemExit('Installed binary read-back mismatch')
        receipt['result'] = 'installed'
        (args.output / 'install-manifest.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print(f'installed to {SETTING_PATH}; receipt: {args.output / "install-manifest.json"}')
        return 0

    with cd.connect() as debugger:
        before = debugger.request(cd.OP_INFO)['payload'].decode('utf-8', 'replace')
        step('connected_v1', info=before.strip().splitlines()[:2])
        installed = debugger.read('/setting/a6400_usb_debugd.elf', 0, cd.MAX_DATA)
        chunks = bytearray(installed)
        offset = len(chunks)
        while True:
            chunk = debugger.read('/setting/a6400_usb_debugd.elf', offset, cd.MAX_DATA)
            if not chunk:
                break
            chunks.extend(chunk)
            offset += len(chunk)
        (args.output / 'setting-a6400_usb_debugd.elf.before').write_bytes(bytes(chunks))
        step('preserved_installed', bytes=len(chunks),
             sha256=hashlib.sha256(bytes(chunks)).hexdigest())
        result = debugger.push(STAGE_PATH, binary)
        step('pushed_stage_binary', path=STAGE_PATH, **result)
        launch = debugger.request(cd.OP_EXEC, b'chmod 755 ' + STAGE_PATH.encode()
                                  + b'; ' + STAGE_PATH.encode() + b' >/dev/null 2>&1 & echo $!')
        pid_text = launch['payload'].decode('latin1').strip()
        if launch['status'] or not pid_text.isdigit():
            step('staged_launch_failed', status=launch['status'], output=pid_text)
            raise SystemExit('Could not start the staged daemon; old daemon left running')
        staged_pid = int(pid_text)
        step('started_stage_binary', path=STAGE_PATH, pid=staged_pid)
        cmdline = b''
        for _ in range(20):
            time.sleep(0.25)
            try:
                cmdline = debugger.read(f'/proc/{staged_pid}/cmdline', 0, 512).rstrip(b'\0')
            except Exception:
                cmdline = b''
            if b'v2' in cmdline:
                break
        if b'v2' not in cmdline:
            step('staged_process_missing', pid=staged_pid, cmdline=cmdline.decode('latin1'))
            raise SystemExit('Staged daemon is not alive; old daemon left running')
        step('staged_process_visible', pid=staged_pid, cmdline=cmdline.decode('latin1'))
        log_bytes, _ = debugger.read_all('/setting/a6400_usb_debugd.log', 1 << 20)
        log_last = log_bytes[-2048:]
        if b'registration retry' not in log_last:
            step('staged_retry_not_observed', log_bytes=len(log_bytes))
        else:
            step('staged_retry_observed', log_bytes=len(log_bytes))
        stop = debugger.request(cd.OP_STOP)
        step('stopped_v1', status=stop['status'])

    info = wait_for_protocol2()
    receipt['new_info'] = info
    receipt['steps'].append({'step': 'protocol2_registered', 'info': info.splitlines()[:3]})
    print('[protocol2_registered]')

    with cd.connect() as debugger:
        state = debugger.usb_state()
        ring_info = debugger.ring_info()
        (args.output / 'usb-state.txt').write_text(state, encoding='utf-8')
        (args.output / 'ring-info.txt').write_text(ring_info, encoding='utf-8')
        receipt['usb_state'] = state
        receipt['ring_info'] = ring_info
        receipt['steps'].append({'step': 'v2_ops_verified',
                                 'usb_state_lines': len(state.splitlines()),
                                 'ring_info_lines': len(ring_info.splitlines())})
        print('[v2_ops_verified]')
        if args.install_setting:
            result = debugger.push(SETTING_PATH, binary)
            step('installed_setting_binary', path=SETTING_PATH, **result)
            after = debugger.read('/setting/a6400_usb_debugd.elf', 0, 64)
            receipt['setting_readback_prefix'] = after.hex()
    receipt['result'] = 'upgraded'
    (args.output / 'manifest.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(f'upgraded to protocol 2; receipt: {args.output / "manifest.json"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
