import hashlib
import io
import sys

sys.path.insert(0, 'Sony-PMCA-RE')
from pmca.commands.usb import senserShellCommand

with open("devcrashday_a6400/gui/modern_menu.elf", "rb") as f:
    elf_data = f.read()

with open("devcrashday_a6400/hook/autoexec_hook.so", "rb") as f:
    hook_data = f.read()

autoexec_sh = b"""#!/bin/sh
export PATH=/usr/bin:/bin:/sbin:/usr/sbin:/tmp

# 1. Mount SD card if available
mount -t vfat /dev/mmca1 /mnt 2>/dev/null || mount /dev/mmca1 /mnt 2>/dev/null

# 2. Killswitch check
if [ -f /mnt/disable_hook ] || [ -f /mnt/disable.txt ] || [ -f /tmp/disable_hook ]; then
    echo "[!] Killswitch active. Autoexec aborted." > /tmp/autoexec.log
    exit 0
fi

# 3. Ensure modern_menu.elf is executable
chmod 755 /tmp/modern_menu.elf 2>/dev/null
chmod 755 /mnt/modern_menu.elf 2>/dev/null

# 4. Launch modern_menu.elf in background daemon mode (starts hidden, toggled by C1)
if ! pidof modern_menu.elf >/dev/null 2>&1; then
    /tmp/modern_menu.elf &
    echo "[+] modern_menu.elf launched in daemon mode (PID: $!)" > /tmp/autoexec.log
fi
"""

def arm(cam):
    print("[+] Connected to Sony ILCE-6400 in Senser service mode!")

    # 1. Write binaries and scripts to flash
    print(f"[+] Writing /tmp/modern_menu.elf ({len(elf_data)} bytes)...")
    cam.writeFile('/tmp/modern_menu.elf', elf_data)

    print(f"[+] Writing /mnt/modern_menu.elf ({len(elf_data)} bytes)...")
    try:
        cam.writeFile('/mnt/modern_menu.elf', elf_data)
    except Exception as e:
        print("[-] /mnt write:", e)

    print(f"[+] Writing /tmp/autoexec_hook.so ({len(hook_data)} bytes)...")
    cam.writeFile('/tmp/autoexec_hook.so', hook_data)

    print("[+] Writing /tmp/autoexec.sh...")
    cam.writeFile('/tmp/autoexec.sh', autoexec_sh)

    # 2. Clear old locks and killswitches
    print("[+] Clearing locks and killswitch...")
    for k in ['/mnt/disable_hook', '/mnt/disable.txt', '/tmp/disable_hook', '/tmp/autoexec.lock']:
        try:
            cam.deleteFile(k)
            print(f"[+] Removed {k}")
        except Exception:
            pass

    # 3. Arm ld.so.preload
    print("[+] Setting /etc/ld.so.preload -> /tmp/autoexec_hook.so...")
    cam.writeFile('/etc/ld.so.preload', b'/tmp/autoexec_hook.so\n')

    print("\n[***] ==================================================== [***]")
    print("[***] MODERN 5-HUB TOUCH MENU IS NOW FULLY ARMED ON CAMERA [***]")
    print("[***] ==================================================== [***]")
    print("[*] Behavior:")
    print("    1. On camera power-on, camera boots normally into live sensor view.")
    print("    2. modern_menu runs silently in background (0% screen load).")
    print("    3. Press 'C1' button anytime to show the Modern 5-Hub Menu.")
    print("    4. Wheel switches Hubs; D-pad navigates; Center confirms.")
    print("    5. Press 'C1' or 'MENU' to hide the menu and restore live view.")

if __name__ == '__main__':
    senserShellCommand(driverName='libusb', complete=arm)
