import subprocess

lib = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libObj.so'

cmd = "arm-linux-gnueabi-objdump -d --start-address=0x195280 --stop-address=0x195310 " + lib
res = subprocess.run(["wsl", "bash", "-c", cmd], capture_output=True, text=True)
print(res.stdout)
