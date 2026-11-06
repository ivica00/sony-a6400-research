import sys
import io
sys.path.insert(0, 'Sony-PMCA-RE')
from pmca.commands.usb import senserShellCommand

def test_mnt(cam):
    print("[+] Connected to Senser!")
    try:
        # Try reading /mnt/disable_hook
        buf = io.BytesIO()
        cam.readFile('/mnt/disable_hook', buf)
        print("[+] /mnt/disable_hook exists on camera SD card! Content:", repr(buf.getvalue()))
    except Exception as e:
        print("[-] /mnt/disable_hook read error:", e)

    try:
        # Check /tmp
        buf = io.BytesIO()
        cam.readFile('/tmp/autoexec.log', buf)
        print("[+] /tmp/autoexec.log:", buf.getvalue().decode('utf-8', errors='ignore'))
    except Exception as e:
        print("[-] /tmp/autoexec.log read error:", e)

if __name__ == '__main__':
    senserShellCommand(driverName='libusb', complete=test_mnt)
