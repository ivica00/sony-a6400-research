import capstone

with open('firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libMWF.so', 'rb') as f:
    f.seek(0x0001edac)
    code = f.read(46)

print("=== UpdateInhFactor ===")
md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
for insn in md.disasm(code, 0x0001edac):
    print(f"0x{insn.address:08x}: {insn.mnemonic} {insn.op_str}")

print("\n=== ChangeInhFactorStatus ===")
with open('firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libMWF.so', 'rb') as f:
    f.seek(0x0001ecf8)
    code = f.read(96)
for insn in md.disasm(code, 0x0001ecf8):
    print(f"0x{insn.address:08x}: {insn.mnemonic} {insn.op_str}")
