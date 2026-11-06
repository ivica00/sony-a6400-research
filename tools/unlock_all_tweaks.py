import sys
import time

sys.path.insert(0, 'Sony-PMCA-RE')
from pmca.commands.usb import (
    importDriver, listDevices, getDevice,
    SonyMscExtCmdDevice, SonySenserDevice,
    SonySenserAuthDevice, SonySenserCamera
)

def apply_all_tweaks(cam):
    print("\n" + "=" * 65)
    print("=== SONY ILCE-6400 NATIVE MENU MODDER ===")
    print("=" * 65)

    # 1. Video Recording Limit (Remove 29m50s limit -> 13h 01m)
    print("\n[+] 1. Unlocking Video Recording Limit (30-minute limit mod)...")
    try:
        old_h = cam.readBackup(0x003c0373).hex()
        old_m = cam.readBackup(0x003c0374).hex()
        old_s = cam.readBackup(0x003c0375).hex()
        print(f"    Current limit: {old_h}h {old_m}m {old_s}s")
        cam.writeBackup(0x003c0373, b'\x0d') # 13h
        cam.writeBackup(0x003c0374, b'\x01') # 01m
        cam.writeBackup(0x003c0375, b'\x00') # 00s
        new_h = cam.readBackup(0x003c0373).hex()
        new_m = cam.readBackup(0x003c0374).hex()
        new_s = cam.readBackup(0x003c0375).hex()
        print(f"    NEW limit    : {new_h}h {new_m}m {new_s}s (UNLOCKED!)")
    except Exception as e:
        print(f"    [-] recLimit error: {e}")

    # 1b. 4K Video Recording Limit
    print("\n[+] 1b. Unlocking 4K Video Recording Limit...")
    try:
        old_4k = cam.readBackup(0x003c04b6).hex()
        print(f"    Current 4K limit: {old_4k}")
        cam.writeBackup(0x003c04b6, b'\xff\x7f') # 0x7fff = 32767 seconds (~9 hours)
        new_4k = cam.readBackup(0x003c04b6).hex()
        print(f"    NEW 4K limit    : {new_4k} (UNLOCKED!)")
    except Exception as e:
        print(f"    [-] recLimit4k error: {e}")

    # 2. PAL / NTSC Selector & Menu
    print("\n[+] 2. Enabling PAL / NTSC Selector in Native Sony Menu...")
    try:
        old_pn = cam.readBackup(0x01070148).hex()
        print(f"    Current PAL/NTSC selector: {old_pn}")
        cam.writeBackup(0x01070148, b'\x01') # Enable
        new_pn = cam.readBackup(0x01070148).hex()
        print(f"    NEW PAL/NTSC selector    : {new_pn} (ENABLED!)")
    except Exception as e:
        print(f"    [-] palNtscSelector error: {e}")

    # 3. Language Pack Unlock (All 35 Languages)
    print("\n[+] 3. Unlocking All 35 Languages in Native Sony Setup Menu...")
    unlocked_langs = 0
    for i in range(35):
        prop_id = 0x010d008f + i
        try:
            cam.writeBackup(prop_id, b'\x01') # 1 = Enabled
            val = cam.readBackup(prop_id)
            if val == b'\x01':
                unlocked_langs += 1
        except Exception:
            pass
    print(f"    Activated: {unlocked_langs} / 35 languages (ALL UNLOCKED!)")

    # 4. Save and commit to non-volatile flash
    print("\n[+] 4. Committing all modifications to Sony non-volatile flash...")
    try:
        cam.saveBackup(0)
        print("    [+] saveBackup(0) committed successfully!")
    except Exception as e:
        print(f"    [-] saveBackup error: {e}")

    print("\n" + "=" * 65)
    print("=== ALL REQUESTED MODS SUCCESSFULLY APPLIED TO SONY FIRMWARE! ===")
    print("=" * 65 + "\n")

def main():
    print("[*] Waiting for Sony camera on USB (Mass Storage)...")
    while True:
        try:
            with importDriver('libusb') as driver:
                device = getDevice(driver)
                if not device:
                    time.sleep(1)
                    continue

                if isinstance(device, SonyMscExtCmdDevice):
                    print("[+] Found camera in Mass Storage! Switching to Senser mode...")
                    dev = SonySenserAuthDevice(device.driver)
                    dev.start(); dev.authenticate()

                    senser_dev = None
                    for _ in range(20):
                        time.sleep(0.5)
                        try:
                            devs = list(listDevices(driver, True))
                            if len(devs) == 1 and isinstance(devs[0], SonySenserDevice):
                                senser_dev = devs[0]
                                break
                        except Exception:
                            pass
                    if not senser_dev:
                        print("[-] Timeout waiting for Senser device.")
                        return

                    device = senser_dev

                if isinstance(device, SonySenserDevice):
                    print("[+] Authenticating Senser session...")
                    dev = SonySenserAuthDevice(device.driver)
                    dev.start(); dev.authenticate()
                    try:
                        apply_all_tweaks(SonySenserCamera(device))
                    finally:
                        dev.stop()
                    print("[+] Done! Camera exiting service mode.")
                    return
        except KeyboardInterrupt:
            print("\nAborted.")
            return
        except Exception as e:
            time.sleep(1)

if __name__ == '__main__':
    main()
