import subprocess

lib = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libInfraPtpControl.so'

# Check dynamic symbols in libInfraPtpControl.so
cmd = f"arm-linux-gnueabi-nm -D -C {lib} | grep -iE 'liveview|jpeg|getobject|scalar'"
res = subprocess.run(["wsl", "bash", "-c", cmd], capture_output=True, text=True)
print(res.stdout[:1500])
