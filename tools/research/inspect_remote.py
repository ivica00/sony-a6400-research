with open('firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libInfraRemote.so', 'rb') as f:
    elf = f.read()

print("Bytes around b700:")
print(elf[0xb6f0:0xb720].hex())
