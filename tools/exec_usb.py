import sys
import urllib.request
import urllib.error

def run_cmd(cmd_str):
    url = f"http://127.0.0.1:8088/exec"
    req = urllib.request.Request(url, data=cmd_str.encode('latin1'), method='POST')
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            output = resp.read().decode('latin1', errors='replace')
            sys.stdout.write(output)
            if not output.endswith('\n'):
                sys.stdout.write('\n')
            return 0
    except urllib.error.URLError:
        sys.stderr.write("[-] usb_session daemon is not running on http://127.0.0.1:8088\n")
        sys.stderr.write("[*] Please launch: py -3.12 tools/usb_session.py\n")
        return 1

if __name__ == '__main__':
    if len(sys.argv) > 1:
        cmd = " ".join(sys.argv[1:])
    else:
        cmd = "uname -a"
    sys.exit(run_cmd(cmd))
