import subprocess

with open('artifacts/hardware/av-cam-camera-original.bin', 'rb') as f:
    data = f.read()

base_addr = 0x635c6000

for target in [0x63d95100, 0x63d9526e, 0x63d95254, 0x63d95238]:
    offset = target - base_addr
    slice_b = data[offset:offset+32]
    with open('artifacts/analysis/pred_slice.bin', 'wb') as sf:
        sf.write(slice_b)
    cmd = f"arm-linux-gnueabi-objdump -b binary -m arm -M force-thumb --adjust-vma={hex(target)} -D artifacts/analysis/pred_slice.bin"
    res = subprocess.run(["wsl", "bash", "-c", cmd], capture_output=True, text=True)
    print(f"=== Target {hex(target)} ===")
    for l in res.stdout.splitlines()[7:]:
        print(l)
