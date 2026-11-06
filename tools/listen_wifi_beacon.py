import socket
import sys
import time

UDP_PORT = 2324
TCP_PORT = 2323

def listen_for_camera(timeout=60):
    print(f"[*] Listening for Sony ILCE-6400 Wi-Fi beacon on UDP port {UDP_PORT} (timeout {timeout}s)...")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    except Exception:
        pass

    try:
        s.bind(('', UDP_PORT))
    except Exception as e:
        print(f"[!] Cannot bind UDP port {UDP_PORT}: {e}")
        return None

    s.settimeout(timeout)
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            data, addr = s.recvfrom(1024)
            msg = data.decode('utf-8', errors='replace').strip()
            print(f"\n[***] ==================================================== [***]")
            print(f"[***] SONY ILCE-6400 DISCOVERED ON LOCAL WI-FI!           [***]")
            print(f"[***] Camera IP: {addr[0]} | Message: {msg}")
            print(f"[***] ==================================================== [***]")
            s.close()
            return addr[0]
        except socket.timeout:
            break
        except Exception as e:
            print(f"[!] Error: {e}")
            break

    s.close()
    print("[-] No camera beacon received within timeout.")
    return None

if __name__ == '__main__':
    t = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    ip = listen_for_camera(t)
    if ip:
        print(f"\n[+] To connect root shell, run: py -3.12 tools/camera_shell.py {ip}")
