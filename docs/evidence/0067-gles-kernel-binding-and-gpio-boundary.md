# Evidence 0067: GLES kernel process binding and GPIO boundary advance

Date: 2026-10-27

## Result

Executing the main process (`im.elf`) under the explicit `--gles-device kernel-bound` policy connects userland graphics initialization to the authentic `GuestGles` driver model respecting reciprocal task identity, `TASK_SIZE = 0x5f000000`, and kernel task limits:

1. **Successful GLES device open and driver lifecycle**:
   - `open("/dev/dmpgles2", O_RDWR)` successfully opens fd 10 (major 248, minor 29).
   - Ten authentic GLES syscalls are serviced in sequence:
     - `ioctl(0x80048206)` (`GLES_GET_MMIO_SIZE`): returns MMIO size `0x4000` (16 KiB).
     - `ioctl(0xc0048202)` (`GLES_QUERY_RESOURCE`): queries Sugilite resource table index 0 (`0x80000000`).
     - `ioctl(0x80048263)` (`GLES_GET_POWER_STATE`): returns power state 1 (powered on).
     - `ioctl(0xc0048211)` (`GLES_LOCK_SEMAPHORE`): acquires hardware lock semaphore.
     - `mmap2(length=0x20000, 128 KiB)`: allocates and maps device command buffer at virtual `0x11810000`.
     - `ioctl(0xc0048212)` (`GLES_UNLOCK_SEMAPHORE`): releases hardware semaphore.
     - `ioctl(0xc0048211)` (`GLES_LOCK_SEMAPHORE`): re-acquires semaphore.
     - `ioctl(0xc004820e)` (`GLES_SIGNAL_COMPLETION`): signals completion on event.
     - `ioctl(0xc0048212)` (`GLES_UNLOCK_SEMAPHORE`): releases semaphore.

2. **Process continuation and new boundary**:
   - Following GLES driver binding, the process maps `/dev/mem` (fd 11) and activates downstream libraries:
     - `//usr/lib/libResourceBluetooth.so` (fd 12)
     - `//usr/lib/libBTUtils.so` (fd 12)
   - The process executes **81,540,245 instructions** (advancing 800,794 instructions past the prior 80,739,451 stop).
   - Execution stops cleanly at the next unsupplied hardware contract:
     - Syscall: `open` (r7 = 5)
     - Path: `/dev/gpio`
     - Flags: 2 (`O_RDWR`)
     - Status: `unsupported_filesystem`, reason: `open_flags_not_read_only_subset`
     - PC: `0x5008bc64` (1342749796), caller TID: 1003, TGID: 1000.

## Inputs and evidence references

- `artifacts/execution/ui-boot-gles-kernel-bound-100m.json`:
  Complete execution record reaching 81,540,245 instructions with 993 serviced syscalls, fd 10 (`/dev/dmpgles2`), fd 11 (`/dev/mem`), and stopping on `/dev/gpio`.
- `src/a6400/execution/guest_gles.py`:
  Authentic `GuestGles` and `GlesBinding` implementations enforcing `TASK_SIZE = 0x5f000000`.
- Preserved inputs:
  - `dev/nflasha15_unpacked/kmod/grm_gles.ko`: GLES kernel module (SHA `a8d1dbe8c66be365d32371b13f35a0e7d598c415c0ff17f2c8f544084ccc6882`).
  - `dev/nflasha3_unpacked/vmlinux.bin`: Kernel binary (SHA `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707`).

## Validation

All **468 unit tests pass** (14.865 seconds).
No faked GPIO responses, synthetic draw calls, or host-invented framebuffers are supplied. SD card `E:\` remains strictly read-only.
