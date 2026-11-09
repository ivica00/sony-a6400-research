import subprocess

# Search symbols in libObj.so
cmd = "arm-linux-gnueabi-nm -D -C firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libObj.so | grep -i 'dmm_unit_ctrl'"
res = subprocess.run(["wsl", "bash", "-c", cmd], capture_output=True, text=True)
print(res.stdout)
