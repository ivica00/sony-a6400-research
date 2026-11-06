import socket
import sys
import threading

def telnet_shell(ip, port=2323):
    print(f"[*] Connecting to Sony ILCE-6400 root shell at {ip}:{port}...")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect((ip, port))
        print("[+] CONNECTED! Type commands below (Ctrl+C to exit):\n")
    except Exception as e:
        print(f"[!] Connection failed: {e}")
        return

    def receive():
        while True:
            try:
                data = s.recv(4096)
                if not data:
                    print("\n[!] Connection closed by camera.")
                    break
                sys.stdout.write(data.decode('utf-8', errors='replace'))
                sys.stdout.flush()
            except Exception:
                break

    t = threading.Thread(target=receive, daemon=True)
    t.start()

    try:
        while True:
            cmd = input()
            s.sendall((cmd + "\n").encode('utf-8'))
    except (KeyboardInterrupt, EOFError):
        print("\n[*] Disconnecting...")
    finally:
        s.close()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: py -3.12 tools/camera_shell.py <camera_ip>")
        sys.exit(1)
    telnet_shell(sys.argv[1])
