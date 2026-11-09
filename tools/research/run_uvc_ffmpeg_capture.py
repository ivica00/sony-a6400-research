import os
import subprocess
import time
from pathlib import Path
from tools.camera_debugger import connect

ROOT = Path(__file__).resolve().parents[2]

def get_present_devices():
    cmd = 'powershell -Command "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like \'*054C*\' -or $_.Class -eq \'Camera\' -or $_.Class -eq \'Image\' } | Select-Object Status, Class, FriendlyName, InstanceId | ConvertTo-Json"'
    try:
        out = subprocess.check_output(cmd, shell=True).decode('utf-8', errors='replace').strip()
        import json
        data = json.loads(out)
        if isinstance(data, dict): data = [data]
        return data
    except Exception:
        return []

def main():
    print("=== Step 1: Pre-session Camera State ===")
    devs = get_present_devices()
    for d in devs:
        print(f"  [{d.get('Class')}] {d.get('FriendlyName')} ({d.get('InstanceId')})")

    ko_path = ROOT / "artifacts/native/uvc-composite-e0143-final/usbg_video_a6400.ko"
    feeder_path = ROOT / "artifacts/native/uvc-disjoint-source-e0143/uvc_stream_feeder_30fps"

    with open(ko_path, 'rb') as f: ko_data = f.read()
    with open(feeder_path, 'rb') as f: feeder_data = f.read()

    print(f"Loaded module ({len(ko_data)} bytes) and feeder ({len(feeder_data)} bytes)")

    print("\n=== Step 2: Deploying to /tmp_bt on Camera ===")
    with connect() as dbg:
        dbg.request(3, b'rm -f /tmp_bt/feeder.log /tmp_bt/stop_feeder')
        dbg.push('/tmp_bt/usbg_video_a6400.ko', ko_data)
        dbg.push('/tmp_bt/uvc_stream_feeder', feeder_data)
        dbg.request(3, b'chmod 755 /tmp_bt/uvc_stream_feeder')

        # Check if module is already loaded
        kmods, _ = dbg.read_all('/proc/modules')
        if 'usbg_video_a6400' not in kmods.decode('latin1'):
            print("  Inserting usbg_video_a6400.ko...")
            res = dbg.request(3, b'insmod /tmp_bt/usbg_video_a6400.ko')
            print("  insmod result:", res['status'])
            dbg.request(3, b'mknod /tmp_bt/video c 248 33 2>/dev/null; chmod 666 /tmp_bt/video')
        else:
            print("  Module already in memory.")

        print("\n=== Step 3: Launching 450-tick (15s) 30 FPS Feeder ===")
        dbg.request(3, b'/bin/sh -c "/tmp_bt/uvc_stream_feeder > /tmp_bt/feeder.log 2>&1 &"')
        print("  Feeder launched on camera.")

    # Wait for UVC device to enumerate on host
    print("\n=== Step 4: Waiting for UVC Device Enumeration on Host ===")
    start_t = time.time()
    detected = False
    for i in range(15):
        time.sleep(0.5)
        devs = get_present_devices()
        uvc_nodes = [d for d in devs if "0322" in d.get("InstanceId", "") or "Streaming" in d.get("FriendlyName", "")]
        if uvc_nodes:
            detected = True
            print(f"  [+] SONY UVC CAMERA DETECTED in {time.time()-start_t:.1f}s:")
            for n in uvc_nodes:
                print(f"      {n.get('FriendlyName')} | {n.get('Status')} | {n.get('InstanceId')}")
            break

    if detected:
        print("\n=== Step 5: Capturing 30 FPS UVC Stream via FFmpeg DirectShow ===")
        out_jpg = ROOT / "artifacts" / "uvc_live_sample_720p.jpg"
        os.makedirs(out_jpg.parent, exist_ok=True)
        # Capture 1 high-quality frame from USB Streaming Device
        cmd = [
            "ffmpeg", "-y",
            "-f", "dshow",
            "-video_size", "1280x720",
            "-i", "video=USB Streaming Device",
            "-vframes", "1",
            str(out_jpg)
        ]
        print(f"  Running: {' '.join(cmd)}")
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        print("  FFmpeg retcode:", res.returncode)
        if out_jpg.exists():
            print(f"  [PASS] Verified UVC capture saved to {out_jpg} ({out_jpg.stat().st_size} bytes)")
        else:
            print("  FFmpeg stdout/stderr:\n", res.stderr[-500:])

    print("\n=== Step 6: Waiting for Feeder to Complete & Restore Mass Storage ===")
    time.sleep(10)

    # Reconnect debugger to verify clean return
    try:
        with connect() as dbg:
            print("  [+] Debugger reconnected successfully in Mass Storage mode!")
            log, _ = dbg.read_all('/tmp_bt/feeder.log')
            print("  Feeder Log:")
            for line in log.decode('latin1', errors='replace').splitlines():
                if line.strip(): print("   ", line)
            dbg.request(3, b'rmmod usbg_video_a6400')
            print("  Module cleanly unloaded.")
    except Exception as e:
        print("  Post-session check error:", e)

if __name__ == '__main__':
    main()
