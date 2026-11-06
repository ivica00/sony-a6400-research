import sys
import io
sys.path.insert(0, 'Sony-PMCA-RE')
from pmca.commands.usb import senserShellCommand

def test_conn(cam):
    print("[+] Successfully connected to Sony ILCE-6400 in Senser mode!")

    # Write a test file
    test_data = b"Sony ILCE-6400 Modern Menu System Online - Test Verification\n"
    print("[+] Writing /tmp/modern_menu_test.txt...")
    cam.writeFile('/tmp/modern_menu_test.txt', test_data)
    print("[+] Successfully written!")

    # Read it back to verify
    buf = io.BytesIO()
    cam.readFile('/tmp/modern_menu_test.txt', buf)
    res = buf.getvalue()
    print("[+] Read back verified:", res.decode('utf-8', errors='ignore').strip())
    assert res == test_data, "Data mismatch!"
    print("[***] CAMERA USB COMMUNICATION FULLY VERIFIED! [***]")

if __name__ == '__main__':
    senserShellCommand(driverName='libusb', complete=test_conn)
