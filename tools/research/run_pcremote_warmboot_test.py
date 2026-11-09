"""Execute Phase 3 composite UVC + PTP enumeration test across PC Remote mode switch.

Detached Background Execution:
1. Uses pre-staged module and runner on /setting/
2. Insmods module and creates /tmp_bt/video node while in Mass Storage
3. Launches detached session runner with --wait-pcremote --timeout 300
4. Prompts user to switch to PC Remote in camera menu
5. Monitors host USB enumeration: UVC Camera device and PTP Still Image device
6. Captures concurrent PTP LiveView frames
7. Prompts user to return to Mass Storage
8. Collects receipts, cleans up /setting/ and verifies byte-equal baseline restoration
"""

import argparse
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


def check_host_devices():
    """Query Windows Pnp devices for Sony camera and imaging devices."""
    cmd = (
        'powershell -NoProfile -Command "Get-PnpDevice -PresentOnly | '
        'Where-Object { $_.InstanceId -like \'*054C*\' -or $_.Class -eq \'Camera\' -or $_.Class -eq \'Image\' -or $_.Class -eq \'WPD\' } | '
        'Select-Object Status, Class, FriendlyName, InstanceId | ConvertTo-Json"'
    )
    try:
        out = subprocess.check_output(cmd, shell=True).decode('utf-8', errors='replace').strip()
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        return data
    except Exception:
        return []


def test_ptp_liveview():
    """Attempt single frame capture via PTP over WPD if available."""
    try:
        from tools.research.ptp_liveview_client import SonyWpdPTPLiveView
        from pmca.usb.driver.windows.wpd import MtpContext
        with MtpContext() as ctx:
            devs = list(ctx.listDevices(0x54c))
            if not devs:
                return {'success': False, 'error': 'No Sony WPD camera discovered'}
            device_id = devs[0].handle
        cam = SonyWpdPTPLiveView(device_id)
        cam.connect()
        cam.start_liveview()
        frame = cam.get_frame(timeout_sec=3.0)
        cam.close()
        if frame and len(frame) > 1000:
            return {'success': True, 'frame_bytes': len(frame)}
        return {'success': False, 'error': 'Empty frame'}
    except Exception as exc:
        return {'success': False, 'error': repr(exc)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', required=True, type=Path)
    p.add_argument('--module-build', type=Path, default=ROOT / 'artifacts/native/uvc-ptp-module-e0206')
    p.add_argument('--module-audit', type=Path, default=ROOT / 'artifacts/analysis/uvc-ptp-module-e0206')
    p.add_argument('--runner-build', type=Path, default=ROOT / 'artifacts/native/uvc-ptp-runner-e0206')
    p.add_argument('--duration', type=int, default=30, help='Session duration in seconds')
    args = p.parse_args()

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

    # Validate audit
    audit_data = json.loads((args.module_audit.resolve() / 'manifest.json').read_text())
    if audit_data['status'] != 'offline_module_audit_passed' or audit_data['module_sha256'] != mod_sha:
        raise ValueError('Module audit mismatch')

    setting_mod = '/setting/usbg_video.ko'
    setting_runner = '/setting/uvc_runner.elf'
    setting_session_log = '/setting/uvc_session.log'

    report = dict(
        status='started',
        captured_utc=datetime.now(timezone.utc).isoformat(),
        module_sha256=mod_sha,
        module_path=setting_mod,
        runner_sha256=run_sha,
        runner_path=setting_runner,
        duration_sec=args.duration,
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

    before_mods = None

    try:
        with connect() as dbg:
            artifact('debugger-before.txt', dbg.request(1)['payload'])
            before_mods, _ = dbg.read_all('/proc/modules', 65536)
            artifact('modules-before.txt', before_mods)
            if any(l.startswith(b'usbg_video ') for l in before_mods.splitlines()):
                print('[*] usbg_video already loaded; unloading first...')
                dbg.request(3, b'rmmod usbg_video')
                before_mods, _ = dbg.read_all('/proc/modules', 65536)

            # Check PID 149 status
            status_before, _ = dbg.read_all('/proc/149/status', 16384)
            artifact('status-before.txt', status_before)
            if not re.search(rb'^TracerPid:\s+0$', status_before, re.M):
                raise RuntimeError('Owner process already traced')

            # Stage module and runner to /setting if missing or mismatched
            print('[*] Staging module and runner to /setting...')
            dbg.push('/tmp_bt/stage_mod.ko', module_bytes)
            dbg.push('/tmp_bt/stage_runner.elf', runner_bytes)
            command(dbg, f'cp /tmp_bt/stage_mod.ko {setting_mod}', 'stage-mod')
            command(dbg, f'cp /tmp_bt/stage_runner.elf {setting_runner}', 'stage-runner')
            command(dbg, f'chmod 755 {setting_runner}', 'chmod-runner')
            command(dbg, 'rm -f /tmp_bt/stage_mod.ko /tmp_bt/stage_runner.elf', 'clean-stage-tmp')

            # Clean previous session log
            command(dbg, f'rm -f {setting_session_log}', 'clean-session-log')

            # Insmod module and create character device node in /tmp_bt
            print('[*] Loading usbg_video module and creating /tmp_bt/video node...')
            command(dbg, f'insmod {setting_mod}', 'insmod')
            command(dbg, 'mknod /tmp_bt/video c 248 33', 'mknod')

            # Launch detached session runner
            print('[*] Launching detached session runner with --wait-pcremote --timeout 300...')
            run_cmd = (
                f'sh -c "{setting_runner} --duration {args.duration} --wait-pcremote --timeout 300 --device /tmp_bt/video </dev/null >{setting_session_log} 2>&1" </dev/null >/dev/null 2>&1 &'
            )
            command(dbg, run_cmd, 'launch-detached-runner')
            report['runner_launched'] = True
            save()

        # Step 2: Prompt user to switch to PC Remote and monitor host USB enumeration
        print("\n" + "=" * 70)
        print(">>> MODUL I RUNNER SU AKTIVNI NA KAMERI I CEKAJU PC REMOTE! <<<")
        print(">>> SADA PREBACITE KAMERU U IZBORNIKU NA 'PC Remote':")
        print(">>>   MENU -> Setup (zuti kofer) -> USB Connection -> PC Remote")
        print("=" * 70 + "\n")

        print(f"[*] Cekam prelazak na PC Remote i nadzirem USB sabirnicu (do 300s za prebacivanje, zatim {args.duration}s sesije)...")
        start_time = time.time()
        uvc_detected = False
        ptp_detected = False
        pcremote_switched = False
        ptp_liveview_verified = False
        host_samples = []

        max_wait = 300 + args.duration + 10
        session_active_time = None

        while time.time() - start_time < max_wait:
            elapsed = time.time() - start_time
            devs = check_host_devices()
            uvc_nodes = [d for d in devs if '0322' in d.get('InstanceId', '') or 'Streaming' in d.get('FriendlyName', '') or d.get('Class') == 'Camera']
            ptp_nodes = [d for d in devs if '0CAA' in d.get('InstanceId', '') or d.get('Class') == 'WPD']

            if ptp_nodes and not pcremote_switched:
                pcremote_switched = True
                print(f"[+] [{elapsed:.1f}s] DETEKTIRAN PC REMOTE NACIN NA HOSTU ({ptp_nodes[0].get('InstanceId', '')})!")

            sample = {
                'elapsed_sec': round(elapsed, 2),
                'pcremote_active': pcremote_switched,
                'uvc_count': len(uvc_nodes),
                'ptp_count': len(ptp_nodes),
                'uvc_devices': uvc_nodes,
                'ptp_devices': ptp_nodes
            }

            if uvc_nodes and not uvc_detected:
                uvc_detected = True
                print(f"[***] [{elapsed:.1f}s] UVC KAMERA DETEKTIRANA NA HOSTU! [***]: {uvc_nodes}")

            if pcremote_switched and not ptp_liveview_verified and (uvc_detected or (session_active_time and time.time() - session_active_time > 5)):
                print(f"[*] [{elapsed:.1f}s] Provjeravam istodobnu PTP LiveView komunikaciju...")
                ptp_res = test_ptp_liveview()
                sample['ptp_liveview_test'] = ptp_res
                if ptp_res.get('success'):
                    ptp_liveview_verified = True
                    print(f"[***] [{elapsed:.1f}s] PTP LIVEVIEW KADAR USPJESNO ZABILJEZEN ({ptp_res['frame_bytes']} B)! [***]")
                else:
                    print(f"[-] [{elapsed:.1f}s] PTP LiveView test: {ptp_res}")

            host_samples.append(sample)

            if pcremote_switched and session_active_time is None:
                session_active_time = time.time()

            if session_active_time and (time.time() - session_active_time > args.duration + 10):
                print(f"[*] Predvidjeno trajanje sesije ({args.duration}s) je isteklo. Zavrsavam nadzor.")
                break

            time.sleep(1.0)

        report['host_monitoring_samples'] = host_samples
        report['pcremote_switched_detected'] = pcremote_switched
        report['uvc_detected_on_host'] = uvc_detected
        report['ptp_liveview_verified'] = ptp_liveview_verified
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
        # Step 3: Wait for Mass Storage reconnection and perform cleanup
        print("[*] Cekam ponovno spajanje u Mass Storage nacinu radi ocitanja logova i ciscenja...")
        msc_reconnected = False
        wait_msc_start = time.time()
        while time.time() - wait_msc_start < 300:
            try:
                with connect() as dbg:
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
                with connect() as dbg:
                    # Read session log
                    log_raw, _ = dbg.read_all(setting_session_log, 256 * 1024)
                    artifact('session.log', log_raw)

                    # Check status
                    status_after, _ = dbg.read_all('/proc/149/status', 16384)
                    artifact('status-after.txt', status_after)

                    # Collect dmesg
                    dmesg_path = '/tmp_bt/post_session.klog'
                    dbg.request(3, f'dmesg > {shlex.quote(dmesg_path)}'.encode())
                    klog, _ = dbg.read_all(dmesg_path, 2 * 1024 * 1024)
                    artifact('kernel-log-after-session.txt', klog)
                    dbg.request(3, f'rm -f {shlex.quote(dmesg_path)}'.encode())

                    # rmmod if still loaded
                    cur_mods, _ = dbg.read_all('/proc/modules', 65536)
                    if any(l.startswith(b'usbg_video ') for l in cur_mods.splitlines()):
                        command(dbg, 'rmmod usbg_video', 'rmmod')

                    # Remove staged files from /setting and /tmp_bt
                    command(dbg, f'rm -f {setting_mod} {setting_runner} {setting_session_log} /tmp_bt/video', 'cleanup-files')

                    # Verify modules restored
                    after_mods, _ = dbg.read_all('/proc/modules', 65536)
                    artifact('modules-after.txt', after_mods)
                    report['module_list_restored'] = (before_mods is not None and after_mods == before_mods)
                    artifact('debugger-after.txt', dbg.request(1)['payload'])
                    report['status'] = 'phase3_session_completed' if 'error' not in report and report['module_list_restored'] else 'failed'
                    save()
            except Exception as cleanup_err:
                report['cleanup_error'] = repr(cleanup_err)
                save()

    print(json.dumps({k: v for k, v in report.items() if k != 'files'}, indent=2))


if __name__ == '__main__':
    main()
