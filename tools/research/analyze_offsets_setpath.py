import subprocess

lib = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libInfraStreamingServer.so'

# Disassemble with comments
cmd = "arm-linux-gnueabi-objdump -d --start-address=0x10eb0 --stop-address=0x10f20 " + lib
res = subprocess.run(["wsl", "bash", "-c", cmd], capture_output=True, text=True)
print(res.stdout)
