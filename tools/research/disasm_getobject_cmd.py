import subprocess

lib = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libInfraRemote.so'

cmd = f"arm-linux-gnueabi-nm -D -C {lib} | grep -i GetObject_cmd"
res = subprocess.run(["wsl", "bash", "-c", cmd], capture_output=True, text=True)
print("Symbols:", res.stdout)

# Disassemble around that symbol
for line in res.stdout.splitlines():
    parts = line.split()
    if len(parts) >= 3:
        addr = int(parts[0], 16)
        cmd_d = f"arm-linux-gnueabi-objdump -d --start-address={hex(addr)} --stop-address={hex(addr+300)} {lib}"
        res_d = subprocess.run(["wsl", "bash", "-c", cmd_d], capture_output=True, text=True)
        print(f"=== Disasm at {hex(addr)} ===")
        print(res_d.stdout[:1500])
