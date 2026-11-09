"""Monitor Sony a6400 UVC enumeration during a 25-second test session."""

import subprocess
import time
import sys
import cv2

from tools.camera_debugger import connect

def get_present_sony_devices():
    cmd = 'powershell -Command "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like \'*054C*\' } | Select-Object Status, Class, FriendlyName, InstanceId | ConvertTo-Json"'
    out = subprocess.check_output(cmd, shell=True).decode('utf-8', errors='replace').strip()
    return out

def test_cameras():
    cameras = []
    for i in range(4):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if cap.isOpened():
            w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            fps = cap.get(cv2.CAP_PROP_FPS)
            cameras.append((i, w, h, fps))
            cap.release()
    return cameras

def main():
    print("=== 1. Pre-session USB Status ===")
    print(get_present_sony_devices())
    print("Initial cameras found:", test_cameras())

    print("\n=== 2. Triggering 25-second UVC session on camera ===")
    try:
        with connect() as dbg:
            # Launch in background with 1-second delay so parent shell exits and returns SCSI response cleanly
            res = dbg.request(3, b'sh -c "sleep 1 && /tmp_bt/uvc_hold_session_arm > /tmp_bt/uvc_session.log 2>&1 &"')
            print("Trigger response:", res['payload'].decode(errors='replace'))
    except Exception as e:
        print("Note on trigger:", e)

    print("\n=== 3. Polling for UVC enumeration (25-second window) ===")
    start_time = time.time()
    detected_uvc = False

    while time.time() - start_time < 35:
        elapsed = time.time() - start_time
        devs = get_present_sony_devices()
        cams = test_cameras()

        is_uvc = ("0322" in devs) or any(c[0] > 0 for c in cams) or ("Streaming" in devs) or ("Camera" in devs and "054C" in devs)
        if is_uvc and not detected_uvc:
            detected_uvc = True
            print(f"\n[+] [{elapsed:.1f}s] UVC DEVICE DETECTED ON WINDOWS!")
            print(devs)
            print("Cameras:", cams)
        elif detected_uvc:
            print(f"[{elapsed:.1f}s] UVC session active. Cameras: {cams}")
        else:
            print(f"[{elapsed:.1f}s] Waiting for enumeration... Cameras: {cams}")

        time.sleep(1.0)

    print("\n=== 4. Post-session verification ===")
    print("Final present Sony devices:")
    print(get_present_sony_devices())
    print("Final cameras:", test_cameras())

if __name__ == '__main__':
    main()
