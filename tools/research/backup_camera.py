import os
import sys
import time
from project_paths import PROJECT_ROOT
from datetime import datetime

repo_path = str(PROJECT_ROOT / 'Sony-PMCA-RE')
if repo_path not in sys.path:
    sys.path.insert(0, repo_path)

from pmca.commands.usb import importDriver, getDevice, listDevices
from pmca.usb.sony import (
    SonyMscExtCmdDevice,
    SonySenserDevice,
    SonySenserAuthDevice,
    SonySenserCamera
)
from pmca.usb.driver.generic import GenericUsbDriver

def dump_backup(driver_name='libusb'):
    print("=" * 60)
    print("SONY a6400 (ILCE-6400) NVRAM / BACKUP.BIN DUMP TOOL")
    print("=" * 60)

    # Use libusb driver for direct service mode control
    with importDriver(driver_name) as driver:
        device = getDevice(driver)
        
        if not device:
            print("\n[-] Camera not found.")
            print("    Check:")
            print("    1. Is the camera powered on and connected via USB cable?")
            print("    2. Is USB Connection set to 'Mass Storage (MSC)'?")
            print("    3. If the camera is already in Service Mode, is the libusb-win32 / libusbK driver installed via Zadig?")
            return

        # Case 1: In Mass Storage mode
        if isinstance(device, SonyMscExtCmdDevice):
            print("\n[+] Camera detected in Mass Storage mode.")
            print("[*] Sending command to enter Service Mode...")
            auth = SonySenserAuthDevice(device.driver)
            auth.start()
            auth.authenticate()
            print("[*] Camera is resetting into Service Mode. Please wait a few seconds...")
            time.sleep(3)
            
            # Re-scan for device in service mode
            device = None
            for _ in range(10):
                time.sleep(1)
                devs = list(listDevices(driver, True))
                if devs and isinstance(devs[0], SonySenserDevice):
                    device = devs[0]
                    break
            
            if not device:
                print("\n[!] Camera entered Service Mode, but the OS is waiting for a driver!")
                print("    Open 'tools\\zadig.exe':")
                print("    - Options -> List All Devices")
                print("    - Select the camera from the list")
                print("    - Select 'libusb-win32' or 'libusbK' and click 'Install / Replace Driver'")
                print("    - Then run this script again.")
                return

        # Case 2: In Service Mode
        if isinstance(device, SonySenserDevice):
            print("\n[+] Camera successfully recognized in Service Mode!")
            print("[*] Authenticating with the camera service layer...")
            auth = SonySenserAuthDevice(device.driver)
            auth.start()
            auth.authenticate()
            
            try:
                senser_cam = SonySenserCamera(device)
                print("[*] Reading full Backup.bin (NVRAM settings)...")
                backup_data = senser_cam.getBackupPresetData(True)
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_dir = PROJECT_ROOT / "backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                filename = str(backup_dir / f"Backup_a6400_{timestamp}.bin")
                with open(filename, "wb") as f:
                    f.write(backup_data)
                
                print(f"\n[SUCCESS] Backup saved successfully!")
                print(f"          File: {os.path.abspath(filename)}")
                print(f"          Size: {len(backup_data)} bytes")
                
                # Check properties count
                from pmca.backup import BackupFile
                bf = BackupFile(open(filename, "rb"))
                props = list(bf.listProperties())
                print(f"          Number of NVRAM properties read: {len(props)}")
                print(f"          Backup revision: {bf.revision}")
                print(f"          Region: {bf.header.region.decode('latin1', 'ignore').strip(chr(0))}")
            finally:
                auth.stop()

if __name__ == '__main__':
    dump_backup(None if '--driver=default' in sys.argv else 'libusb')

