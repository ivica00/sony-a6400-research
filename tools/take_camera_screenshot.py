import urllib.request
import struct
import os
import sys
import time
from PIL import Image

OSD_A_PA = 0x23a80000
OSD_B_PA = 0x23b16000
OSD_WIDTH = 640
OSD_HEIGHT = 480
OSD_SIZE = OSD_WIDTH * OSD_HEIGHT * 2 # 614,400 bytes

CHUNK_SIZE = 16384

def fetch_memory_chunked(base, total_size):
    data = bytearray()
    offset = 0
    while offset < total_size:
        sz = min(CHUNK_SIZE, total_size - offset)
        url = f"http://127.0.0.1:8088/memory?base={hex(base + offset)}&size={sz}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            chunk = resp.read()
            data.extend(chunk)
            offset += len(chunk)
    return bytes(data)

def decode_rgba4444(raw_bytes, width, height):
    img = Image.new("RGBA", (width, height))
    pixels = img.load()
    num_pixels = width * height
    words = struct.unpack(f"<{num_pixels}H", raw_bytes[:num_pixels * 2])
    idx = 0
    non_zero = 0
    for y in range(height):
        for x in range(width):
            val = words[idx]
            idx += 1
            if val != 0:
                non_zero += 1
            # Sony RGBA4444: R: 15..12, G: 11..8, B: 7..4, A: 3..0
            r = ((val >> 12) & 0xF) * 17
            g = ((val >> 8) & 0xF) * 17
            b = ((val >> 4) & 0xF) * 17
            a = (val & 0xF) * 17
            pixels[x, y] = (r, g, b, a)
    return img, non_zero

def main():
    os.makedirs("artifacts/gui", exist_ok=True)

    print("[*] Reading live OSD Buffer A from camera (640x480 RGBA4444)...")
    t0 = time.time()
    raw_a = fetch_memory_chunked(OSD_A_PA, OSD_SIZE)
    img_a, nz_a = decode_rgba4444(raw_a, OSD_WIDTH, OSD_HEIGHT)
    out_a = "artifacts/gui/camera_live_osd_a.png"
    img_a.save(out_a)
    print(f"[+] OSD Buffer A saved to {out_a} in {time.time()-t0:.2f}s ({nz_a} non-zero pixels)")

    print("[*] Reading live OSD Buffer B from camera (640x480 RGBA4444)...")
    t0 = time.time()
    raw_b = fetch_memory_chunked(OSD_B_PA, OSD_SIZE)
    img_b, nz_b = decode_rgba4444(raw_b, OSD_WIDTH, OSD_HEIGHT)
    out_b = "artifacts/gui/camera_live_osd_b.png"
    img_b.save(out_b)
    print(f"[+] OSD Buffer B saved to {out_b} in {time.time()-t0:.2f}s ({nz_b} non-zero pixels)")

if __name__ == '__main__':
    main()
