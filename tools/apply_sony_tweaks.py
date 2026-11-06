import sys
import time

sys.path.insert(0, 'Sony-PMCA-RE')
from pmca.commands.usb import (
    importDriver, listDevices, getDevice,
    SonyMscExtCmdDevice, SonySenserDevice,
    SonySenserAuthDevice, SonySenserCamera
)
from pmca.platform.backend.senser import SenserPlatformBackend
from pmca.platform.tweaks import TweakInterface

def run_tweaks(cam):
    print("\n" + "=" * 65)
    print("=== SONY ILCE-6400 NATIVE MENU MOD ENGINE ===")
    print("=" * 65)

    backend = SenserPlatformBackend(cam)
    backend.start()

    tweak_mgr = TweakInterface(backend)
    if not tweak_mgr.backupPatch:
        print("[-] Backup patch interface could not be initialized.")
        return

    print("\n[1] Checking current status of camera tweaks:")
    for name, desc, enabled, val in tweak_mgr.getTweaks():
        status = "ENABLED" if enabled else "DISABLED"
        print(f"  - {name:<18} [{status:<8}] ({val}) : {desc}")

    # Desired tweaks
    targets = ['recLimit', 'recLimit4k', 'language', 'palNtscSelector']
    print("\n[2] Activating requested native mods:")
    for t in targets:
        if tweak_mgr.available(t):
            print(f"  -> Enabling '{t}'...")
            tweak_mgr.setEnabled(t, True)
        else:
            print(f"  [!] Tweak '{t}' is not available on this model/region.")

    print("\n[3] Applying and syncing backup modifications to flash...")
    tweak_mgr.apply()
    print("[+] Modifications written and protected successfully!")

    print("\n[4] Verifying new status of camera tweaks:")
    # Re-read
    tweak_mgr_verify = TweakInterface(backend)
    for name, desc, enabled, val in tweak_mgr_verify.getTweaks():
        status = "ENABLED" if enabled else "DISABLED"
        print(f"  - {name:<18} [{status:<8}] ({val}) : {desc}")

    print("\n" + "=" * 65)
    print("[+] All requested native Sony menu mods applied permanently!")
    print("=" * 65 + "\n")

def main():
    print("[*] Connecting to Sony camera over USB...")
    with importDriver('libusb') as driver:
        device = getDevice(driver)
        if not device:
            print("[-] No Sony USB device found.")
            return

        if isinstance(device, SonyMscExtCmdDevice):
            print("[+] Camera in Mass Storage. Switching to Senser mode...")
            dev = SonySenserAuthDevice(device.driver)
            dev.start()
            dev.authenticate()

            device = None
            for _ in range(20):
                time.sleep(0.5)
                try:
                    devs = list(listDevices(driver, True))
                    if len(devs) == 1 and isinstance(devs[0], SonySenserDevice):
                        device = devs[0]
                        break
                except Exception:
                    pass

            if not device:
                print("[-] Timed out waiting for Senser mode.")
                return

        if isinstance(device, SonySenserDevice):
            print("[+] Camera in Senser mode. Authenticating...")
            dev = SonySenserAuthDevice(device.driver)
            dev.start()
            dev.authenticate()
            try:
                run_tweaks(SonySenserCamera(device))
            finally:
                dev.stop()

if __name__ == '__main__':
    main()
