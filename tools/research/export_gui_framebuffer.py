"""Analyze and extract GUI framebuffer / surfaces from emulator stream memory."""

import pickle
import zlib
from pathlib import Path
from PIL import Image


def inspect_and_export_surfaces(checkpoint_path: str, output_dir: str = 'artifacts/gui'):
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    with open(checkpoint_path, 'rb') as f:
        payload = pickle.load(f)

    stream_data = None
    stream_base = None
    for r in payload['regions']:
        b, e, sz = r['begin'], r['end'], r['size']
        if b == 0x53f50000 or (sz == 32 * 1024 * 1024 and 'stream' in str(r)):
            stream_data = zlib.decompress(r['data'])
            stream_base = b
            print(f'Found stream VRAM region at 0x{b:08x}-0x{e:08x} ({sz/1024/1024:.1f} MB)')
            break

    if not stream_data:
        print('Stream buffer not found in checkpoint!')
        return

    # Check non-zero pages
    print('Scanning non-zero regions in stream buffer...')
    pages = []
    for off in range(0, len(stream_data), 4096):
        chunk = stream_data[off:off+4096]
        if any(chunk):
            nz = sum(1 for b in chunk if b != 0)
            pages.append((off, nz))
            print(f'  +0x{off:06x}: {nz} non-zero bytes')

    # Try decoding possible framebuffers
    # Sony ILCE-6400 resolutions:
    # 1. 640 x 480 (VGA LCD)
    # 2. 800 x 480 (WVGA)
    # 3. 960 x 540 (qHD 16:9 LCD)
    # Formats: RGBA4444 (16-bit, 2 bpp), RGB565 (16-bit, 2 bpp), ARGB8888 (32-bit, 4 bpp)
    resolutions = [
        ('qhd', 960, 540),
        ('wvga', 800, 480),
        ('vga', 640, 480),
        ('small', 320, 240),
    ]

    # Look for candidate offsets where data starts
    candidate_offsets = [0, 0x1000, 0x8000, 0xe100, 0xee100, 0x100000]

    for name, w, h in resolutions:
        for bpp, mode in [(16, 'RGB'), (32, 'RGBA')]:
            stride = w * (bpp // 8)
            frame_len = stride * h
            for off in candidate_offsets:
                if off + frame_len <= len(stream_data):
                    sub = stream_data[off:off+frame_len]
                    nz = sum(1 for b in sub if b != 0)
                    if nz > 50:
                        try:
                            if bpp == 32:
                                img = Image.frombytes('RGBA', (w, h), sub, 'raw', 'BGRA')
                            else:
                                img = Image.frombytes('RGB', (w, h), sub, 'raw', 'BGR;16')
                            img_file = out_path / f'gui_{name}_{bpp}bpp_off0x{off:x}.png'
                            img.save(img_file)
                            print(f'Exported candidate image: {img_file} (nz={nz})')
                        except Exception as e:
                            pass


if __name__ == '__main__':
    inspect_and_export_surfaces('artifacts/checkpoints/boot-110m.ckpt')
