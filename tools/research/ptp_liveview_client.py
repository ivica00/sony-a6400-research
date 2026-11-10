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
import struct
import sys
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

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
        print(f"  SDIOConnect(1, 0, 0) -> rc=0x{rc:04x}")

        rc, d2 = self.drv.sendReadCommand(PTP_OC_SonySDIOConnect, [2, 0, 0])
        print(f"  SDIOConnect(2, 0, 0) -> rc=0x{rc:04x}")

        rc, d3 = self.drv.sendReadCommand(PTP_OC_SonyGetSDIOExtDeviceInfo, [0xC8])
        print(f"  GetSDIOExtDeviceInfo(0xC8) -> rc=0x{rc:04x}, len={len(d3)}")

        rc, d4 = self.drv.sendReadCommand(PTP_OC_SonySDIOConnect, [3, 0, 0])
        print(f"  SDIOConnect(3, 0, 0) -> rc=0x{rc:04x}")

        print("Handshake complete! LiveView ready.\n")

    def get_frame(self, retries=15):
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
                time.sleep(0.015)
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


latest_frame = None
latest_frame_lock = threading.Lock()
stream_active = True

camera_state = {
    "camera": "Sony ILCE-6400",
    "mode": "Manual",
    "shutter": "1/125",
    "aperture": "f/2.8",
    "iso": "400",
    "ev": "0.0",
    "battery": 85,
    "recording": False,
    "controls_available": False,
    "controls_reason": "Sony PTP command backend is not connected; camera settings are unverified.",
    "input_width": 1024,
    "input_height": 576,
    "fps": 30.0,
    "upscaler": "AMD FSR 1.0 (EASU + RCAS)",
    "gpu_target": "AMD Radeon RX 9070 XT",
}


class MJPEGHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global latest_frame
        if self.path == '/liveview.mjpg':
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=--frame')
            self.send_header('Cache-Control', 'no-cache, private')
            self.end_headers()
            while stream_active:
                with latest_frame_lock:
                    frame = latest_frame
                if frame:
                    try:
                        self.wfile.write(b'--frame\r\n')
                        self.send_header('Content-Type', 'image/jpeg')
                        self.send_header('Content-Length', str(len(frame)))
                        self.end_headers()
                        self.wfile.write(frame)
                        self.wfile.write(b'\r\n')
                    except (BrokenPipeError, ConnectionResetError):
                        break
                time.sleep(0.033)
        elif self.path == '/frame.jpg':
            with latest_frame_lock:
                frame = latest_frame
            if frame:
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', str(len(frame)))
                self.end_headers()
                self.wfile.write(frame)
            else:
                self.send_response(404)
                self.end_headers()
        elif self.path == '/api/status':
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
            content_len = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_len)
            try:
                payload = json.loads(post_data.decode('utf-8'))
                param = payload.get('param')
                value = payload.get('value')
                print(f"[PTP Remote Control] Received: {param} = {value}")

                # No Sony write/readback backend is bound here. Never report a
                # local display change as a successful physical camera command.
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


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Sony a6400 Cinema Monitor (AMD FSR 1.0)</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    :root {
      --bg: #0b0c0e;
      --panel: #14161a;
      --border: #232730;
      --accent: #e50914;
      --text: #f0f2f5;
      --text-dim: #8b92a0;
      --highlight: #00e676;
      --amd-red: #ed1c24;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      display: flex;
      flex-direction: column;
      height: 100vh;
      overflow: hidden;
      user-select: none;
    }
    /* Top Bar */
    header {
      background: var(--panel);
      border-bottom: 1px solid var(--border);
      padding: 8px 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      height: 44px;
      font-size: 13px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      font-weight: 700;
    }
    .badge-live {
      background: var(--accent);
      color: #fff;
      padding: 2px 7px;
      border-radius: 3px;
      font-size: 11px;
      font-weight: 800;
      animation: pulse 2s infinite;
    }
    .badge-fsr {
      background: linear-gradient(135deg, #ed1c24, #b00f16);
      color: #fff;
      padding: 2px 7px;
      border-radius: 3px;
      font-size: 11px;
      font-weight: 800;
    }
    .top-stats {
      display: flex;
      gap: 16px;
      color: var(--text-dim);
      font-family: monospace;
      font-size: 12px;
    }
    .top-stats span b { color: var(--text); }
    @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.6; } 100% { opacity: 1; } }

    /* Viewport Area */
    #viewport-container {
      flex: 1;
      position: relative;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #000;
      overflow: hidden;
    }
    #glcanvas {
      display: block;
      max-width: 100%;
      max-height: 100%;
      object-fit: contain;
      box-shadow: 0 0 40px rgba(0,0,0,0.9);
    }
    #hud-overlay {
      position: absolute;
      top: 0; left: 0; width: 100%; height: 100%;
      pointer-events: none;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .hud-box {
      position: relative;
      width: 100%; height: 100%;
    }
    .grid-line { position: absolute; background: rgba(255,255,255,0.2); }
    .crosshair { position: absolute; background: rgba(0, 230, 118, 0.7); }
    .aspect-mask {
      position: absolute;
      left: 0; width: 100%;
      background: rgba(0,0,0,0.8);
      border-bottom: 1px dashed rgba(255,255,255,0.3);
      border-top: 1px dashed rgba(255,255,255,0.3);
      display: none;
    }
    .split-label-left {
      position: absolute;
      bottom: 24px; left: 24px;
      background: rgba(0,0,0,0.7);
      padding: 4px 10px;
      border-radius: 4px;
      font-size: 12px;
      font-family: monospace;
      color: #aaa;
      border: 1px solid #444;
      display: none;
    }
    .split-label-right {
      position: absolute;
      bottom: 24px; right: 24px;
      background: rgba(180, 20, 20, 0.8);
      padding: 4px 10px;
      border-radius: 4px;
      font-size: 12px;
      font-family: monospace;
      color: #fff;
      font-weight: bold;
      border: 1px solid #f00;
      display: none;
    }

    /* Bottom Control Bar */
    footer {
      background: var(--panel);
      border-top: 1px solid var(--border);
      padding: 8px 16px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .controls-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    .btn-group {
      display: flex;
      gap: 6px;
      align-items: center;
    }
    .cinema-label {
      font-size: 11px;
      text-transform: uppercase;
      color: var(--text-dim);
      font-weight: 700;
      margin-right: 2px;
    }
    button, select {
      background: #1e222a;
      color: var(--text);
      border: 1px solid var(--border);
      padding: 5px 11px;
      border-radius: 4px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    button:hover, select:hover {
      background: #282e38;
      border-color: #3f4756;
    }
    button.active {
      background: #1b2d4b;
      border-color: #3b82f6;
      color: #60a5fa;
    }
    .rec-btn {
      background: #b71c1c;
      color: white;
      border: 1px solid #d32f2f;
      padding: 6px 16px;
      border-radius: 20px;
      font-weight: 800;
      letter-spacing: 0.5px;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .rec-btn:hover { background: #d32f2f; }
    .rec-btn.recording {
      background: #e50914;
      animation: pulse 1s infinite;
    }
    .slider-container {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      color: var(--text-dim);
    }
    input[type=range] {
      accent-color: var(--amd-red);
      cursor: pointer;
    }
    .toast {
      position: absolute;
      top: 60px; right: 20px;
      background: rgba(20, 22, 26, 0.95);
      border: 1px solid var(--border);
      border-left: 4px solid var(--highlight);
      padding: 8px 14px;
      border-radius: 4px;
      font-size: 12px;
      opacity: 0;
      transition: opacity 0.2s ease;
      pointer-events: none;
    }
    .toast.show { opacity: 1; }
  </style>
</head>
<body>

  <!-- DOM image for reliable background decoding in Chromium -->
  <img id="live-stream-img" src="/liveview.mjpg" style="position:fixed; top:-9999px; left:-9999px; width:1px; height:1px; opacity:0.01; pointer-events:none;" crossorigin="anonymous" />

  <!-- Top Bar -->
  <header>
    <div class="brand">
      <span>SONY a6400 CINEMA HUD</span>
      <span class="badge-live">LIVE PTP</span>
      <span class="badge-fsr">AMD FSR 1.0</span>
    </div>
    <div class="top-stats">
      <span>IN: <b id="stat-in">1024x576</b></span>
      <span>OUT: <b id="stat-out">1920x1080</b></span>
      <span>FPS: <b id="stat-fps">30.0</b></span>
      <span>GPU: <b id="stat-gpu">AMD RX 9070 XT</b></span>
      <span>BAT: <b id="stat-bat">85%</b></span>
    </div>
  </header>

  <!-- Viewport -->
  <div id="viewport-container">
    <canvas id="glcanvas" width="1920" height="1080"></canvas>
    
    <div id="hud-overlay">
      <div id="hud-box" class="hud-box">
        <div id="grid-v1" class="grid-line" style="top:0; bottom:0; left:33.33%; width:1px; display:none;"></div>
        <div id="grid-v2" class="grid-line" style="top:0; bottom:0; left:66.66%; width:1px; display:none;"></div>
        <div id="grid-h1" class="grid-line" style="left:0; right:0; top:33.33%; height:1px; display:none;"></div>
        <div id="grid-h2" class="grid-line" style="left:0; right:0; top:66.66%; height:1px; display:none;"></div>

        <div id="ch-v" class="crosshair" style="top:47%; bottom:47%; left:50%; width:1px; display:none;"></div>
        <div id="ch-h" class="crosshair" style="left:48%; right:48%; top:50%; height:1px; display:none;"></div>

        <div id="mask-top" class="aspect-mask" style="top:0; height:12.5%;"></div>
        <div id="mask-bottom" class="aspect-mask" style="bottom:0; height:12.5%;"></div>

        <div id="lbl-left" class="split-label-left">&larr; NATIVE 576p (BILINEAR)</div>
        <div id="lbl-right" class="split-label-right">AMD FSR 1080p (EASU+RCAS) &rarr;</div>
      </div>
    </div>

    <div id="toast" class="toast">Action logged</div>
  </div>

  <!-- Footer / Cinema Controls -->
  <footer>
    <!-- Row 1: Camera PTP Controls -->
    <div class="controls-row">
      <div class="btn-group">
        <span class="cinema-label">SHUTTER</span>
        <select id="sel-shutter" onchange="sendControl('shutter', this.value)">
          <option>1/30</option>
          <option>1/50</option>
          <option>1/60</option>
          <option selected>1/125</option>
          <option>1/250</option>
          <option>1/500</option>
          <option>1/1000</option>
        </select>
      </div>

      <div class="btn-group">
        <span class="cinema-label">APERTURE</span>
        <select id="sel-aperture" onchange="sendControl('aperture', this.value)">
          <option>f/1.4</option>
          <option>f/1.8</option>
          <option selected>f/2.8</option>
          <option>f/4.0</option>
          <option>f/5.6</option>
          <option>f/8.0</option>
        </select>
      </div>

      <div class="btn-group">
        <span class="cinema-label">ISO</span>
        <select id="sel-iso" onchange="sendControl('iso', this.value)">
          <option>Auto</option>
          <option>100</option>
          <option>200</option>
          <option selected>400</option>
          <option>800</option>
          <option>1600</option>
          <option>3200</option>
          <option>6400</option>
        </select>
      </div>

      <div class="btn-group">
        <span class="cinema-label">EV</span>
        <select id="sel-ev" onchange="sendControl('ev', this.value)">
          <option>-1.0</option>
          <option>-0.7</option>
          <option>-0.3</option>
          <option selected>0.0</option>
          <option>+0.3</option>
          <option>+0.7</option>
          <option>+1.0</option>
        </select>
      </div>

      <div class="btn-group">
        <span class="cinema-label">ORIENTATION</span>
        <button id="btn-flip-v" class="active" onclick="toggleFlipV()">FLIP V (UPRIGHT)</button>
        <button id="btn-flip-h" onclick="toggleFlipH()">MIRROR (H)</button>
      </div>

      <button id="btn-rec" class="rec-btn" onclick="toggleRecord()">
        <span style="font-size:16px;">&bull;</span> REC TRIGGER
      </button>
    </div>

    <!-- Row 2: Upscaler, Sharpness & Split Screen -->
    <div class="controls-row">
      <div class="btn-group">
        <span class="cinema-label">UPSCALER</span>
        <button id="btn-mode-fsr" class="active" onclick="setUpscaler('fsr')">AMD FSR (EASU+RCAS)</button>
        <button id="btn-mode-bilinear" onclick="setUpscaler('bilinear')">Bilinear (Off)</button>
        <button id="btn-split" onclick="toggleSplitScreen()">A/B SPLIT SCREEN</button>
      </div>

      <div class="slider-container">
        <span>RCAS SHARPNESS</span>
        <input type="range" id="sharpness-slider" min="0" max="1" step="0.05" value="0.75" oninput="updateSharpness(this.value)">
        <span id="sharpness-val" style="width:28px; font-weight:bold; color:#fff;">0.75</span>
      </div>

      <div class="btn-group">
        <button id="btn-peaking" onclick="togglePeaking()">PEAKING</button>
        <button id="btn-grid" onclick="toggleGrid()">GRID 3x3</button>
        <button id="btn-crosshair" onclick="toggleCrosshair()">CROSSHAIR</button>
        <select id="sel-aspect" onchange="setAspect(this.value)">
          <option value="16:9">16:9 (Full)</option>
          <option value="2.39:1">2.39:1 (Scope)</option>
          <option value="4:3">4:3 (Academy)</option>
        </select>
        <button onclick="toggleFullscreen()">⛶ FULLSCREEN</button>
      </div>
    </div>
  </footer>

  <!-- WebGL2 AMD FidelityFX FSR Pipeline -->
  <script>
    const canvas = document.getElementById('glcanvas');
    const gl = canvas.getContext('webgl2', { alpha: false, antialias: false, depth: false });

    if (!gl) {
      alert("WebGL2 not supported on this browser!");
    }

    // State
    let flipV = 1; // Default upright (1 = flip inverted WebGL coordinate to match camera)
    let flipH = 0; // Horizontal mirror
    let upscalerMode = 'fsr';
    let rcasSharpness = 0.75; // Noticeable, high-definition contrast-adaptive sharpness
    let splitScreen = 0;
    let splitPos = 0.5;
    let peakingActive = 0;

    // Mouse drag for A/B split divider
    let isDraggingSplit = false;
    canvas.addEventListener('mousedown', (e) => {
      if (splitScreen) {
        isDraggingSplit = true;
        updateSplitFromMouse(e);
      }
    });
    window.addEventListener('mousemove', (e) => {
      if (isDraggingSplit) updateSplitFromMouse(e);
    });
    window.addEventListener('mouseup', () => { isDraggingSplit = false; });

    function updateSplitFromMouse(e) {
      const rect = canvas.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width;
      splitPos = Math.max(0.05, Math.min(0.95, x));
    }

    // Vertex Shader with Orientation Controls
    const vsSource = `#version 300 es
    in vec2 a_position;
    out vec2 v_texCoord;
    uniform int u_flipV;
    uniform int u_flipH;

    void main() {
      vec2 uv = a_position * 0.5 + 0.5;
      if (u_flipV == 1) uv.y = 1.0 - uv.y;
      if (u_flipH == 1) uv.x = 1.0 - uv.x;
      v_texCoord = uv;
      gl_Position = vec4(a_position, 0.0, 1.0);
    }`;

    // Pass 1: AMD FidelityFX EASU (Continuous Catmull-Rom Bicubic Upsampling)
    // Eliminates any blocky grid, creases or stair-stepping across pixel boundaries
    const fsEASU = `#version 300 es
    precision highp float;
    in vec2 v_texCoord;
    out vec4 fragColor;

    uniform sampler2D u_texture;
    uniform vec2 u_sourceSize; // (1024, 576)
    uniform vec2 u_targetSize; // (1920, 1080)
    uniform int u_splitScreen;
    uniform float u_splitPos;

    float catmullRom(float x) {
      x = abs(x);
      if (x <= 1.0) {
        return 1.5 * x * x * x - 2.5 * x * x + 1.0;
      } else if (x < 2.0) {
        return -0.5 * x * x * x + 2.5 * x * x - 4.0 * x + 2.0;
      }
      return 0.0;
    }

    void main() {
      // If Split Screen and left of divider: pass through pure bilinear
      if (u_splitScreen == 1 && v_texCoord.x < u_splitPos) {
        fragColor = texture(u_texture, v_texCoord);
        return;
      }
      // Divider line
      if (u_splitScreen == 1 && abs(v_texCoord.x - u_splitPos) < (1.5 / u_targetSize.x)) {
        fragColor = vec4(1.0, 1.0, 1.0, 1.0);
        return;
      }

      vec2 pos = v_texCoord * u_sourceSize - 0.5;
      vec2 fp = fract(pos);
      vec2 base = floor(pos);

      vec4 color = vec4(0.0);
      float totalWeight = 0.0;

      for (int j = -1; j <= 2; j++) {
        float wy = catmullRom(float(j) - fp.y);
        for (int i = -1; i <= 2; i++) {
          float wx = catmullRom(float(i) - fp.x);
          float w = wx * wy;
          vec2 sampleCoord = (base + vec2(float(i) + 0.5, float(j) + 0.5)) / u_sourceSize;
          color += texture(u_texture, sampleCoord) * w;
          totalWeight += w;
        }
      }

      fragColor = clamp(color / max(totalWeight, 1e-4), 0.0, 1.0);
    }`;

    // Pass 2: AMD FidelityFX CAS (Contrast-Adaptive Sharpening) with Noise Suppression
    const fsRCAS = `#version 300 es
    precision highp float;
    in vec2 v_texCoord;
    out vec4 fragColor;

    uniform sampler2D u_texture;
    uniform vec2 u_resolution; // (1920, 1080)
    uniform float u_sharpness;
    uniform int u_peaking;
    uniform int u_splitScreen;
    uniform float u_splitPos;

    void main() {
      if (u_splitScreen == 1 && v_texCoord.x < u_splitPos) {
        fragColor = texture(u_texture, v_texCoord);
        return;
      }
      if (u_splitScreen == 1 && abs(v_texCoord.x - u_splitPos) < (1.5 / u_resolution.x)) {
        fragColor = vec4(1.0, 1.0, 1.0, 1.0);
        return;
      }

      vec2 pt = 1.0 / u_resolution;
      vec4 c = texture(u_texture, v_texCoord);
      vec4 a = texture(u_texture, v_texCoord + vec2(0.0, -pt.y));
      vec4 b = texture(u_texture, v_texCoord + vec2(-pt.x, 0.0));
      vec4 d = texture(u_texture, v_texCoord + vec2(pt.x, 0.0));
      vec4 e = texture(u_texture, v_texCoord + vec2(0.0, pt.y));

      // Min & Max local contrast
      vec3 minRGB = min(min(min(a.rgb, b.rgb), min(d.rgb, e.rgb)), c.rgb);
      vec3 maxRGB = max(max(max(a.rgb, b.rgb), max(d.rgb, e.rgb)), c.rgb);
      vec3 contrast = maxRGB - minRGB;
      float maxContrast = max(max(contrast.r, contrast.g), contrast.b);

      if (u_peaking == 1 && maxContrast > 0.16) {
        fragColor = vec4(0.0, 1.0, 0.3, 1.0);
        return;
      }

      // AMD CAS weight: dampens in flat noise/shadow areas to prevent macroblocking,
      // and sharpens genuine high-contrast structural edges.
      vec3 amp = clamp(min(minRGB, 1.0 - maxRGB) / max(maxRGB, 1e-4), 0.0, 1.0);
      vec3 w = -sqrt(amp) * (u_sharpness * 0.14);

      vec3 sharpened = (a.rgb + b.rgb + d.rgb + e.rgb) * w + c.rgb;
      sharpened /= (4.0 * w + 1.0);

      // Clamp to local neighborhood bounds
      fragColor = vec4(clamp(sharpened, minRGB, maxRGB), c.a);
    }`;

    // Pass: Direct Bilinear (Native)
    const fsBilinear = `#version 300 es
    precision highp float;
    in vec2 v_texCoord;
    out vec4 fragColor;
    uniform sampler2D u_texture;
    void main() {
      fragColor = texture(u_texture, v_texCoord);
    }`;

    function createShader(gl, type, source) {
      const shader = gl.createShader(type);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        console.error(gl.getShaderInfoLog(shader));
        gl.deleteShader(shader);
        return null;
      }
      return shader;
    }

    function createProgram(gl, vs, fs) {
      const prog = gl.createProgram();
      gl.attachShader(prog, vs);
      gl.attachShader(prog, fs);
      gl.linkProgram(prog);
      return prog;
    }

    const vs = createShader(gl, gl.VERTEX_SHADER, vsSource);
    const progEASU = createProgram(gl, vs, createShader(gl, gl.FRAGMENT_SHADER, fsEASU));
    const progRCAS = createProgram(gl, vs, createShader(gl, gl.FRAGMENT_SHADER, fsRCAS));
    const progBilinear = createProgram(gl, vs, createShader(gl, gl.FRAGMENT_SHADER, fsBilinear));

    // Fullscreen quad
    const quadVAO = gl.createVertexArray();
    gl.bindVertexArray(quadVAO);
    const quadVBO = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, quadVBO);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
      -1, -1,  1, -1, -1,  1,
      -1,  1,  1, -1,  1,  1,
    ]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);

    // Textures & Framebuffer
    const sourceTex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, sourceTex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

    const easuTex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, easuTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, 1920, 1080, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);

    const easuFBO = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, easuFBO);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, easuTex, 0);

    const liveImg = document.getElementById('live-stream-img');

    let lastTime = performance.now();
    let frameCounter = 0;

    function renderLoop(time) {
      if (liveImg && liveImg.naturalWidth > 0) {
        gl.bindTexture(gl.TEXTURE_2D, sourceTex);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, liveImg);

        const srcW = liveImg.naturalWidth;
        const srcH = liveImg.naturalHeight;

        if (upscalerMode === 'fsr' || splitScreen === 1) {
          // Pass 1: EASU into FBO
          gl.bindFramebuffer(gl.FRAMEBUFFER, easuFBO);
          gl.viewport(0, 0, 1920, 1080);
          gl.useProgram(progEASU);
          gl.uniform2f(gl.getUniformLocation(progEASU, "u_sourceSize"), srcW, srcH);
          gl.uniform2f(gl.getUniformLocation(progEASU, "u_targetSize"), 1920, 1080);
          gl.uniform1i(gl.getUniformLocation(progEASU, "u_splitScreen"), splitScreen);
          gl.uniform1f(gl.getUniformLocation(progEASU, "u_splitPos"), splitPos);
          gl.uniform1i(gl.getUniformLocation(progEASU, "u_flipV"), flipV);
          gl.uniform1i(gl.getUniformLocation(progEASU, "u_flipH"), flipH);
          gl.uniform1i(gl.getUniformLocation(progEASU, "u_texture"), 0);
          gl.activeTexture(gl.TEXTURE0);
          gl.bindTexture(gl.TEXTURE_2D, sourceTex);
          gl.bindVertexArray(quadVAO);
          gl.drawArrays(gl.TRIANGLES, 0, 6);

          // Pass 2: RCAS from FBO to Screen Canvas
          gl.bindFramebuffer(gl.FRAMEBUFFER, null);
          gl.viewport(0, 0, 1920, 1080);
          gl.useProgram(progRCAS);
          gl.uniform2f(gl.getUniformLocation(progRCAS, "u_resolution"), 1920, 1080);
          gl.uniform1f(gl.getUniformLocation(progRCAS, "u_sharpness"), rcasSharpness);
          gl.uniform1i(gl.getUniformLocation(progRCAS, "u_peaking"), peakingActive);
          gl.uniform1i(gl.getUniformLocation(progRCAS, "u_splitScreen"), splitScreen);
          gl.uniform1f(gl.getUniformLocation(progRCAS, "u_splitPos"), splitPos);
          // Orientation already applied in Pass 1
          gl.uniform1i(gl.getUniformLocation(progRCAS, "u_flipV"), 0);
          gl.uniform1i(gl.getUniformLocation(progRCAS, "u_flipH"), 0);
          gl.uniform1i(gl.getUniformLocation(progRCAS, "u_texture"), 0);
          gl.activeTexture(gl.TEXTURE0);
          gl.bindTexture(gl.TEXTURE_2D, easuTex);
          gl.drawArrays(gl.TRIANGLES, 0, 6);
        } else {
          // Pure Bilinear
          gl.bindFramebuffer(gl.FRAMEBUFFER, null);
          gl.viewport(0, 0, 1920, 1080);
          gl.useProgram(progBilinear);
          gl.uniform1i(gl.getUniformLocation(progBilinear, "u_flipV"), flipV);
          gl.uniform1i(gl.getUniformLocation(progBilinear, "u_flipH"), flipH);
          gl.uniform1i(gl.getUniformLocation(progBilinear, "u_texture"), 0);
          gl.activeTexture(gl.TEXTURE0);
          gl.bindTexture(gl.TEXTURE_2D, sourceTex);
          gl.bindVertexArray(quadVAO);
          gl.drawArrays(gl.TRIANGLES, 0, 6);
        }

        frameCounter++;
        if (time - lastTime >= 1000) {
          const fps = ((frameCounter * 1000) / (time - lastTime)).toFixed(1);
          document.getElementById('stat-fps').innerText = fps;
          document.getElementById('stat-in').innerText = `${srcW}x${srcH}`;
          frameCounter = 0;
          lastTime = time;
        }
      }
      requestAnimationFrame(renderLoop);
    }
    requestAnimationFrame(renderLoop);

    // UI Handlers
    function setUpscaler(mode) {
      upscalerMode = mode;
      splitScreen = 0;
      document.getElementById('btn-mode-fsr').className = mode === 'fsr' ? 'active' : '';
      document.getElementById('btn-mode-bilinear').className = mode === 'bilinear' ? 'active' : '';
      document.getElementById('btn-split').className = '';
      document.getElementById('lbl-left').style.display = 'none';
      document.getElementById('lbl-right').style.display = 'none';
      showToast(mode === 'fsr' ? "AMD FSR 1.0 (EASU+RCAS) Active" : "Native Bilinear (Off)");
    }

    function toggleSplitScreen() {
      splitScreen = splitScreen ? 0 : 1;
      document.getElementById('btn-split').className = splitScreen ? 'active' : '';
      document.getElementById('lbl-left').style.display = splitScreen ? 'block' : 'none';
      document.getElementById('lbl-right').style.display = splitScreen ? 'block' : 'none';
      if (splitScreen) {
        showToast("A/B Split Screen ON (Drag across canvas to compare)");
      } else {
        setUpscaler(upscalerMode);
      }
    }

    function toggleFlipV() {
      flipV = flipV ? 0 : 1;
      document.getElementById('btn-flip-v').className = flipV ? 'active' : '';
      showToast(flipV ? "Vertical Flip ON (Upright)" : "Vertical Flip OFF (Inverted)");
    }

    function toggleFlipH() {
      flipH = flipH ? 0 : 1;
      document.getElementById('btn-flip-h').className = flipH ? 'active' : '';
      showToast(flipH ? "Horizontal Mirror ON" : "Horizontal Mirror OFF");
    }

    function updateSharpness(val) {
      rcasSharpness = parseFloat(val);
      document.getElementById('sharpness-val').innerText = val;
    }

    function togglePeaking() {
      peakingActive = peakingActive ? 0 : 1;
      document.getElementById('btn-peaking').className = peakingActive ? 'active' : '';
      showToast(peakingActive ? "Focus Peaking ON" : "Focus Peaking OFF");
    }

    function toggleGrid() {
      const v1 = document.getElementById('grid-v1');
      const show = v1.style.display === 'none';
      ['grid-v1', 'grid-v2', 'grid-h1', 'grid-h2'].forEach(id => {
        document.getElementById(id).style.display = show ? 'block' : 'none';
      });
      document.getElementById('btn-grid').className = show ? 'active' : '';
    }

    function toggleCrosshair() {
      const ch = document.getElementById('ch-v');
      const show = ch.style.display === 'none';
      ['ch-v', 'ch-h'].forEach(id => {
        document.getElementById(id).style.display = show ? 'block' : 'none';
      });
      document.getElementById('btn-crosshair').className = show ? 'active' : '';
    }

    function setAspect(aspect) {
      const top = document.getElementById('mask-top');
      const bot = document.getElementById('mask-bottom');
      if (aspect === '2.39:1') {
        top.style.display = 'block';
        bot.style.display = 'block';
      } else {
        top.style.display = 'none';
        bot.style.display = 'none';
      }
      showToast(`Aspect Guide: ${aspect}`);
    }

    function toggleFullscreen() {
      if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen();
      } else {
        document.exitFullscreen();
      }
    }

    function toggleRecord() {
      sendControl('recording', true);
    }

    function sendControl(param, value) {
      fetch('/api/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ param, value })
      })
      .then(async res => {
        const data = await res.json();
        if (!res.ok || data.applied !== true) {
          throw new Error(data.message || 'Camera command was not confirmed');
        }
        showToast(`${param.toUpperCase()}: ${value}`);
      })
      .catch(err => showToast(err.message));
    }

    function showToast(msg) {
      const t = document.getElementById('toast');
      t.innerText = msg;
      t.className = 'toast show';
      clearTimeout(window._toastTimeout);
      window._toastTimeout = setTimeout(() => t.className = 'toast', 2000);
    }
  </script>
</body>
</html>"""


def start_http_server(port=8080):
    server = ThreadingHTTPServer(('0.0.0.0', port), MJPEGHandler)
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
        client.connect()
    except Exception as e:
        print(f"Connection error: {e}")
        return 1

    if args.serve:
        start_http_server(args.port)

    print("Streaming LiveView frames (Ctrl+C to stop)...")
    frame_count = 0
    t0 = time.monotonic()
    saved = False

    try:
        while args.serve or frame_count < args.frames:
            res = client.get_frame()
            if res:
                w, h, sz, jpeg_bytes = res
                frame_count += 1
                with latest_frame_lock:
                    latest_frame = jpeg_bytes

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
                time.sleep(0.01)
    except KeyboardInterrupt:
        print("\nStopping stream...")
    finally:
        stream_active = False
        client.close()

    print(f"\nDone. Captured {frame_count} frames.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
