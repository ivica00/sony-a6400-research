import sys
import io
import time

sys.path.insert(0, 'Sony-PMCA-RE')
from pmca.commands.usb import senserShellCommand

def run_usb_terminal(cam):
    print("\n" + "=" * 60)
    print("=== SONY ILCE-6400 DIRECT USB ROOT TERMINAL ===")
    print("=" * 60)
    print("[+] Connected to camera over USB Senser interface!")
    print("[*] Interactive root shell ready. Type commands (e.g. 'uname -a', 'ps', 'dmesg').")
    print("[*] Type 'exit' or Ctrl+C to disconnect.\n")

    # Clean stale command files
    for f in ['/tmp/usb_cmd.txt', '/tmp/usb_cmd.run', '/tmp/usb_done', '/tmp/usb_out.txt']:
        try:
            cam.deleteFile(f)
        except Exception:
            pass

    # Ensure daemon is armed
    test_cmd = b"uname -a\n"
    cam.writeFile('/tmp/usb_cmd.txt', test_cmd)

    # Wait for daemon
    daemon_running = False
    for _ in range(20):
        time.sleep(0.05)
        try:
            buf = io.BytesIO()
            cam.readFile('/tmp/usb_done', buf)
            daemon_running = True
            break
        except Exception:
            pass

    if daemon_running:
        buf = io.BytesIO()
        cam.readFile('/tmp/usb_out.txt', buf)
        out = buf.getvalue().decode('latin1', errors='replace')
        print(f"[+] Camera kernel: {out.strip()}")
    else:
        print("[!] Note: usb_shell_daemon not running in background yet.")
        print("[*] Please reboot camera or ensure autoexec.sh is active.")

    while True:
        try:
            cmd = input("sony-a6400 # ").strip()
            if not cmd:
                continue
            if cmd in ['exit', 'quit']:
                print("[*] Exiting terminal...")
                break

            # Clean previous done flag and output
            try:
                cam.deleteFile('/tmp/usb_done')
            except Exception:
                pass
            try:
                cam.deleteFile('/tmp/usb_out.txt')
            except Exception:
                pass

            # Write command
            cam.writeFile('/tmp/usb_cmd.txt', (cmd + "\n").encode('latin1'))

            # Poll for completion (up to 10 seconds for long commands)
            completed = False
            for _ in range(200):
                time.sleep(0.05)
                try:
                    buf = io.BytesIO()
                    cam.readFile('/tmp/usb_done', buf)
                    completed = True
                    break
                except Exception:
                    pass

            if completed:
                try:
                    buf = io.BytesIO()
                    cam.readFile('/tmp/usb_out.txt', buf)
                    output = buf.getvalue().decode('latin1', errors='replace')
                    if output:
                        sys.stdout.write(output)
                        if not output.endswith('\n'):
                            sys.stdout.write('\n')
                except Exception as e:
                    print(f"[!] Error reading output: {e}")
            else:
                print("[-] Command timed out (no response from usb_shell_daemon).")

        except (KeyboardInterrupt, EOFError):
            print("\n[*] Exiting terminal...")
            break

if __name__ == '__main__':
    senserShellCommand(driverName='libusb', complete=run_usb_terminal)
