import os
import sys
import time
from project_paths import PROJECT_ROOT

# Ensure venv packages and Sony-PMCA-RE are imported
repo_path = str(PROJECT_ROOT / 'Sony-PMCA-RE')
if repo_path not in sys.path:
    sys.path.insert(0, repo_path)

import usb.core
from pmca.commands.usb import listDevices, importDriver
from pmca.usb.sony import SonyMscExtCmdDevice, SonySenserDevice

def scan():
    print("=" * 50)
    print("SONY a6400 USB DETECTION & DIAGNOSTIC TOOL")
    print("=" * 50)
    
    # 1. Raw USB Scan
    print("\n[1] Checking all connected USB devices via libusb:")
    sony_found = False
    try:
        devices = list(usb.core.find(find_all=True))
        for dev in devices:
            # Sony Vendor ID is 0x054c
            is_sony = (dev.idVendor == 0x054c)
            prefix = "--> [SONY DEVICE]" if is_sony else "   "
            if is_sony:
                sony_found = True
                print(f"{prefix} Vendor: 0x{dev.idVendor:04x}, Product: 0x{dev.idProduct:04x} (Bus {dev.bus}, Dev {dev.address})")
        if not sony_found:
            print("   No Sony USB device (VID: 0x054c) currently detected.")
    except Exception as e:
        print(f"   Scan error: {e}")

    # 2. PMCA Driver Scan
    print("\n[2] Checking PMCA driver (Windows / libusb):")
    for driver_name in [None, 'libusb']:
        name_str = "Default Windows Drivers" if driver_name is None else "libusb Driver"
        print(f"\n--- Testing with: {name_str} ---")
        try:
            with importDriver(driver_name) as driver:
                devs = list(listDevices(driver))
                if devs:
                    for d in devs:
                        print(f"   [Device found]: {type(d).__name__}")
                        if isinstance(d, SonyMscExtCmdDevice):
                            print("   --> Camera is in Mass Storage mode (MSC). Ready to switch to Service Mode.")
                        elif isinstance(d, SonySenserDevice):
                            print("   --> Camera is already in Service Mode (Scalar/Senser).")
                else:
                    print("   No Sony camera recognized through this driver.")
        except Exception as e:
            print(f"   Status: {e}")

if __name__ == '__main__':
    scan()
