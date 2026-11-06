import sys
import time

sys.path.insert(0, 'Sony-PMCA-RE')
from pmca.commands.usb import (
    importDriver, listDevices, getDevice,
    SonyMscExtCmdDevice, SonySenserDevice,
    SonySenserAuthDevice, SonySenserCamera
)

def inspect_tweaks(cam):
    print("\n" + "=" * 60)
    print("=== READING NATIVE SONY BACKUP REGISTERS ===")
    print("=" * 60)

    # 1. Video rec limit
    val_h = cam.readBackup(0x003c0373)
    val_m = cam.readBackup(0x003c0374)
    val_s = cam.readBackup(0x003c0375)
    print(f"recLimit (0x003c0373..75): {val_h.hex()}h {val_m.hex()}m {val_s.hex()}s")

    # 2. 4K rec limit
    try:
        val_4k = cam.readBackup(0x003c04b6)
        print(f"recLimit4k (0x003c04b6): {val_4k.hex()}")
    except Exception as e:
        print(f"recLimit4k: {e}")

    # 3. PAL/NTSC selector
    try:
        val_pn = cam.readBackup(0x01070148)
        print(f"palNtscSelector (0x01070148): {val_pn.hex()}")
    except Exception as e:
        print(f"palNtscSelector: {e}")

    # 4. Languages
    lang_vals = []
    for i in range(35):
        try:
            v = cam.readBackup(0x010d008f + i)
            lang_vals.append(v.hex())
        except Exception:
            break
    print(f"Languages (0x010d008f..+{len(lang_vals)}): {' '.join(lang_vals)}")
    print("=" * 60)

def main():
    with importDriver('libusb') as driver:
        device = getDevice(driver)
        if isinstance(device, SonyMscExtCmdDevice):
            print("[+] Switching to Senser mode...")
            dev = SonySenserAuthDevice(device.driver)
            dev.start(); dev.authenticate()
            time.sleep(1)
            device = list(listDevices(driver, True))[0]

        dev = SonySenserAuthDevice(device.driver)
        dev.start(); dev.authenticate()
        try:
            inspect_tweaks(SonySenserCamera(device))
        finally:
            dev.stop()

if __name__ == '__main__':
    main()
