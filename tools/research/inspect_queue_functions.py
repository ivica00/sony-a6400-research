import subprocess

with open('artifacts/hardware/av-cam-camera-original.bin', 'rb') as f:
    data = f.read()

base_addr = 0x635c6000

# Let's inspect the code around 0x63a9457c and see what function uses 0x01670464
for addr in [0x63a8c4a0, 0x63a9457c, 0x63a94830, 0x63a95e90, 0x63a97534]:
    offset = addr - base_addr - 64
    slice_b = data[offset:offset+128]
    with open('artifacts/analysis/func_slice.bin', 'wb') as sf:
        sf.write(slice_b)
    cmd = f"arm-linux-gnueabi-objdump -b binary -m arm -M force-thumb --adjust-vma={hex(addr-64)} -D artifacts/analysis/func_slice.bin"
    res = subprocess.run(["wsl", "bash", "-c", cmd], capture_output=True, text=True)
    print(f"=== Code around {hex(addr)} ===")
    lines = res.stdout.splitlines()
    for l in lines[7:35]:
        print(l)
