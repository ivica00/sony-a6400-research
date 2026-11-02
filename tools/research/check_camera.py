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
    print("\n[1] Provera svih priključenih USB uređaja preko libusb:")
    sony_found = False
    try:
        devices = list(usb.core.find(find_all=True))
        for dev in devices:
            # Sony Vendor ID is 0x054c
            is_sony = (dev.idVendor == 0x054c)
            prefix = "--> [SONY UREĐAJ]" if is_sony else "   "
            if is_sony:
                sony_found = True
                print(f"{prefix} Vendor: 0x{dev.idVendor:04x}, Product: 0x{dev.idProduct:04x} (Bus {dev.bus}, Dev {dev.address})")
        if not sony_found:
            print("   Nijedan Sony USB uređaj (VID: 0x054c) trenutno nije detektovan.")
    except Exception as e:
        print(f"   Greška pri skeniranju: {e}")

    # 2. PMCA Driver Scan
    print("\n[2] Provera PMCA drajvera (Windows / libusb):")
    for driver_name in [None, 'libusb']:
        name_str = "Default Windows Drajveri" if driver_name is None else "libusb Drajver"
        print(f"\n--- Testiranje sa: {name_str} ---")
        try:
            with importDriver(driver_name) as driver:
                devs = list(listDevices(driver))
                if devs:
                    for d in devs:
                        print(f"   [Pronađen uređaj]: {type(d).__name__}")
                        if isinstance(d, SonyMscExtCmdDevice):
                            print("   --> Kamera je u Mass Storage modu (MSC). Spremna za prelazak u Service Mode.")
                        elif isinstance(d, SonySenserDevice):
                            print("   --> Kamera je već u Service Mode-u (Scalar/Senser).")
                else:
                    print("   Nema prepoznate Sony kamere kroz ovaj drajver.")
        except Exception as e:
            print(f"   Status: {e}")

if __name__ == '__main__':
    scan()
