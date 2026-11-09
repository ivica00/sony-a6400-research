import time
import subprocess
import re
from pathlib import Path
from tools.camera_debugger import connect

ROOT = Path(__file__).resolve().parents[2]
ko_path = ROOT / "artifacts/native/uvc-composite-e0143-final/usbg_video_a6400.ko"
feeder_path = ROOT / "artifacts/native/uvc-disjoint-source-e0143/uvc_stream_feeder_5m"

print("=================================================================")
print("  SONY ILCE-6400 UVC CINEMAHUD LAUNCHER (720p @ 30 FPS)")
print("=================================================================")

with open(ko_path, 'rb') as f: ko_data = f.read()
with open(feeder_path, 'rb') as f: feeder_data = f.read()

print(f"\n[Step 1] Deploying UVC stack to Sony a6400 RAM (/tmp_bt)...")
print(f"  Module: {len(ko_data)} bytes | Feeder (5 min): {len(feeder_data)} bytes")

with connect() as dbg:
    dbg.request(3, b'rm -f /tmp_bt/feeder.log /tmp_bt/stop_feeder')
    dbg.push('/tmp_bt/usbg_video_a6400.ko', ko_data)
    dbg.push('/tmp_bt/uvc_stream_feeder', feeder_data)
    dbg.request(3, b'chmod 755 /tmp_bt/uvc_stream_feeder')

    kmods, _ = dbg.read_all('/proc/modules')
    if 'usbg_video' not in kmods.decode('latin1'):
        print("  Inserting kernel module usbg_video_a6400.ko...")
        res = dbg.request(3, b'insmod /tmp_bt/usbg_video_a6400.ko')
        print("  insmod status:", res['status'])
        dbg.request(3, b'mknod /tmp_bt/video c 248 33 2>/dev/null; chmod 666 /tmp_bt/video')

    print("  Starting 30 FPS UVC Feeder (5 minute streaming session)...")
    dbg.request(3, b'/bin/sh -c "/tmp_bt/uvc_stream_feeder > /tmp_bt/feeder.log 2>&1 &"')

print("\n[Step 2] Waiting for Sony UVC Gadget enumeration on host...")
found_idx = None
found_name = None

for attempt in range(12):
    time.sleep(0.5)
    cmd = ['ffmpeg', '-list_devices', 'true', '-f', 'dshow', '-i', 'dummy']
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='replace')
    devices = []
    for line in p.stderr.splitlines():
        m = re.search(r'"([^"]+)"\s+\(video\)', line)
        if m:
            devices.append(m.group(1))

    for idx, name in enumerate(devices):
        if 'usb streaming device' in name.lower() or 'sony' in name.lower():
            found_idx = idx
            found_name = name
            break

    if found_idx is not None:
        print(f"  [+] DETECTED SONY UVC! DirectShow index {found_idx}: '{found_name}' (after {(attempt+1)*0.5:.1f}s)")
        break

if found_idx is None:
    print("  [-] ERROR: Sony UVC gadget did not appear on DirectShow!")
    exit(1)

print("\n[Step 3] Launching CinemaHUD ptp_liveview_client.py server on port 8080...")
import subprocess
server_cmd = [
    'python', '-u', '-m', 'tools.research.ptp_liveview_client',
    '--source', 'uvc',
    '--camera-index', str(found_idx),
    '--serve',
    '--port', '8080',
    '--no-auto-deploy'
]

print(f"  Command: {' '.join(server_cmd)}")
proc = subprocess.Popen(server_cmd)

print("\n=================================================================")
print("  SONY A6400 UVC STREAM IS LIVE!")
print("  Open browser: http://127.0.0.1:8080/")
print("  Or run: launch_cinema_mpv.bat")
print("=================================================================\n")

# Wait 3s and verify server is responding
time.sleep(3)
import urllib.request, json
try:
    with urllib.request.urlopen('http://127.0.0.1:8080/api/status', timeout=3) as resp:
        status = json.loads(resp.read().decode())
        print("Verified Server Status:")
        print(json.dumps(status, indent=2))
except Exception as e:
    print("Server check note:", e)

print("\nServer is running in foreground. Press Ctrl+C to terminate.")
try:
    proc.wait()
except KeyboardInterrupt:
    proc.terminate()

