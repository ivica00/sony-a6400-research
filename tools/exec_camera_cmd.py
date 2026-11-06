import sys
import io
import time

sys.path.insert(0, 'Sony-PMCA-RE')
from pmca.commands.usb import senserShellCommand

def exec_cmd(cmd_str):
    def run(cam):
        try:
            cam.deleteFile('/tmp/usb_done')
        except Exception:
            pass
        try:
            cam.deleteFile('/tmp/usb_out.txt')
        except Exception:
            pass

        cam.writeFile('/tmp/usb_cmd.txt', (cmd_str + "\n").encode('latin1'))

        for _ in range(50):
            time.sleep(0.06)
            try:
                buf = io.BytesIO()
                cam.readFile('/tmp/usb_done', buf)
                buf = io.BytesIO()
                cam.readFile('/tmp/usb_out.txt', buf)
                out = buf.getvalue().decode('latin1', errors='replace')
                print(out)
                return
            except Exception:
                pass
        print("[-] Command timed out.")

    senserShellCommand(driverName='libusb', complete=run)

if __name__ == '__main__':
    if len(sys.argv) > 1:
        cmd = " ".join(sys.argv[1:])
    else:
        cmd = "uname -a"
    exec_cmd(cmd)
