import capstone

with open('artifacts/hardware/av-cam-camera-original.bin', 'rb') as f:
    f.seek(0x636d7c48 - 0x635c6000)
    code = f.read(64)

md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
for insn in md.disasm(code, 0x636d7c48):
    print(f"0x{insn.address:08x}: {insn.mnemonic} {insn.op_str}")
