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
            print("\n[-] Kamera nije pronaÄ‘ena.")
            print("    Proveri:")
            print("    1. Da li je kamera ukljuÄŤena i povezana USB kablom?")
            print("    2. Da li je USB Connection postavljen na 'Mass Storage (MSC)'?")
            print("    3. Ako je kamera veÄ‡ u Service Mode-u, da li je Zadigom postavljen libusb-win32 / libusbK drajver?")
            return

        # Case 1: In Mass Storage mode
        if isinstance(device, SonyMscExtCmdDevice):
            print("\n[+] Detektovana kamera u Mass Storage modu.")
            print("[*] Slanje komande za prelazak u Service Mode...")
            auth = SonySenserAuthDevice(device.driver)
            auth.start()
            auth.authenticate()
            print("[*] Kamera se resetuje u Service Mode. SaÄŤekajte par sekundi...")
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
                print("\n[!] Kamera je preĹˇla u Service Mode, ali operativni sistem ÄŤeka drajver!")
                print("    Otvorite 'tools\\zadig.exe':")
                print("    - Options -> List All Devices")
                print("    - Izaberite kameru sa liste")
                print("    - Izaberite 'libusb-win32' ili 'libusbK' i kliknite 'Install / Replace Driver'")
                print("    - Nakon toga ponovo pokrenite ovu skriptu.")
                return

        # Case 2: In Service Mode
        if isinstance(device, SonySenserDevice):
            print("\n[+] Kamera je uspeĹˇno prepoznata u Service Mode-u!")
            print("[*] Autentifikacija sa servisnim slojem kamere...")
            auth = SonySenserAuthDevice(device.driver)
            auth.start()
            auth.authenticate()
            
            try:
                senser_cam = SonySenserCamera(device)
                print("[*] OÄŤitavanje kompletnog Backup.bin (NVRAM postavke)...")
                backup_data = senser_cam.getBackupPresetData(True)
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_dir = PROJECT_ROOT / "backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                filename = str(backup_dir / f"Backup_a6400_{timestamp}.bin")
                with open(filename, "wb") as f:
                    f.write(backup_data)
                
                print(f"\n[SUCCESS] Backup uspeĹˇno saÄŤuvan!")
                print(f"          Fajl: {os.path.abspath(filename)}")
                print(f"          VeliÄŤina: {len(backup_data)} bajtova")
                
                # Check properties count
                from pmca.backup import BackupFile
                bf = BackupFile(open(filename, "rb"))
                props = list(bf.listProperties())
                print(f"          Broj oÄŤitanih NVRAM svojstava (properties): {len(props)}")
                print(f"          Revizija backupa: {bf.revision}")
                print(f"          Regija: {bf.header.region.decode('latin1', 'ignore').strip(chr(0))}")
            finally:
                auth.stop()

if __name__ == '__main__':
    dump_backup(None if '--driver=default' in sys.argv else 'libusb')

