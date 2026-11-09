import subprocess

with open('artifacts/hardware/av-cam-camera-original.bin', 'rb') as f:
    data = f.read()

base_addr = 0x635c6000
start = 0x63a8fc20
offset = start - base_addr
slice_b = data[offset:offset+120]
with open('artifacts/analysis/slice_fsm.bin', 'wb') as sf:
    sf.write(slice_b)

cmd = f"arm-linux-gnueabi-objdump -b binary -m arm -M force-thumb --adjust-vma={hex(start)} -D artifacts/analysis/slice_fsm.bin"
res = subprocess.run(["wsl", "bash", "-c", cmd], capture_output=True, text=True)
print(res.stdout)
