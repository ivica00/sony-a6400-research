import subprocess

lib = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libInfraStreamingServer.so'

for start, stop in [(0x10a50, 0x10b80), (0x10d50, 0x10ec0)]:
    cmd = f"arm-linux-gnueabi-objdump -d --start-address={hex(start)} --stop-address={hex(stop)} {lib}"
    res = subprocess.run(["wsl", "bash", "-c", cmd], capture_output=True, text=True)
    print(f"=== Disasm {hex(start)} to {hex(stop)} ===")
    print(res.stdout)
