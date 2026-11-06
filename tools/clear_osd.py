import urllib.request
import time

OSD_A = 0x23a80000
OSD_B = 0x23b16000
OSD_SIZE = 640 * 480 * 2 # 614,400 bytes
CHUNK = 16384

def clear_buffer(base, name):
    print(f"[*] Clearing {name} (PA {hex(base)})...")
    zeros = b'\x00' * CHUNK
    offset = 0
    t0 = time.time()
    while offset < OSD_SIZE:
        sz = min(CHUNK, OSD_SIZE - offset)
        data = zeros[:sz]
        url = f"http://127.0.0.1:8088/memory?base={hex(base + offset)}"
        req = urllib.request.Request(url, data=data, method='POST')
        urllib.request.urlopen(req, timeout=5)
        offset += sz
    print(f"[+] {name} cleared to transparent in {time.time()-t0:.2f}s!")

def main():
    clear_buffer(OSD_A, "OSD Buffer A")
    clear_buffer(OSD_B, "OSD Buffer B")

if __name__ == '__main__':
    main()
