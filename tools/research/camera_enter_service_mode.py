"""Stage 1 only: switch a camera in mass-storage mode to Service Mode using the libusb driver.

Authorized by the user for this session. Performs no backup and installs no driver.
"""
import sys
import time

from project_paths import PROJECT_ROOT

repo_path = str(PROJECT_ROOT / 'Sony-PMCA-RE')
if repo_path not in sys.path:
    sys.path.insert(0, repo_path)

from pmca.commands.usb import importDriver, listDevices
from pmca.usb.sony import SonyMscExtCmdDevice, SonySenserAuthDevice


def main():
    with importDriver('libusb') as driver:
        devices = list(listDevices(driver))
        msc = [d for d in devices if isinstance(d, SonyMscExtCmdDevice)]
        if len(msc) != 1:
            print(f'Expected exactly one Sony MSC camera, found {len(msc)}; not sending anything.')
            return 2
        print('Sending Service Mode authentication (camera will re-enumerate).')
        auth = SonySenserAuthDevice(msc[0].driver)
        auth.start()
        auth.authenticate()
        time.sleep(3)
    print('Done. Camera should now enumerate as a different USB device.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

