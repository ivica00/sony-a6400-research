import sys
import io

sys.path.insert(0, 'Sony-PMCA-RE')
from pmca.commands.usb import senserShellCommand

diag_script = b"""#!/bin/sh
export PATH=/usr/bin:/bin:/sbin:/usr/sbin:/tmp

OUT="/tmp/fb_diag.txt"
echo "=== FB DIAGNOSTIC ===" > "$OUT"
echo "Date: $(date)" >> "$OUT"

echo "=== /dev/fb* ===" >> "$OUT"
ls -la /dev/fb* >> "$OUT" 2>&1

echo "=== /proc/fb ===" >> "$OUT"
cat /proc/fb >> "$OUT" 2>&1

echo "=== /dev/dmp* ===" >> "$OUT"
ls -la /dev/dmp* >> "$OUT" 2>&1

echo "=== Testing modern_menu.elf info ===" >> "$OUT"
chmod 755 /tmp/modern_menu.elf
/tmp/modern_menu.elf --help >> "$OUT" 2>&1

echo "=== /proc/devices ===" >> "$OUT"
cat /proc/devices >> "$OUT" 2>&1

echo "=== Completed ===" >> "$OUT"
"""

def run_diag(cam):
    print("[+] Connected to camera in Senser mode!")

    # Write diag_script to /tmp/run_diag.sh
    print("[+] Writing /tmp/run_diag.sh...")
    cam.writeFile('/tmp/run_diag.sh', diag_script)

    # In /tmp/autoexec.sh, run /tmp/run_diag.sh
    autoexec_runner = b"""#!/bin/sh
export PATH=/usr/bin:/bin:/sbin:/usr/sbin:/tmp
/bin/sh /tmp/run_diag.sh
"""
    print("[+] Writing /tmp/autoexec.sh to execute diag...")
    cam.writeFile('/tmp/autoexec.sh', autoexec_runner)

    # Remove lock so it executes
    try:
        cam.deleteFile('/tmp/autoexec.lock')
    except Exception:
        pass

    print("[+] Configured to run diagnostic on next boot.")

if __name__ == '__main__':
    senserShellCommand(driverName='libusb', complete=run_diag)
