"""Sony PTP Live View Client and Cinema Monitor with AMD FSR for a6400 (PC Remote mode).

Connects over USB in "PC Remote" mode via Windows WPD.
Streams live frames and runs a local HTTP MJPEG / WebGL2 server at http://127.0.0.1:8080/
Includes authentic AMD FidelityFX Super Resolution (EASU + RCAS) real-time upscaling,
A/B Split-Screen comparison, Flip V/H controls, focus peaking, and cinema telemetry.
"""

import argparse
import ctypes
import json
import os
import socket
from urllib.parse import urlsplit, parse_qs
from tools.research.cinema_frames import FrameHub
import queue
from concurrent.futures import Future, TimeoutError as FutureTimeout
import struct
import sys
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from tools.research.sony_ptp_controls import SonySettings

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Sony-PMCA-RE'))

# Sony PTP Vendor Opcodes
PTP_OC_OpenSession = 0x1002
PTP_OC_CloseSession = 0x1003
PTP_OC_GetDeviceInfo = 0x1001
PTP_OC_GetObject = 0x1009

PTP_OC_SonySDIOConnect = 0x9201
PTP_OC_SonyGetSDIOExtDeviceInfo = 0x9202
PTP_OC_SonySetControlDeviceA = 0x9205

# Sony Handles & Properties
SONY_HANDLE_LIVEVIEW = 0xFFFFC002
SONY_PROP_PRIORITY_MODE = 0xD25A

PTP_RC_OK = 0x2001
PTP_RC_SessionAlreadyOpened = 0x201E
PTP_RC_DeviceBusy = 0x2019


def parse_jpeg(data: bytes):
    """Find SOI (0xFF, 0xD8) and EOI (0xFF, 0xD9) and parse SOF0 dimensions."""
    soi = data.find(b'\xff\xd8')
    if soi == -1:
        return None
    eoi = data.rfind(b'\xff\xd9')
    if eoi == -1:
        return None
    jpeg_bytes = data[soi:eoi + 2]

    w, h = 0, 0
    for i in range(len(jpeg_bytes) - 8):
        if jpeg_bytes[i] == 0xFF and jpeg_bytes[i + 1] in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack('>HH', jpeg_bytes[i + 5:i + 9])
            break

    return w, h, len(jpeg_bytes), jpeg_bytes


def is_wpd_shutdown_error(exc):
    """True when a WPD COM object was invalidated (device re-enumerated)."""
    text = str(exc).lower()
    return 'shutdown was already called' in text or 'object that owns it' in text


class SonyWpdPTPLiveView:
    def __init__(self):
        from pmca.usb.driver.windows.wpd import MtpContext
        self.ctx = MtpContext()
        self.drv = None

    def connect(self, device_index=0):
        from pmca.usb.driver.windows.wpd import (
            tag_inner_PROPVARIANT, VT_UI4, CreateObject,
            PortableDevicePropVariantCollection,
        )
        print("Discovering Sony cameras via Windows WPD (PC Remote mode)...")
        devices = list(self.ctx.listDevices(0x054C))
        if not devices:
            raise RuntimeError(
                "No Sony camera found on USB in PC Remote mode.\n"
                "Ensure camera is powered ON and set to:\n"
                "  MENU -> Setup -> USB Connection -> PC Remote"
            )
        if not 0 <= device_index < len(devices):
            raise IndexError(f'device index {device_index} outside 0..{len(devices)-1}')
        self.device_count = len(devices)
        self.device_index = device_index
        self.device_handle = devices[device_index].handle

        print(f"Found camera: {self.device_handle} (index {device_index}/{len(devices)})")
        self.drv = self.ctx.openDevice(devices[device_index])

        # Patch 64-bit PROPVARIANT marshaling bug in WPD driver
        def fixed_initPropCollection(values):
            params = CreateObject(PortableDevicePropVariantCollection)
            union_name = tag_inner_PROPVARIANT._fields_[4][0]
            for value in values:
                p = tag_inner_PROPVARIANT()
                p.vt = VT_UI4
                union = getattr(p, union_name)
                union.ulVal = value
                params.Add(ctypes.pointer(p))
            return params

        self.drv._initPropCollection = fixed_initPropCollection

        print("Executing Sony SDIO PTP handshake...")
        rc, d1 = self.drv.sendReadCommand(PTP_OC_SonySDIOConnect, [1, 0, 0])
        if rc != PTP_RC_OK:
            raise RuntimeError(f'SDIO phase 1 failed: 0x{rc:04x}')
        print(f"  SDIOConnect(1, 0, 0) -> rc=0x{rc:04x}")

        rc, d2 = self.drv.sendReadCommand(PTP_OC_SonySDIOConnect, [2, 0, 0])
        if rc != PTP_RC_OK:
            raise RuntimeError(f'SDIO phase 2 failed: 0x{rc:04x}')
        print(f"  SDIOConnect(2, 0, 0) -> rc=0x{rc:04x}")

        rc, d3 = self.drv.sendReadCommand(PTP_OC_SonyGetSDIOExtDeviceInfo, [0xC8])
        if rc != PTP_RC_OK:
            raise RuntimeError(f'SDIO device info failed: 0x{rc:04x}')
        print(f"  GetSDIOExtDeviceInfo(0xC8) -> rc=0x{rc:04x}, len={len(d3)}")

        rc, d4 = self.drv.sendReadCommand(PTP_OC_SonySDIOConnect, [3, 0, 0])
        if rc != PTP_RC_OK:
            raise RuntimeError(f'SDIO phase 3 failed: 0x{rc:04x}')
        print(f"  SDIOConnect(3, 0, 0) -> rc=0x{rc:04x}")

        print("Handshake complete! LiveView ready.\n")

    def get_frame(self, retries=15, retry_delay=0.015):
        self.last_response = None
        self.reconnects = 0
        for _ in range(retries):
            if getattr(self, 'drv', None) is None:
                try:
                    self.connect(getattr(self, 'device_index', 0))
                    self.reconnects += 1
                    self.last_response = {'reconnected': True}
                except Exception as reconnect_exc:
                    self.last_response = {'reconnect_error': repr(reconnect_exc)}
                    time.sleep(0.05)
                    continue
            try:
                rc, data = self.drv.sendReadCommand(PTP_OC_GetObject, [SONY_HANDLE_LIVEVIEW])
                self.last_response = {'rc': rc, 'len': len(data) if data else 0}
                if rc == PTP_RC_OK and data and len(data) > 100:
                    res = parse_jpeg(data)
                    if res and res[0] > 0:
                        return res
                time.sleep(retry_delay)
            except Exception as exc:
                self.last_response = {'error': repr(exc)}
                if is_wpd_shutdown_error(exc):
                    self.close()
                    continue
                time.sleep(0.02)
        return None

    def close(self):
        driver = getattr(self, 'drv', None)
        if driver is None:
            return
        device = getattr(driver, 'device', None)
        try:
            if device is not None:
                device.Close()
        except Exception:
            pass
        self.drv = None


class UvcLiveView:
    def __init__(self, device_index=None, width=1280, height=720, fps=30, auto_launch=True):
        self.device_index = device_index
        self.width = width
        self.height = height
        self.fps = fps
        self.auto_launch = auto_launch
        self.cap = None

    def _ensure_camera_active(self):
        """Auto-detect if Sony UVC is present, and auto-deploy via MSC debugger if needed."""
        import subprocess
        # Quick check if Sony UVC PID 0322 is present in Windows PnP
        try:
            cmd = 'powershell -Command "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like \'*054C&PID_0322*\' } | Select-Object -ExpandProperty InstanceId"'
            out = subprocess.check_output(cmd, shell=True).decode('utf-8', errors='replace').strip()
            if '054C' in out:
                print("  [+] Sony UVC Gadget already detected on host.")
                return True
        except Exception:
            pass

        if not self.auto_launch:
            return False

        print("  [*] Sony UVC Gadget not active. Auto-deploying composite UVC module and 30 FPS feeder via MSC debugger...")
        try:
            from tools.camera_debugger import connect
            ko_path = ROOT / "artifacts/native/uvc-composite-e0143-final/usbg_video_a6400.ko"
            feeder_path = ROOT / "artifacts/native/uvc-disjoint-source-e0143/uvc_stream_feeder_5m"
            if not feeder_path.exists():
                feeder_path = ROOT / "artifacts/native/uvc-disjoint-source-e0143/uvc_stream_feeder_60s"
            if not feeder_path.exists():
                feeder_path = ROOT / "artifacts/native/uvc-disjoint-source-e0143/uvc_stream_feeder_30fps"

            with open(ko_path, 'rb') as f: ko_data = f.read()
            with open(feeder_path, 'rb') as f: feeder_data = f.read()

            with connect() as dbg:
                dbg.request(3, b'rm -f /tmp_bt/feeder.log /tmp_bt/stop_feeder')
                dbg.push('/tmp_bt/usbg_video_a6400.ko', ko_data)
                dbg.push('/tmp_bt/uvc_stream_feeder', feeder_data)
                dbg.request(3, b'chmod 755 /tmp_bt/uvc_stream_feeder')
                kmods, _ = dbg.read_all('/proc/modules')
                if 'usbg_video' not in kmods.decode('latin1'):
                    dbg.request(3, b'insmod /tmp_bt/usbg_video_a6400.ko')
                    dbg.request(3, b'mknod /tmp_bt/video c 248 33 2>/dev/null; chmod 666 /tmp_bt/video')
                dbg.request(3, b'/bin/sh -c "/tmp_bt/uvc_stream_feeder > /tmp_bt/feeder.log 2>&1 &"')
                print("  [+] UVC Feeder launched on camera. Waiting for host enumeration (3s)...")
                time.sleep(3)
                return True
        except Exception as e:
            print(f"  [-] Auto-deploy note: {e}")
            return False

    def _find_sony_device(self):
        """Find the DirectShow device index specifically for 'USB Streaming Device' (Sony)."""
        import subprocess, re
        cmd = ['ffmpeg', '-list_devices', 'true', '-f', 'dshow', '-i', 'dummy']
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='replace')
        devices = []
        for line in p.stderr.splitlines():
            m = re.search(r'"([^"]+)"\s+\(video\)', line)
            if m:
                devices.append(m.group(1))
        for idx, name in enumerate(devices):
            if 'usb streaming device' in name.lower() or 'sony' in name.lower():
                return idx, name
        return None, None

    def connect(self):
        import cv2
        import time

        self._ensure_camera_active()

        target_index = self.device_index
        target_name = "Sony UVC"
        if target_index is None:
            print("Detecting Sony UVC camera ('USB Streaming Device') on DirectShow...")
            for attempt in range(12):
                idx, name = self._find_sony_device()
                if idx is not None:
                    target_index = idx
                    target_name = name
                    print(f"  [+] Found authentic Sony UVC camera at DirectShow index {target_index} ('{target_name}')!")
                    break
                time.sleep(0.5)

            if target_index is None:
                raise RuntimeError(
                    "Sony ILCE-6400 UVC camera ('USB Streaming Device') was not detected on DirectShow!\n"
                    "Refusing to fall back to non-Sony webcams (e.g. Logitech). Feeder or UVC module may not be running."
                )
        
        self.device_index = target_index
        print(f"Connecting to Sony UVC camera at index {self.device_index} ('{target_name}') via DirectShow...")
        self.cap = cv2.VideoCapture(self.device_index, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open Sony UVC video device index {self.device_index}")
        
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"Sony UVC video ready: {actual_w}x{actual_h} @ {self.fps} FPS (DirectShow MJPG)\n")

    def get_frame(self):
        import cv2
        if not self.cap or not self.cap.isOpened():
            return None
        ret, frame = self.cap.read()
        if not ret or frame is None:
            return None
        ret, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        if not ret:
            return None
        jpeg_bytes = buf.tobytes()
        h, w = frame.shape[:2]
        return w, h, len(jpeg_bytes), jpeg_bytes

    def close(self):
        if self.cap:
            self.cap.release()
            self.cap = None


frame_hub = FrameHub()
latest_frame = None
latest_frame_lock = threading.Lock()
stream_active = True

camera_state = {
    "camera": "Sony ILCE-6400",
    "mode": None,
    "shutter": None,
    "aperture": None,
    "iso": None,
    "ev": None,
    "battery": None,
    "recording": None,
    "controls": {},
    "frame_transport": "latest-longpoll-v1",
    "controls_available": False,
    "controls_reason": "Sony PTP command backend is not connected; camera settings are unverified.",
    "input_width": 1024,
    "input_height": 576,
    "fps": 30.0,
    "upscaler": "AMD FSR 1.0 (EASU + RCAS)",
    "gpu_target": "AMD Radeon RX 9070 XT",
}

control_requests = queue.Queue(maxsize=8)
settings_ready = threading.Event()


def publish_settings(settings):
    controls = settings.snapshot()
    camera_state.update(controls=controls,
                        controls_available=any(c['writable'] for c in controls.values()),
                        controls_reason='Settings read from Sony PTP',
                        settings_updated=time.time())
    for name in ('shutter', 'aperture', 'iso', 'ev'):
        camera_state[name] = controls.get(name, {}).get('label')
    battery = settings.properties.get(0x5001)
    camera_state['battery'] = battery['current'] if battery else None
    def property_label(code, labels):
        prop = settings.properties.get(code)
        return labels.get(prop['current']) if prop else None
    camera_state['white_balance'] = property_label(0x5005, {2: 'AUTO', 4: 'DAY', 6: 'TUNG', 7: 'FLASH', 0x8010: 'CLOUD', 0x8011: 'SHADE', 0x8012: 'K'})
    camera_state['focus_mode'] = property_label(0x500A, {1: 'MF', 2: 'AF-S', 3: 'AF-C', 0x8004: 'AF-A', 0x8005: 'DMF'})
    camera_state['exposure_mode'] = property_label(0x500E, {1: 'M', 2: 'P', 3: 'A', 4: 'S', 0x8050: 'MOV M'})


def service_controls(settings):
    """Drain HTTP requests on the COM owner thread between frame transactions."""
    try:
        name, value, future = control_requests.get_nowait()
    except queue.Empty:
        return
    if not future.set_running_or_notify_cancel():
        return
    try:
        settings.apply(name, value)
        publish_settings(settings)
        future.set_result({'status': 'confirmed', 'applied': True,
                           'controls': settings.snapshot()})
    except Exception as exc:
        # apply() may have received a fresh readback even on mismatch.
        publish_settings(settings)
        future.set_exception(exc)


class MJPEGHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.request.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)

    def frame_headers(self, frame):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Cinema-Sequence', str(frame.sequence))
        self.send_header('X-Cinema-Host-Age-Ms', f'{frame.age_ms():.3f}')
        self.send_header('X-Cinema-Fetch-Ms', f'{frame.fetch_ms:.3f}')

    def do_GET(self):
        global latest_frame
        url = urlsplit(self.path)
        if url.path == '/liveview.mjpg':
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            sequence = -1
            while stream_active:
                frame = frame_hub.after(sequence, timeout=1)
                if frame is None:
                    continue
                sequence = frame.sequence
                try:
                    self.wfile.write(b'--frame\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', str(len(frame.jpeg)))
                    self.frame_headers(frame)
                    self.end_headers()
                    self.wfile.write(frame.jpeg)
                    self.wfile.write(b'\r\n')
                    self.wfile.flush()
                except (OSError, ConnectionError):
                    break
        elif url.path == '/frame.jpg':
            try:
                after = int(parse_qs(url.query).get('after', ['-1'])[0])
                if after < -1:
                    raise ValueError('Invalid sequence')
            except ValueError:
                self.send_error(400, 'Invalid frame sequence')
                return
            frame = frame_hub.after(after, timeout=2 if 'after=' in url.query else 0)
            self.close_connection = False
            self.send_response(200 if frame else 204)
            self.send_header('Connection', 'keep-alive')
            self.send_header('Content-Length', str(len(frame.jpeg) if frame else 0))
            self.send_header('X-Cinema-Stream-Id', frame_hub.stream_id)
            if frame:
                self.send_header('Content-Type', 'image/jpeg')
                self.frame_headers(frame)
            self.end_headers()
            if frame:
                self.wfile.write(frame.jpeg)
                self.wfile.flush()
        elif self.path == '/api/status':
            camera_state['frame_age_ms'] = round(frame_hub.latest.age_ms(),3) if frame_hub.latest else None
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(camera_state).encode('utf-8'))
        elif self.path in ('/', '/index.html'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/api/control':
            if self.headers.get_content_type() != 'application/json':
                self.send_error(415, 'Use application/json')
                return
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + self.headers.get('Host', ''):
                self.send_error(403, 'Origin does not match this CinemaHUD')
                return
            content_len = int(self.headers.get('Content-Length', 0))
            if not 0 < content_len <= 4096:
                self.send_error(400, 'Invalid command size')
                return
            post_data = self.rfile.read(content_len)
            try:
                payload = json.loads(post_data.decode('utf-8'))
                param = payload.get('param')
                value = payload.get('value')
                print(f"[PTP Remote Control] Received: {param} = {value}")

                if settings_ready.is_set():
                    if param not in ('shutter', 'aperture', 'iso', 'ev') or type(value) is not int:
                        raise ValueError('Unsupported camera setting or value')
                    future = Future()
                    try:
                        control_requests.put_nowait((param, value, future))
                    except queue.Full:
                        raise ValueError('Camera command queue is busy')
                    try:
                        result = future.result(timeout=10)
                    except FutureTimeout:
                        future.cancel()
                        self.send_response(504)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({'applied': False, 'status': 'unconfirmed',
                            'message': 'Camera confirmation timed out; refresh the current value before retrying.'}).encode())
                        return
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(result).encode())
                    return
                self.send_response(501)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'status': 'unavailable',
                    'message': camera_state['controls_reason'],
                    'applied': False,
                }).encode('utf-8'))
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


HTML_PAGE = (Path(__file__).with_name("cinemahud.html")).read_text(encoding="utf-8")


def start_http_server(port=8080):
    server = ThreadingHTTPServer(('127.0.0.1', port), MJPEGHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"\n=================================================================")
    print(f"  Sony a6400 Cinema Live Monitor [AMD FSR Active]")
    print(f"  Open in browser:  http://127.0.0.1:{port}/")
    print(f"=================================================================\n")
    return server


def main():
    global latest_frame, stream_active
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', choices=['ptp', 'uvc'], default='ptp', help='Video source: ptp (PC Remote) or uvc (USB Video Class)')
    parser.add_argument('--camera-index', type=int, default=None, help='UVC device index for --source uvc (default auto-detect)')
    parser.add_argument('--serve', action='store_true', help='Start HTTP MJPEG / WebGL2 streaming server')
    parser.add_argument('--port', type=int, default=8080, help='Port for HTTP server (default 8080)')
    parser.add_argument('--no-auto-deploy', action='store_true', help='Do not auto-deploy UVC module via MSC debugger')
    parser.add_argument('--frames', type=int, default=10, help='Frames to capture if not serving')
    parser.add_argument('--save-frame', type=Path, default=Path('artifacts/hardware/liveview_1080p_sample.jpg'))
    args = parser.parse_args()

    if args.source == 'uvc':
        client = UvcLiveView(device_index=args.camera_index, auto_launch=not args.no_auto_deploy)
        camera_state['mode'] = "UVC Stream"
    else:
        client = SonyWpdPTPLiveView()

    try:
        if args.source == 'ptp':
            client.connect(device_index=args.camera_index or 0)
        else:
            client.connect()
    except Exception as e:
        client.close()
        print(f"Connection error: {e}")
        return 1

    settings, last_settings_poll = None, 0
    http_server = None
    if args.source == 'ptp':
        settings = SonySettings(client.drv)
    if args.serve:
        http_server = start_http_server(args.port)

    print("Streaming LiveView frames (Ctrl+C to stop)...")
    frame_count = 0
    t0 = time.monotonic()
    saved = False

    def capture_one():
        global latest_frame
        nonlocal frame_count, saved
        fetch_start = time.perf_counter_ns()
        res = client.get_frame(retries=1, retry_delay=0.002) if args.source == 'ptp' else client.get_frame()
        fetch_ms = (time.perf_counter_ns()-fetch_start)/1e6
        if res:
            w, h, sz, jpeg_bytes = res
            frame_count += 1
            with latest_frame_lock:
                latest_frame = jpeg_bytes

            published = frame_hub.publish(jpeg_bytes, fetch_ms)
            camera_state.update(frame_sequence=published.sequence, ptp_fetch_ms=round(fetch_ms,3))
            camera_state['input_width'] = w
            camera_state['input_height'] = h

            elapsed = time.monotonic() - t0
            fps = frame_count / elapsed if elapsed > 0 else 0
            camera_state['fps'] = round(fps, 1)
            print(f"Frame #{frame_count:04d}: {w}x{h} px | {sz:6d} bytes ({sz / 1024:.1f} KiB) | {fps:4.1f} FPS", end='\r')

            if not saved and args.save_frame:
                args.save_frame.parent.mkdir(parents=True, exist_ok=True)
                args.save_frame.write_bytes(jpeg_bytes)
                saved = True
        else:
            time.sleep(0.002)
        return res is not None

    if settings is not None and args.serve:
        settings.on_progress = capture_one

    try:
        while args.serve or frame_count < args.frames:
            if settings is not None:
                # A reconnect creates a new driver on this same owner thread.
                settings.driver = client.drv
                if time.monotonic() - last_settings_poll >= 1:
                    try:
                        settings.refresh()
                        publish_settings(settings)
                        settings_ready.set()
                    except Exception as exc:
                        settings_ready.clear()
                        camera_state.update(controls_available=False, controls={},
                                            controls_reason=str(exc), settings_updated=None,
                                            shutter=None, aperture=None, iso=None, ev=None, battery=None)
                    last_settings_poll = time.monotonic()
                if settings_ready.is_set():
                    service_controls(settings)
            capture_one()
    except KeyboardInterrupt:
        print("\nStopping stream...")
    finally:
        stream_active = False
        settings_ready.clear()
        if http_server is not None:
            http_server.shutdown()
            http_server.server_close()
        client.close()

    print(f"\nDone. Captured {frame_count} frames.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
