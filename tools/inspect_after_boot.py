import sys
import io

sys.path.insert(0, 'Sony-PMCA-RE')
from pmca.commands.usb import senserShellCommand

def inspect_camera(cam):
    print("[+] Connected to camera in Senser mode!")

    files_to_check = [
        '/tmp/autoexec.log',
        '/tmp/gui.log',
        '/tmp/gui.pid',
        '/tmp/autoexec.lock',
        '/etc/ld.so.preload',
        '/tmp/autoexec.sh',
        '/tmp/modern_menu.elf',
        '/proc/uptime',
        '/proc/loadavg'
    ]

    for f in files_to_check:
        try:
            buf = io.BytesIO()
            cam.readFile(f, buf)
            content = buf.getvalue()
            if len(content) < 500:
                print(f"=== {f} ({len(content)} bytes) ===")
                print(content.decode('utf-8', errors='replace').strip())
            else:
                print(f"=== {f} ({len(content)} bytes) ===")
                print(content[:300].decode('utf-8', errors='replace').strip() + "\n... [truncated]")
        except Exception as e:
            print(f"=== {f} === [ERROR/NOT FOUND: {e}]")
    print("\n[+] Inspection completed.")

if __name__ == '__main__':
    senserShellCommand(driverName='libusb', complete=inspect_camera)
