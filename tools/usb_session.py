import sys
import io
import os
import time
import threading
import http.server
import urllib.parse
import json

sys.path.insert(0, 'Sony-PMCA-RE')
from pmca.commands.usb import (
    importDriver, listDevices, getDevice,
    SonyMscExtCmdDevice, SonySenserDevice,
    SonySenserAuthDevice, SonySenserCamera,
    GenericUsbDriver
)

HTTP_PORT = 8088
cam_lock = threading.Lock()
active_cam = None
stop_event = threading.Event()

def execute_shell_on_camera(cam, cmd_str, timeout=10.0):
    """Executes a command via /tmp/usb_cmd.txt -> usb_shell_daemon -> /tmp/usb_out.txt"""
    # Clean old done / out files
    try:
        cam.deleteFile('/tmp/usb_done')
    except Exception:
        pass
    try:
        cam.deleteFile('/tmp/usb_out.txt')
    except Exception:
        pass

    # Write command
    cam.writeFile('/tmp/usb_cmd.txt', (cmd_str + "\n").encode('latin1'))

    # Poll for completion
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(0.04)
        try:
            buf = io.BytesIO()
            cam.readFile('/tmp/usb_done', buf)
            # Command finished! Read output
            buf_out = io.BytesIO()
            cam.readFile('/tmp/usb_out.txt', buf_out)
            return buf_out.getvalue().decode('latin1', errors='replace')
        except Exception:
            continue
    return "[-] Command timed out (daemon not responding or command took > 10s)\n"

class UsbApiHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress noisy HTTP server logs to keep console clean
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)

        if parsed.path == '/ping':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok', 'active': active_cam is not None}).encode())
            return

        if parsed.path == '/delete':
            remote_path = qs.get('path', [''])[0]
            if not remote_path or active_cam is None:
                self.send_response(400)
                self.end_headers()
                return
            with cam_lock:
                try:
                    active_cam.deleteFile(remote_path)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"DELETED\n")
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(str(e).encode())
            return

        if parsed.path == '/memory':
            base_str = qs.get('base', ['0'])[0]
            size_str = qs.get('size', ['0'])[0]
            base = int(base_str, 0)
            size = int(size_str, 0)
            if size <= 0 or active_cam is None:
                self.send_response(400)
                self.end_headers()
                return
            with cam_lock:
                buf = io.BytesIO()
                try:
                    active_cam.readMemory(base, size, buf)
                    data = buf.getvalue()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/octet-stream')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(str(e).encode())
            return

        if parsed.path == '/delete':
            remote_path = qs.get('path', [''])[0]
            if not remote_path or active_cam is None:
                self.send_response(400)
                self.end_headers()
                return
            with cam_lock:
                try:
                    active_cam.deleteFile(remote_path)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"DELETED\n")
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(str(e).encode())
            return

        if parsed.path == '/memory':
            base_str = qs.get('base', ['0'])[0]
            base = int(base_str, 0)
            if active_cam is None:
                self.send_response(503)
                self.end_headers()
                return
            with cam_lock:
                try:
                    active_cam.writeMemory(base, body)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"OK\n")
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(str(e).encode())
            return

        if parsed.path == '/file':
            remote_path = qs.get('path', [''])[0]
            if not remote_path or active_cam is None:
                self.send_response(400)
                self.end_headers()
                return
            with cam_lock:
                buf = io.BytesIO()
                try:
                    active_cam.readFile(remote_path, buf)
                    data = buf.getvalue()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/octet-stream')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(str(e).encode())
            return

        if parsed.path == '/exec':
            cmd = qs.get('cmd', [''])[0]
            if not cmd:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing 'cmd' parameter\n")
                return

            if active_cam is None:
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b"Camera not connected\n")
                return

            with cam_lock:
                output = execute_shell_on_camera(active_cam, cmd)

            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=latin1')
            self.end_headers()
            self.wfile.write(output.encode('latin1', errors='replace'))
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)

        if parsed.path == '/delete':
            remote_path = qs.get('path', [''])[0]
            if not remote_path or active_cam is None:
                self.send_response(400)
                self.end_headers()
                return
            with cam_lock:
                try:
                    active_cam.deleteFile(remote_path)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"DELETED\n")
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(str(e).encode())
            return

        if parsed.path == '/memory':
            base_str = qs.get('base', ['0'])[0]
            base = int(base_str, 0)
            if active_cam is None:
                self.send_response(503)
                self.end_headers()
                return
            with cam_lock:
                try:
                    active_cam.writeMemory(base, body)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"OK\n")
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(str(e).encode())
            return

        if parsed.path == '/file':
            remote_path = qs.get('path', [''])[0]
            if not remote_path or active_cam is None:
                self.send_response(400)
                self.end_headers()
                return
            with cam_lock:
                try:
                    active_cam.writeFile(remote_path, body)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"OK\n")
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(str(e).encode())
            return

        if parsed.path == '/exec':
            cmd = body.decode('latin1').strip()
            if not cmd:
                self.send_response(400)
                self.end_headers()
                return

            if active_cam is None:
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b"Camera not connected\n")
                return

            with cam_lock:
                output = execute_shell_on_camera(active_cam, cmd)

            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=latin1')
            self.end_headers()
            self.wfile.write(output.encode('latin1', errors='replace'))
            return

        if parsed.path == '/exit':
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Exiting session...\n")
            stop_event.set()
            return

        self.send_response(404)
        self.end_headers()

def keepalive_worker(cam):
    """Sends periodic keepalive packets so the camera Senser watchdog never times out"""
    while not stop_event.is_set():
        time.sleep(8)
        if stop_event.is_set():
            break
        try:
            with cam_lock:
                cam.readHasp()
        except Exception:
            pass

def start_http_server():
    server = http.server.ThreadingHTTPServer(('127.0.0.1', HTTP_PORT), UsbApiHandler)
    server.timeout = 0.5
    while not stop_event.is_set():
        server.handle_request()
    server.server_close()

def main():
    global active_cam
    print("=" * 65)
    print("=== SONY ILCE-6400 PERSISTENT USB CONTINUOUS SESSION BRIDGE ===")
    print("=" * 65)
    print("[*] Initializing libusb connection...")

    with importDriver('libusb') as driver:
        device = getDevice(driver)
        if not device:
            print("[-] No Sony USB device found in Mass Storage or Senser mode.")
            return

        # If camera is in Mass Storage mode, switch to Service Mode
        if isinstance(device, SonyMscExtCmdDevice):
            print("[+] Found camera in Mass Storage mode. Switching to Senser mode...")
            dev = SonySenserAuthDevice(device.driver)
            dev.start()
            dev.authenticate()

            print("[*] Waiting for camera to switch into Senser mode...")
            device = None
            for _ in range(20):
                time.sleep(0.5)
                try:
                    devs = list(listDevices(driver, True))
                    if len(devs) == 1 and isinstance(devs[0], SonySenserDevice):
                        device = devs[0]
                        break
                except Exception:
                    pass

            if not device:
                print("[-] Timed out waiting for Senser mode device.")
                return

        if not isinstance(device, SonySenserDevice):
            print(f"[-] Unsupported device mode: {type(device)}")
            return

        print("[+] Connecting and authenticating Senser session...")
        auth_dev = SonySenserAuthDevice(device.driver)
        auth_dev.start()
        auth_dev.authenticate()

        cam = SonySenserCamera(device)
        active_cam = cam

        # Start keepalive worker
        keepalive_thread = threading.Thread(target=keepalive_worker, args=(cam,), daemon=True)
        keepalive_thread.start()

        # Start background HTTP server
        http_thread = threading.Thread(target=start_http_server, daemon=True)
        http_thread.start()

        print("\n" + "=" * 65)
        print(f"[+] USB SESSION CONNECTED & LOCKED OPEN!")
        print(f"[+] Local HTTP API active at http://127.0.0.1:{HTTP_PORT}/exec")
        print(f"[*] Background tasks can run: py -3.12 tools/exec_usb.py \"<cmd>\"")
        print(f"[*] Type shell commands directly below (e.g. 'uname -a', 'ps', 'dmesg').")
        print(f"[*] Type 'exit' to cleanly exit service mode and return to Mass Storage.")
        print("=" * 65 + "\n")

        # Session Execution & Loop
        try:
            # Test initial command
            try:
                with cam_lock:
                    test_out = execute_shell_on_camera(cam, "uname -a", timeout=3.0)
                if "Linux" in test_out:
                    print(f"[+] Camera Root Shell Verified: {test_out.strip()}\n")
                else:
                    print("[!] usb_shell_daemon warming up...\n")
            except Exception as e:
                print(f"[!] Note on init check: {e}\n")

            # Interactive or Daemon wait loop
            is_interactive = sys.stdin and sys.stdin.isatty()
            if not is_interactive:
                print("[*] Running in background daemon mode (serving HTTP API).")
                print("[*] Waiting for commands via http://127.0.0.1:8088/exec...")
                try:
                    while not stop_event.is_set():
                        time.sleep(0.5)
                except (KeyboardInterrupt, SystemExit):
                    pass
            else:
                while not stop_event.is_set():
                    try:
                        cmd = input("sony-a6400 # ").strip()
                    except (EOFError, KeyboardInterrupt):
                        print("\n[*] Exiting session...")
                        break

                    if not cmd:
                        continue
                    if cmd in ['exit', 'quit']:
                        print("[*] Terminating persistent session...")
                        break

                    with cam_lock:
                        out = execute_shell_on_camera(cam, cmd)
                    sys.stdout.write(out)
                    if not out.endswith('\n'):
                        sys.stdout.write('\n')
        finally:
            stop_event.set()
            print("[*] Safely closing USB Senser session...")
            try:
                auth_dev.stop()
            except Exception:
                pass
            print("[+] Session closed. Camera returning to normal mode.")

if __name__ == '__main__':
    main()
