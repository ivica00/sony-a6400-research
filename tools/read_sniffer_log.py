import sys
import time

sys.path.insert(0, 'Sony-PMCA-RE')
from pmca.commands.usb import (
    importDriver, listDevices, getDevice,
    SonyMscExtCmdDevice, SonySenserDevice,
    SonySenserAuthDevice, SonySenserCamera
)

def read_log():
    print("[*] Waiting for Sony camera over USB...")
    with importDriver('libusb') as driver:
        device = None
        for _ in range(30):
            devs = list(listDevices(driver, True))
            if devs:
                device = devs[0]
                break
            time.sleep(0.5)

        if not device:
            print("[-] No Sony USB device found within 15 seconds.")
            return None

        if isinstance(device, SonyMscExtCmdDevice):
            print("[+] In Mass Storage. Switching to Senser mode...")
            dev = SonySenserAuthDevice(device.driver)
            dev.start(); dev.authenticate()

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
                print("[-] Failed to switch to Senser mode.")
                return None

        dev = SonySenserAuthDevice(device.driver)
        dev.start(); dev.authenticate()
        cam = SonySenserCamera(device)
        try:
            for path in ['/setting/input_dump.log', '/tmp/input_dump.log']:
                try:
                    data = cam.readFile(path)
                    if data:
                        print(f"[+] Found log at {path} ({len(data)} bytes)!")
                        return data.decode(errors='ignore')
                except Exception as e:
                    print(f"[-] {path}: {e}")
            return None
        finally:
            dev.stop()

if __name__ == '__main__':
    log = read_log()
    if log:
        print("\n" + "=" * 65)
        print("=== CAPTURED HARDWARE INPUT DUMP ===")
        print("=" * 65)
        print(log)
        print("=" * 65 + "\n")
