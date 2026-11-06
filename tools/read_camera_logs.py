import sys
sys.path.insert(0, 'Sony-PMCA-RE')
from pmca.commands.usb import senserShellCommand
import io

def dump_logs(cam):
    print("\n[+] CONNECTED TO CAMERA!")
    for log_name in ['/tmp/autoexec.log', '/tmp/wifi.log', '/tmp/gui.log', '/tmp/telnetd.log', '/tmp/input.log']:
        try:
            buf = io.BytesIO()
            cam.readFile(log_name, buf)
            content = buf.getvalue().decode('latin1', errors='replace')
            print(f"\n=== {log_name} ===")
            print(content if content.strip() else "(empty)")
        except Exception as e:
            print(f"\n=== {log_name} === (error reading: {e})")

if __name__ == '__main__':
    senserShellCommand(driverName='libusb', complete=dump_logs)
