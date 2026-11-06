import sys
import io

sys.path.insert(0, 'Sony-PMCA-RE')
from pmca.commands.usb import senserShellCommand

with open("devcrashday_a6400/probe_stream.elf", "rb") as f:
    elf_bytes = f.read()

def deploy_probe(cam):
    print("[+] Connected to camera in Senser mode!")

    # 1. Upload probe_stream.elf
    print(f"[+] Uploading /tmp/probe_stream.elf ({len(elf_bytes)} bytes)...")
    cam.writeFile('/tmp/probe_stream.elf', elf_bytes)

    # 2. Configure /tmp/autoexec.sh to execute probe
    autoexec_script = b"""#!/bin/sh
export PATH=/usr/bin:/bin:/sbin:/usr/sbin:/tmp
chmod 755 /tmp/probe_stream.elf
/tmp/probe_stream.elf
"""
    print("[+] Writing /tmp/autoexec.sh...")
    cam.writeFile('/tmp/autoexec.sh', autoexec_script)

    # 3. Clear lock
    try:
        cam.deleteFile('/tmp/autoexec.lock')
    except Exception:
        pass
    print("[+] Probe ready to run on next camera boot!")

if __name__ == '__main__':
    senserShellCommand(driverName='libusb', complete=deploy_probe)
