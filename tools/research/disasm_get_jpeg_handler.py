import subprocess

with open('artifacts/hardware/av-cam-camera-original.bin', 'rb') as f:
    data = f.read()

base_addr = 0x635c6000
start_addr = 0x63a91a3c
offset = start_addr - base_addr
slice_b = data[offset:offset+240]
with open('artifacts/analysis/get_jpeg_handler.bin', 'wb') as sf:
    sf.write(slice_b)

cmd = f"arm-linux-gnueabi-objdump -b binary -m arm -M force-thumb --adjust-vma={hex(start_addr)} -D artifacts/analysis/get_jpeg_handler.bin"
res = subprocess.run(["wsl", "bash", "-c", cmd], capture_output=True, text=True)
print(res.stdout)
