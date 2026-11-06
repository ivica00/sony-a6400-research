import sys
import urllib.request
import urllib.error

def main():
    print("=" * 60)
    print("=== SONY ILCE-6400 USB INTERACTIVE SHELL ===")
    print("=" * 60)
    print("[*] Connected via local USB session bridge (http://127.0.0.1:8088)")
    print("[*] Type commands directly. Type 'exit' to quit this shell.")
    print("=" * 60 + "\n")

    # Check connection
    try:
        with urllib.request.urlopen("http://127.0.0.1:8088/ping", timeout=2) as r:
            pass
    except Exception:
        print("[-] USB session bridge is not running.")
        print("[*] Starting bridge or check background task...")
        return 1

    while True:
        try:
            cmd = input("sony-a6400 # ").strip()
            if not cmd:
                continue
            if cmd in ['exit', 'quit']:
                break

            req = urllib.request.Request("http://127.0.0.1:8088/exec", data=cmd.encode('latin1'), method='POST')
            with urllib.request.urlopen(req, timeout=15) as resp:
                out = resp.read().decode('latin1', errors='replace')
                sys.stdout.write(out)
                if not out.endswith('\n'):
                    sys.stdout.write('\n')
        except (KeyboardInterrupt, EOFError):
            print("\n[*] Exiting shell...")
            break
        except Exception as e:
            print(f"[!] Error: {e}")

if __name__ == '__main__':
    main()
