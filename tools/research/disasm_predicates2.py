import subprocess

with open('artifacts/hardware/av-cam-camera-original.bin', 'rb') as f:
    data = f.read()

base_addr = 0x635c6000

for target in [0x63d95288, 0x63d952a2, 0x63d952d8, 0x63d952f2, 0x63d952be]:
    offset = target - base_addr
    slice_b = data[offset:offset+32]
    with open('artifacts/analysis/pred_slice2.bin', 'wb') as sf:
        sf.write(slice_b)
    cmd = f"arm-linux-gnueabi-objdump -b binary -m arm -M force-thumb --adjust-vma={hex(target)} -D artifacts/analysis/pred_slice2.bin"
    res = subprocess.run(["wsl", "bash", "-c", cmd], capture_output=True, text=True)
    print(f"=== Target {hex(target)} ===")
    for l in res.stdout.splitlines()[7:]:
        print(l)
