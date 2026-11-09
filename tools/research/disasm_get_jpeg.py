import subprocess

lib = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libInfraStreamingServer.so'

cmd = "arm-linux-gnueabi-objdump -d --start-address=0x10b10 --stop-address=0x10b70 " + lib
res = subprocess.run(["wsl", "bash", "-c", cmd], capture_output=True, text=True)
print(res.stdout)
