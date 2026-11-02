# Evidence 0068: GPIO driver contract and USB bus power kernel module boundary

Date: 2026-10-28

## Result

Executing the main process (`im.elf`) under `--gpio-device driver-bound` connects userland GPIO configuration to the authentic `GuestGpio` driver model (major 240, minor 0):

1. **Successful GPIO device open, ioctl dispatch, and descriptor close**:
   - `open("/dev/gpio", O_RDWR)` successfully opens fd 12 with verified device number `240:0` (derived from `nflasha7` inode 366).
   - Serviced two consecutive authentic `GPIO_CMD_SET_MODE` (`0xc0104702`) ioctls from `libul_GpioCtrl.so` via `libResourceBluetooth.so`, configuring pin operating modes.
   - Closed fd 12 via `close` (syscall 6), releasing the GPIO owner cleanly.

2. **Downstream continuation and USB module load boundary**:
   - Following GPIO initialization, execution advances through Bluetooth setup and loads `//usr/lib/libUsbBusPower.so`.
   - The process opens and maps `/usr/kmod/usbg_buspower.ko` (fd 12, size 14,068 bytes, SHA `81fee5ccc6b14bc9f46e7f8315308b2476ba056763bf16e84ccaf053e38cea41`).
   - The process reaches **81,686,763 instructions** (advancing 146,518 instructions past the 81,540,245 GPIO boundary) and services **1,051 syscalls**.
   - Execution stops cleanly at `init_module` (r7 = 128) requesting kernel insertion of `/usr/kmod/usbg_buspower.ko`:
     - Syscall: `init_module` (r7 = 128)
     - Address: `0x1285f000` (310771712), Length: 14,068 bytes
     - Status: `syscall_boundary`
     - PC: `0x5029e230` (1344920912), caller TID: 1003, TGID: 1000.

## Inputs and evidence references

- `artifacts/execution/ui-boot-gpio-bound-100m.json`:
  Complete execution record reaching 81,686,763 instructions with 1,051 serviced syscalls, fd 12 (`/dev/gpio`), opening `/usr/kmod/usbg_buspower.ko`, and stopping at `init_module`.
- `src/a6400/execution/guest_gpio.py`:
  Authentic `GuestGpio` implementation enforcing `TASK_SIZE = 0x5f000000` and handling `'G'` group ioctls (`0xc0104702`, `0xc0104701`).
- Preserved inputs:
  - `dev/nflasha15_unpacked/kmod/usbg_buspower.ko`: USB bus power module (SHA `81fee5ccc6b14bc9f46e7f8315308b2476ba056763bf16e84ccaf053e38cea41`).
  - `dev/nflasha15_unpacked/lib/libul_GpioCtrl.so`: Sony userland GPIO middleware.
  - `dev/nflasha15_unpacked/lib/libResourceBluetooth.so`: Sony Bluetooth resource library.

## Validation

All **476 unit tests pass** (14.581 seconds).
Physical card volume `E:\` remains strictly read-only. No host-faked module insertion or unverified kernel replies are supplied.
