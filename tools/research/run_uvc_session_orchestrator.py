"""UVC Session Orchestrator for Sony a6400.
Handles deployment to /tmp_bt, module insertion, session trigger, and host detection.
"""

import subprocess
import time
import sys
import json
from pathlib import Path
import cv2

from tools.camera_debugger import connect

ROOT = Path(__file__).resolve().parents[2]

def get_present_devices():
    cmd = 'powershell -Command "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like \'*054C*\' -or $_.Class -eq \'Camera\' -or $_.Class -eq \'Image\' } | Select-Object Status, Class, FriendlyName, InstanceId | ConvertTo-Json"'
    out = subprocess.check_output(cmd, shell=True).decode('utf-8', errors='replace').strip()
    try:
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        return data
    except Exception:
        return []

def main():
    print("=== Step 1: Pre-session State ===")
    devs = get_present_devices()
    for d in devs:
        print(f"  [{d.get('Class')}] {d.get('FriendlyName')} ({d.get('InstanceId')})")

    print("\n=== Step 2: Deploying Module & Session Runner to /tmp_bt ===")
    ko_path = ROOT / "artifacts/native/uvc-composite-checked-e0139/usbg_video_a6400.ko"
    runner_path = ROOT / "tools/native_camera/uvc_hold_session_arm"

    with connect() as dbg:
        print("  Pushing usbg_video_a6400.ko (34 KB)...")
        r1 = dbg.push("/tmp_bt/usbg_video_a6400.ko", ko_path.read_bytes())
        print(f"    Pushed {r1['bytes']} bytes, verified={r1['readback_verified']}")

        print("  Pushing uvc_hold_session_arm...")
        r2 = dbg.push("/tmp_bt/uvc_hold_session_arm", runner_path.read_bytes())
        print(f"    Pushed {r2['bytes']} bytes, verified={r2['readback_verified']}")

        print("  Setting up module and permissions...")
        dbg.request(3, b'chmod +x /tmp_bt/uvc_hold_session_arm')
        dbg.request(3, b'insmod /tmp_bt/usbg_video_a6400.ko')
        dbg.request(3, b'mknod /tmp_bt/video c 248 33 2>/dev/null')
        ls_res = dbg.request(3, b'ls -la /tmp_bt')
        print(ls_res['payload'].decode(errors='replace'))

        print("\n=== Step 3: Triggering 60-second UVC Session ===")
        # Launch runner in background with output to /tmp_bt/uvc_session.log
        dbg.request(3, b'/bin/sh -c "/tmp_bt/uvc_hold_session_arm > /tmp_bt/uvc_session.log 2>&1 &"')
        print("  Runner launched on camera.")

    # Small delay for runner to execute IOCTL_UVC_INIT
    time.sleep(1.5)

    print("\n=== Step 4: Monitoring for UVC Camera Enumeration (60s window) ===")
    start_t = time.time()
    uvc_detected = False

    while time.time() - start_t < 65:
        elapsed = time.time() - start_t
        devs = get_present_devices()

        uvc_nodes = [d for d in devs if "0322" in d.get("InstanceId", "") or "Streaming" in d.get("FriendlyName", "")]
        if uvc_nodes and not uvc_detected:
            uvc_detected = True
            print(f"\n[+] [{elapsed:.1f}s] SONY UVC CAMERA DETECTED!")
            for n in uvc_nodes:
                print(f"    -> {n.get('FriendlyName')} | Class: {n.get('Class')} | Status: {n.get('Status')} | ID: {n.get('InstanceId')}")

            # Check OpenCV DirectShow cameras
            print("    Probing DirectShow cameras...")
            for i in range(4):
                cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
                if cap.isOpened():
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    print(f"    Index {i}: {w}x{h} @ {fps} FPS")
                    cap.release()
        elif not uvc_detected:
            time.sleep(1.0)
        else:
            time.sleep(2.0)

    print("\n=== Step 5: Post-Session Restoration Check ===")
    time.sleep(3.0)
    devs = get_present_devices()
    print("Present Sony devices after session:")
    for d in devs:
        print(f"  [{d.get('Class')}] {d.get('FriendlyName')} ({d.get('InstanceId')})")

    # Read log from camera
    try:
        with connect() as dbg:
            res = dbg.request(3, b'cat /tmp_bt/uvc_session.log; echo "---"; cat /proc/uptime')
            print("Session log & uptime:\n", res['payload'].decode(errors='replace'))
    except Exception as e:
        print("Note on post-session check:", e)

if __name__ == '__main__':
    main()
