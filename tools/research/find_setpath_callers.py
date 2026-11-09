import subprocess

lib = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libInfraStreamingServer.so'

cmd = f"arm-linux-gnueabi-objdump -d {lib} | grep -B 10 -A 5 '10ea8'"
res = subprocess.run(["wsl", "bash", "-c", cmd], capture_output=True, text=True)
print(res.stdout)
