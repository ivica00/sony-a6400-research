import struct
import subprocess

with open('artifacts/hardware/av-cam-camera-original.bin', 'rb') as f:
    data = f.read()

base_addr = 0x635c6000
target_addr = 0x63a90c38
file_offset = target_addr - base_addr
print(f"ScalarInfraAsyncMain target offset: 0x{file_offset:x}")

# Save slice around target_addr to disassemble with objdump
slice_bytes = data[file_offset:file_offset + 512]
with open('artifacts/analysis/scalar_infra_slice.bin', 'wb') as sf:
    sf.write(slice_bytes)

print("Saved slice, disassembling...")
for target in [0x63d95204, 0x63d951f4, 0x63d950f0, 0x63d950e0, 0x63aa185c, 0x63aa1798]:
    offset = target - base_addr
    slice_b = data[offset:offset+48]
    with open('artifacts/analysis/plt_slice.bin', 'wb') as sf:
        sf.write(slice_b)
    cmd = f"arm-linux-gnueabi-objdump -b binary -m arm -M force-thumb --adjust-vma={hex(target)} -D artifacts/analysis/plt_slice.bin"
    res = subprocess.run(["wsl", "bash", "-c", cmd], capture_output=True, text=True)
    print(f"=== Target {hex(target)} ===")
    print(res.stdout)
