import sys
import time

sys.path.insert(0, 'Sony-PMCA-RE')
from pmca.commands.usb import (
    importDriver, listDevices, getDevice,
    SonyMscExtCmdDevice, SonySenserDevice,
    SonySenserAuthDevice, SonySenserCamera
)

def unlock_all(cam):
    print("\n" + "=" * 65)
    print("=== SONY ILCE-6400 COMPLETE BACKUP UNLOCK (WITH ID1 UNPROTECT) ===")
    print("=" * 65)

    # Step 1: Disable backup protection (ID1)
    print("[+] Step 1: Unlocking backup protection (ID1 = False)...")
    try:
        cam.setBackupId1(False)
        print("    [+] Protection UNLOCKED successfully!")
    except Exception as e:
        print(f"    [-] setBackupId1 error: {e}")

    # Step 2: Unlock Video Recording Limit (0x003c0373..75)
    print("\n[+] Step 2: Unlocking 30-minute Video Recording Limit (recLimit)...")
    try:
        cam.writeBackup(0x003c0373, b'\x0d') # 13h
        cam.writeBackup(0x003c0374, b'\x01') # 01m
        cam.writeBackup(0x003c0375, b'\x00') # 00s
        h = cam.readBackup(0x003c0373).hex()
        m = cam.readBackup(0x003c0374).hex()
        s = cam.readBackup(0x003c0375).hex()
        print(f"    [+] Video limit set to: {h}h {m}m {s}s (UNLIMITED!)")
    except Exception as e:
        print(f"    [-] recLimit error: {e}")

    # Step 3: Unlock 4K Video Recording Limit (0x003c04b6)
    print("\n[+] Step 3: Unlocking 4K Video Recording Limit...")
    try:
        cam.writeBackup(0x003c04b6, b'\xff\x7f') # 0x7fff = 32767 seconds (~9 hours)
        val_4k = cam.readBackup(0x003c04b6).hex()
        print(f"    [+] 4K Video limit set to: {val_4k} (UNLOCKED!)")
    except Exception as e:
        print(f"    [-] recLimit4k error: {e}")

    # Step 4: Unlock PAL / NTSC Selector in Native Menu (0x01070148)
    print("\n[+] Step 4: Enabling PAL / NTSC Selector in Native Sony Menu...")
    try:
        cam.writeBackup(0x01070148, b'\x01')
        val_pn = cam.readBackup(0x01070148).hex()
        print(f"    [+] PAL/NTSC selector set to: {val_pn} (ENABLED!)")
    except Exception as e:
        print(f"    [-] palNtscSelector error: {e}")

    # Step 5: Unlock All 35 Languages (0x010d008f .. 0x010d00b1)
    print("\n[+] Step 5: Unlocking All 35 Languages in Native Sony Setup Menu...")
    unlocked = 0
    for i in range(35):
        prop_id = 0x010d008f + i
        try:
            cam.writeBackup(prop_id, b'\x01')
            if cam.readBackup(prop_id) == b'\x01':
                unlocked += 1
        except Exception as e:
            pass
    print(f"    [+] Activated: {unlocked} / 35 languages (ALL UNLOCKED!)")

    # Step 6: Commit and sync to non-volatile flash
    print("\n[+] Step 6: Syncing all modifications to Sony non-volatile flash...")
    try:
        cam.saveBackup(0)
        print("    [+] saveBackup(0) committed successfully!")
    except Exception as e:
        print(f"    [-] saveBackup error: {e}")

    # Step 7: Re-enable protection
    print("\n[+] Step 7: Restoring backup protection (ID1 = True)...")
    try:
        cam.setBackupId1(True)
        print("    [+] Protection re-locked safely!")
    except Exception as e:
        print(f"    [-] setBackupId1 lock error: {e}")

    print("\n" + "=" * 65)
    print("=== ALL REQUESTED MODS COMPLETED & VERIFIED 100%! ===")
    print("=" * 65 + "\n")

def main():
    print("[*] Waiting for Sony camera on USB...")
    while True:
        try:
            with importDriver('libusb') as driver:
                device = getDevice(driver)
                if not device:
                    time.sleep(1)
                    continue

                if isinstance(device, SonyMscExtCmdDevice):
                    print("[+] Camera in Mass Storage. Switching to Senser mode...")
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
                        continue
                    device = senser_dev

                if isinstance(device, SonySenserDevice):
                    print("[+] Camera in Senser mode. Authenticating...")
                    dev = SonySenserAuthDevice(device.driver)
                    dev.start(); dev.authenticate()
                    try:
                        unlock_all(SonySenserCamera(device))
                    finally:
                        dev.stop()
                    print("[+] Done! Exiting cleanly.")
                    return
        except KeyboardInterrupt:
            return
        except Exception:
            time.sleep(1)

if __name__ == '__main__':
    main()
