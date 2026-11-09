import struct
import subprocess

with open('artifacts/hardware/av-cam-camera-original.bin', 'rb') as f:
    data = f.read()

base_addr = 0x635c6000

# Look for occurrences of 0x01670464 being loaded into a register right before a BL
needle = struct.pack('<I', 0x01670464)
pos = 0
while True:
    pos = data.find(needle, pos)
    if pos == -1: break
    addr = base_addr + pos
    print(f"0x01670464 literal at addr 0x{addr:x}")
    # Now check if any PC-relative LDR loads this literal
    for i in range(max(0, pos - 1000), pos, 2):
        w = struct.unpack_from('<H', data, i)[0]
        if (w & 0xf800) == 0x4800: # ldr rX, [pc, #imm]
            reg = (w >> 8) & 7
            imm8 = (w & 0xff) * 4
            pc = ((base_addr + i + 4) & ~3)
            if pc + imm8 == addr:
                ldr_addr = base_addr + i
                print(f"  Loaded by ldr r{reg}, [pc, #{imm8}] at 0x{ldr_addr:x}")
    pos += 4
