"""Execute Phase 3 composite UVC + PTP enumeration test on Sony a6400.

Preconditions:
1. Camera initially in Mass Storage for RAM staging; switch to PC Remote only after launch.
2. Module candidate E0206 and session runner E0206 built and audited.
3. Camera writes strictly confined to RAM /tmp_bt.
"""

import argparse
import gc
from contextlib import ExitStack, nullcontext
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import time

from tools.camera_debugger import connect
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT
from tools.research.capture_sony_usb_hub import capture as capture_hub
from tools.research.uvc_ptp_windows_host import query_devices, classify, setupapi_sony


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_host_devices():
    """Only exact Sony identity; query failure must remain distinguishable."""
    return query_devices()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', required=True, type=Path)
    p.add_argument('--module-build', type=Path, default=ROOT / 'artifacts/native/uvc-ptp-module-e0206')
    p.add_argument('--module-audit', type=Path, default=ROOT / 'artifacts/analysis/uvc-ptp-module-e0206')
    p.add_argument('--runner-build', type=Path, default=ROOT / 'artifacts/native/uvc-ptp-runner-e0208')
    p.add_argument('--duration', type=int, default=90, help='Session duration in seconds (default 90 for Windows binding)')
    args = p.parse_args()
    if not 1<=args.duration<=300:p.error('Duration must be 1..300 seconds')

    out = args.output_dir.resolve()
    if not out.is_relative_to(ROOT / 'artifacts'):
        p.error('Output must be under artifacts')
    out.mkdir(parents=True, exist_ok=False)

    module_file = args.module_build.resolve() / 'usbg_video_a6400_shared_candidate.ko'
    runner_file = args.runner_build.resolve() / 'uvc_ptp_session_runner.elf'
    module_bytes = module_file.read_bytes()
    runner_bytes = runner_file.read_bytes()
    mod_sha = hashlib.sha256(module_bytes).hexdigest()
    run_sha = hashlib.sha256(runner_bytes).hexdigest()
    runner_manifest=json.loads((args.runner_build.resolve()/'manifest.json').read_text())
    runner_records=[r for path,r in runner_manifest['files'].items() if Path(path).name==runner_file.name]
    if len(runner_records)!=1 or runner_records[0]['sha256']!=run_sha or runner_records[0]['bytes']!=len(runner_bytes):
        raise ValueError('Runner build identity mismatch')

    # Validate audit
    audit_data = json.loads((args.module_audit.resolve() / 'manifest.json').read_text())
    if audit_data['status'] != 'offline_module_audit_passed' or audit_data['module_sha256'] != mod_sha:
        raise ValueError('Module audit mismatch')

    prefix = f'/tmp_bt/uvc_ptp_enum_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")}'
    remote_mod = prefix + '.ko'
    remote_runner = prefix + '_runner.elf'
    remote_node = prefix + '_video'
    remote_log = prefix + '.log'
    remote_receipt = prefix + '.receipt'

    report = dict(
        status='started',
        captured_utc=datetime.now(timezone.utc).isoformat(),
        module_sha256=mod_sha,
        module_path=remote_mod,
        runner_sha256=run_sha,
        runner_path=remote_runner,
        device_node=remote_node,
        session_log=remote_log,
        session_receipt=remote_receipt,
        duration_sec=args.duration,
        camera_writes='/tmp_bt only',
        files={}
    )

    def save():
        (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')

    def artifact(name, raw):
        (out / name).write_bytes(raw)
        report['files'][name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())

    def command(dbg, cmd_str, name):
        res = dbg.request(3, cmd_str.encode())
        artifact(name + '.txt', res['payload'])
        report[name] = dict(status=res['status'], flags=res['flags'])
        save()
        if res['status'] or res['flags']:
            raise RuntimeError(f'{name} failed: {cmd_str}')

    save()
    devices_before = check_host_devices()
    report['host_devices_before'] = devices_before
    save()

    loaded = False
    node_created = False
    runner_pushed = False
    before_mods = None

    try:
        with connect() as dbg:
            artifact('debugger-before.txt', dbg.request(1)['payload'])
            before_mods, _ = dbg.read_all('/proc/modules', 65536)
            artifact('modules-before.txt', before_mods)
            if any(l.startswith(b'usbg_video ') for l in before_mods.splitlines()):
                raise RuntimeError('Module already loaded')

            # Check PID 149 status
            status_before, _ = dbg.read_all('/proc/149/status', 16384)
            artifact('status-before.txt', status_before)
            if not re.search(rb'^TracerPid:\s+0$', status_before, re.M):
                raise RuntimeError('Owner process already traced')

            # Upload module
            report['upload_module'] = dbg.push(remote_mod, module_bytes)
            save()

            # Upload runner
            report['upload_runner'] = dbg.push(remote_runner, runner_bytes)
            runner_pushed = True
            command(dbg, f'chmod 700 {shlex.quote(remote_runner)}', 'chmod-runner')

            # insmod
            command(dbg, f'insmod {shlex.quote(remote_mod)}', 'insmod')
            loaded = True
            loaded_mods, _ = dbg.read_all('/proc/modules', 65536)
            artifact('modules-loaded.txt', loaded_mods)
            if not any(l.startswith(b'usbg_video ') for l in loaded_mods.splitlines()):
                raise RuntimeError('Loaded module not visible in /proc/modules')

            # Create video character node
            command(dbg, f'mknod {shlex.quote(remote_node)} c 248 33', 'mknod')
            node_created = True

            # Launch session runner asynchronously with --wait-pcremote
            run_cmd = f'{shlex.quote(remote_runner)} --duration {args.duration} --wait-pcremote --timeout 300 --device {shlex.quote(remote_node)} --receipt {shlex.quote(remote_receipt)} > {shlex.quote(remote_log)} 2>&1 &'
            command(dbg, run_cmd, 'launch-session-runner')
            report['session_launched'] = True
            save()
            ready=False
            for _ in range(15):
                time.sleep(0.2)
                ready_log,short=dbg.read_all(remote_log,8192)
                if b'STEP 0: Waiting for camera to enter PC Remote mode' in ready_log:
                    ready=True;artifact('runner-ready.log',ready_log);break
                if b'FAIL ' in ready_log:
                    artifact('runner-start-failed.log',ready_log);break
            if not ready:raise RuntimeError('Runner did not confirm open device and PC Remote wait; do not switch camera')
            report['runner_ready_before_switch']=True;save()

        # Drop the staging device reference before a USB disconnect/reconnect.
        del dbg
        gc.collect()

        # Step 2: Prompt user to switch to PC Remote and monitor host USB enumeration
        print("\n" + "=" * 70)
        print(">>> MODUL I RUNNER SU USPJESNO POSTAVLJENI NA KAMERU! <<<")
        print(">>> SADA PREBACITE KAMERU U IZBORNIKU NA 'PC Remote':")
        print(">>>   MENU -> Setup (zuti kofer) -> USB Connection -> PC Remote")
        print("=" * 70 + "\n")

        print(f"[*] Cekam prelazak na PC Remote i nadzirem USB sabirnicu (do 300s za prebacivanje, zatim {args.duration}s sesije)...")
        start_time = time.time()
        uvc_detected = False
        ptp_detected = False
        pcremote_switched = False
        host_samples = []
        captured_composite_hub = False

        # Monitor for up to 300s wait + duration + 10s grace
        max_wait = 300 + args.duration + 30
        session_active_time = None

        while time.time() - start_time < max_wait:
            elapsed = time.time() - start_time
            try:
                devs = check_host_devices();binding=classify(devs)
            except Exception as query_error:
                host_samples.append(dict(elapsed_sec=round(elapsed,2),query_error=repr(query_error)))
                time.sleep(1);continue
            uvc_nodes = binding['uvc_children']
            ptp_nodes = binding['ptp_children']

            if devs and not pcremote_switched:
                pcremote_switched = True
                print(f"[+] [{elapsed:.1f}s] DETEKTIRAN PC REMOTE NACIN NA HOSTU ({devs[0].get('InstanceId', '')})!")

            sample = {
                'elapsed_sec': round(elapsed, 2),
                'pcremote_active': pcremote_switched,
                'uvc_count': len(uvc_nodes),
                'ptp_count': len(ptp_nodes),
                'uvc_devices': uvc_nodes,
                'ptp_devices': ptp_nodes
            }
            sample['binding']=binding
            if any(str(d.get('Service','')).lower()=='usbccgp' for d in binding['parents']) and not captured_composite_hub:
                try:
                    hub=capture_hub();artifact('composite-hub-descriptors.json',json.dumps(hub,indent=2).encode('utf-8'))
                    captured_composite_hub=True
                except Exception as hub_error:sample['hub_capture_error']=repr(hub_error)
            host_samples.append(sample)

            if binding['uvc_ready'] and not uvc_detected:
                uvc_detected = True
                print(f"[***] [{elapsed:.1f}s] UVC KAMERA DETEKTIRANA NA HOSTU! [***]: {uvc_nodes}")

            if binding['parents'] and session_active_time is None:
                session_active_time = time.time()

            if session_active_time and (time.time() - session_active_time > args.duration + 30):
                print(f"[*] Predvidjeno trajanje sesije ({args.duration}s) je isteklo. Zavrsavam nadzor.")
                break

            time.sleep(1.0)

        report['host_monitoring_samples'] = host_samples
        report['pcremote_switched_detected'] = pcremote_switched
        report['uvc_detected_on_host'] = uvc_detected
        report['children_ready_together']=any(s.get('binding',{}).get('children_ready_simultaneously',False) for s in host_samples)
        try:
            metadata,setup_text=setupapi_sony();artifact('setupapi-sony.txt',setup_text.encode('utf-8'));report['setupapi']=metadata
        except OSError as setup_error:report['setupapi_error']=repr(setup_error)
        save()

        print("\n" + "=" * 70)
        print(">>> SESIJA JE ZAVRSENA NA KAMERI! <<<")
        print(">>> SADA VRATITE KAMERU U 'Mass Storage' NACIN RADA:")
        print(">>>   MENU -> Setup (zuti kofer) -> USB Connection -> Mass Storage")
        print("=" * 70 + "\n")

    except Exception as exc:
        report['error'] = repr(exc)
        save()

    finally:
        if 'dbg' in locals():
            del dbg
            gc.collect()
        # Step 3: Wait for Mass Storage reconnection and perform cleanup
        print("[*] Cekam ponovno spajanje u Mass Storage nacinu radi ocitanja logova i ciscenja...")
        msc_reconnected = False
        reconnection=ExitStack()
        wait_msc_start = time.time()
        while time.time() - wait_msc_start < 120:
            try:
                dbg=reconnection.enter_context(connect())
                msc_reconnected = True
                break
            except Exception:
                time.sleep(1.5)

        if not msc_reconnected:
            print("[-] Isteklo vrijeme cekanja za Mass Storage reconnect!")
            report['cleanup_error'] = 'Timeout waiting for camera to return to Mass Storage'
            save()
        else:
            print("[+] Ponovno povezan na debugger u Mass Storage nacinu! Preuzimam dokaze...")
            try:
                with nullcontext(dbg) as dbg:
                    # Read session log
                    try:
                        log_raw, truncated = dbg.read_all(remote_receipt,256*1024)
                        report['collected_log_path']=remote_receipt
                    except Exception as receipt_error:
                        report['receipt_read_error']=repr(receipt_error)
                        log_raw, truncated=dbg.read_all(remote_log,256*1024)
                        report['collected_log_path']=remote_log
                    if truncated:raise RuntimeError('Truncated session receipt')
                    artifact('session.log', log_raw)
                    report['runner_completed']=b'SESSION_RUNNER complete result=0' in log_raw and b'Entry hook retired' in log_raw and b'IOCTL_UVC_INIT returned ret=0' in log_raw
                    if not report['runner_completed']:raise RuntimeError('Runner completion/retirement not confirmed; preserving module for recovery')

                    # Check status
                    status_after, status_short = dbg.read_all('/proc/149/status', 16384)
                    artifact('status-after.txt', status_after)
                    if status_short or not re.search(rb'^TracerPid:\s+0$',status_after,re.M):raise RuntimeError('Tracer state not clean; no unload attempted')

                    # Collect dmesg
                    dmesg_path = prefix + '.klog'
                    dbg.request(3, f'dmesg > {shlex.quote(dmesg_path)}'.encode())
                    klog, _ = dbg.read_all(dmesg_path, 2 * 1024 * 1024)
                    artifact('kernel-log-after-session.txt', klog)
                    dbg.request(3, f'rm -f {shlex.quote(dmesg_path)}'.encode())

                    # Wait for runner to terminate if still running
                    time.sleep(2.0)

                    # rmmod
                    cur_mods, _ = dbg.read_all('/proc/modules', 65536)
                    if any(l.startswith(b'usbg_video ') for l in cur_mods.splitlines()):
                        command(dbg, 'rmmod usbg_video', 'rmmod')
                        loaded = False

                    # Remove temporary files
                    if node_created:
                        command(dbg, f'rm -f {shlex.quote(remote_node)}', 'remove-node')
                    if runner_pushed:
                        command(dbg, f'rm -f {shlex.quote(remote_runner)}', 'remove-runner-file')
                    command(dbg, f'rm -f {shlex.quote(remote_mod)}', 'remove-module-file')
                    command(dbg, f'rm -f {shlex.quote(remote_log)}', 'remove-log-file')
                    command(dbg, f'rm -f {shlex.quote(remote_receipt)}', 'remove-receipt-file')

                    # Verify modules restored
                    after_mods, _ = dbg.read_all('/proc/modules', 65536)
                    artifact('modules-after.txt', after_mods)
                    report['module_list_restored'] = (before_mods is not None and after_mods == before_mods)
                    artifact('debugger-after.txt', dbg.request(1)['payload'])
                    report['status'] = 'phase3_session_completed' if 'error' not in report and report['module_list_restored'] and report.get('runner_completed') else 'failed'
                    save()
            except Exception as cleanup_err:
                report['cleanup_error'] = repr(cleanup_err)
                save()
            finally:
                reconnection.close()

    print(json.dumps({k: v for k, v in report.items() if k != 'files'}, indent=2))


if __name__ == '__main__':
    main()
