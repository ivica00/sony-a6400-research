# Evidence Record 0072: USB OTG Core Driver Contract and HDMI Subsystem Boundary

**Date**: 2026-11-03  
**Milestone**: 85,766,715 instructions executed; 1,747 serviced syscalls; 20 concurrent firmware threads; 66 open file descriptors; `/dev/usb/otgcore` verified and HDMI subsystem boundary reached.

---

## 1. Summary of Achievements

1. **USB OTG Core Driver Contract (`/dev/usb/otgcore`)**:
   - Evidenced in `vmlinux.bin` `udif_devnodes` table at `0x3d2ba8`:
     - **Major: 242, Minor: 2** (`c 242 2`)
     - Operations: `open` (`0x602b7108`), `unlocked_ioctl` (`0x602b7468`)
   - Reverse-engineered consumer in `libInfraUsbCmn.so` (`0xa7e4..0xaa34`):
     - `0xa806`: `open("/dev/usb/otgcore", O_RDWR=2)`
     - `0xa828`: `fcntl(fd, F_SETFD, FD_CLOEXEC)`
     - `0xa892`: `ioctl(fd, 0x4024e301, &struct_36_bytes)` -> `USB_OTGCORE_IOCTL_SET_PORT_DESC`
     - `0xa8b4`: `ioctl(fd, 0x0000e304)` -> `USB_OTGCORE_IOCTL_START`
     - `0xa9a0`: `ioctl(fd, 0x0000e303)` -> `USB_OTGCORE_IOCTL_STOP`
     - `0xa9c2`: `ioctl(fd, 0x0000e302)` -> `USB_OTGCORE_IOCTL_RESET`
     - `0xa7d2`: `ioctl(fd, 0x4040e311, &struct_64_bytes)` -> `USB_OTGCORE_IOCTL_SET_CONFIG`
     - `0xaa0a`: `close(fd)`
   - Implemented `GuestUsbOtgCore` in `src/a6400/execution/guest_usb_otgcore.py` with strict memory address limits (`TASK_SIZE <= 0x5f000000`).
   - Wired `/dev/usb/otgcore` into `InterpreterProbe` and `tools/research/experiment_ui_boot.py` under `--usb-otgcore-device driver-bound`.
   - Added 8 unit tests in `tests/test_guest_usb_otgcore.py` (all 506 unit tests passing).

2. **Execution Milestone (85.76M Instructions)**:
   - Execution advanced from 82,556,194 to **85,766,715 instructions** (+3,210,521 instructions).
   - Serviced syscalls increased from 1,349 to **1,747** (+398 serviced syscalls).
   - Open descriptors increased from 14 to **66**.
   - Spawned 5 new threads, reaching **20 concurrent threads**:
     - TID 1000: `main` (blocked_futex)
     - TID 1001: `THREAD_INFRA0` (blocked_futex)
     - TID 1002: `thread_1002` (blocked_futex)
     - TID 1003: `thread_1003` (blocked_futex)
     - TID 1004: `THREAD_INFRA1` (blocked_futex)
     - TID 1005: `grm_dn_vdf_if` (blocked_uipc)
     - TID 1006: `UDATE_ASYNCSET` (blocked_futex)
     - TID 1007: `THREAD_INFRA2` (running - performing HDMI display/bus setup)
     - TID 1008: `thread_1008` (active Sugilite GPU/display render worker)
     - TID 1009: `InfraAudioDecode` (blocked_uipc)
     - TID 1010: `UsbBusPower` (blocked_futex)
     - TID 1011: `InfraAvEffector` (blocked_uipc)
     - TID 1012: `UsbControl` (blocked_futex)
     - TID 1013: `InfraDecoder` (blocked_uipc)
     - TID 1014: `thread_1014` (`usb_event_thread`, waiting on `/dev/usb/event` read)
     - TID 1015: `thread_1015` (blocked_futex)
     - TID 1016: `BusPower` (from `libBusPower.so`)
     - TID 1017: `InfraMovieEditor` (multimedia infrastructure thread)
     - TID 1018: `Hotplug` (display/cable hotplug management thread)
     - TID 1019: `thread_1019` (runnable worker)
   - Dynamic library loading: loaded `libBusPower.so` and `libInfraHdmi.so`.
   - Kernel module loading: mapped and initialized `/usr/kmod/hdmi.ko` (SHA-256: `cc70cc5956b6bf48601cdd874fe31a03e1b7c7ddeb925bb22b8aebb4f86d9faf`) via verified-image `init_module` (r7 = 128).

3. **Discovery of Complete Sony Device Table (`devno.ko`)**:
   - Located kernel module `devno.ko` (`dev/nflasha7_unpacked/kmod/devno.ko` and `initrd.img_unpacked/kmod/devno.ko`).
   - Exported symbol `udif_devnodes` contains an 88-entry Sony character/block device registration table:
     - Confirmed `/dev/usb/buspwr` is Major 248, Minor 13 (`0x00f80000`, minor `0x0d`).
     - Confirmed `/dev/hdmi` is **Major 248, Minor 25** (`0x00f80000`, minor `0x19`).
     - Confirmed `hdmi_external_tx` is Major 248, Minor 26 (`0x1a`).
     - Confirmed `cec` is Major 248, Minor 27 (`0x1b`).
     - Confirmed `dmpgles2` is Major 248, Minor 29 (`0x1d`).
     - Confirmed `hdmi_input` is Major 248, Minor 30 (`0x1e`).

4. **New Boundary Reached**:
   - Stopped at `open("/dev/hdmi", O_RDWR)` (`flags = 2`) at PC `0x5008bc64` (inst address `1342749796`, `r7 = 5`).
   - Caller: `THREAD_INFRA2` (TID 1007) via `libInfraHdmi.so` at offset `0x53234`.
   - Next milestone: implement `GuestHdmi` (`major: 248, minor: 25`) with verified ioctls (`0xc0044801..0xc0044813`).

---

## 2. Command Line Reproduction

```powershell
python -m tools.research.experiment_ui_boot `
  --argument i `
  --stimulus none `
  --urandom-open `
  --urandom-entropy deterministic `
  --tmp-overlay experimental-empty `
  --proc-overlay experimental-empty `
  --setting-overlay experimental-empty `
  --media-service authentic-sd `
  --stream-device image-driver `
  --regular-inode-rdev `
  --readonly-image-times `
  --backup-service preset-backed `
  --graphics-service authentic-grm `
  --null-page read-zero `
  --madvise-dontneed `
  --gles-device kernel-bound `
  --gpio-device driver-bound `
  --kmod-service verified-image `
  --usb-buspower-device driver-bound `
  --usb-event-device driver-bound `
  --usb-otgcore-device driver-bound `
  --instructions 100000000 `
  --timeout-us 600000000 `
  --report artifacts/execution/ui-boot-usb-otgcore-100m.json
```

---

## 3. Boundary Details

```json
{
  "reason": "open_flags_not_read_only_subset",
  "path": "/dev/hdmi",
  "flags": 2,
  "pc": 1342749796,
  "r7": 5,
  "arguments": [
    378614324,
    2,
    1
  ]
}
```

- Target path: `/dev/hdmi`
- Character device: Major 248, Minor 25 (`c 248 25`)
- Ioctl contract family: `'H'` (`0xc0044801..0xc0044813`) defined in `hdmi.ko` (`hdmi_dev_ioctl`)
