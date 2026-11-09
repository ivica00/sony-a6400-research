import subprocess

with open('artifacts/hardware/av-cam-camera-original.bin', 'rb') as f:
    data = f.read()

base_addr = 0x635c6000

for target in [0x63a8ed2c, 0x63a8f1e6, 0x63a8fac6]:
    start = target - 32
    offset = start - base_addr
    slice_b = data[offset:offset+128]
    with open('artifacts/analysis/slice_8120.bin', 'wb') as sf:
        sf.write(slice_b)
    cmd = f"arm-linux-gnueabi-objdump -b binary -m arm -M force-thumb --adjust-vma={hex(start)} -D artifacts/analysis/slice_8120.bin"
    res = subprocess.run(["wsl", "bash", "-c", cmd], capture_output=True, text=True)
    print(f"=== Disasm around {hex(target)} ===")
    for l in res.stdout.splitlines()[7:30]:
        print(l)
