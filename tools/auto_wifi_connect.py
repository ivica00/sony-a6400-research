import socket
import sys
import time
import os

def check_ip(ip, port=2323):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.04)
    try:
        s.connect((ip, port))
        s.close()
        return True
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass

def scan_network():
    print("[*] ==========================================================")
    print("[*] SONY ILCE-6400 WI-FI ROOT SHELL AUTOCONNECT DAEMON")
    print("[*] Local Subnet: 192.168.100.0/24 | Target Port: 2323")
    print("[*] ==========================================================")
    print("[*] Ready. Unplug USB, then on camera select:")
    print("[*]   MENU -> Network -> 'Send to Computer' (ili 'Ctrl w/ Smartphone')")
    print("[*] Waiting for camera connection...\n")

    seen_ips = set()
    pass_cnt = 0
    while True:
        pass_cnt += 1
        found = None
        for i in range(2, 254):
            if i == 6:
                continue
            ip = f"192.168.100.{i}"
            if check_ip(ip, 2323):
                found = ip
                break

        if found:
            print(f"\n[***] ====================================================== [***]")
            print(f"[***] SONY ILCE-6400 CONNECTED AT {found}:2323! [***]")
            print(f"[***] LAUNCHING ROOT SHELL NOW...                            [***]")
            print(f"[***] ====================================================== [***]\n")
            from camera_shell import telnet_shell
            telnet_shell(found, 2323)
            return

        sys.stdout.write(f"\r[*] Scan pass {pass_cnt} (no camera yet)...")
        sys.stdout.flush()
        time.sleep(1)

if __name__ == '__main__':
    scan_network()
