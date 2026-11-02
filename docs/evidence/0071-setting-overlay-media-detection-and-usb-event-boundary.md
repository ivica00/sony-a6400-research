# Evidence Record 0071: Setting Overlay, Media Detection, and USB Event Driver Contract

**Date**: 2026-11-02  
**Milestone**: 82,556,194 instructions executed; 1,349 serviced syscalls; 15 concurrent firmware threads; USB event character device contract verified.

---

## 1. Summary of Achievements

1. **Setting Overlay Contract**:
   - `THREAD_INFRA2` (TID 1007) in `libObj.so` at `0x83cf30` accesses `/setting`.
   - Added `setting_overlay` (`experimental-empty`) to `GuestFilesystem` providing valid directory metadata for partition 2 mountpoint.
   - Allowed infrastructure services to proceed and spawn audio, AV effector, and USB control threads.

2. **MediaCommonDriver UIPC Service Contract**:
   - Firmware queue `0x00d9016e` receives category 2, subcmd 1 (`CheckInsertedMedia`).
   - Implemented `GuestMediaCommon` in `src/a6400/execution/guest_media_common.py` responding with authentic SD card presence (`media_type = 3`).
   - Integrated `media_service_policy` (`authentic-sd`) into `GuestUipc` and probe runtime.

3. **USB Event Driver Contract (`/dev/usb/event`)**:
   - Reverse-engineered character device from `vmlinux.bin` `udif_devnodes` table at `0x3d2ba8` and `file_operations` at `0x3dcf38`:
     - **Major: 242, Minor: 0** (`c 242 0`)
     - Operations: `open` (`0x602b5a00`), `release` (`0x602b56f8`), `unlocked_ioctl` (`0x602b5814`), `read` (`0x602b5d7c`)
   - Reverse-engineered consumer in `libInfraUsbCmn.so`:
     - `usb_event_start` (`0xc7a4`): opens `/dev/usb/event` (`O_RDWR`), configures `FD_CLOEXEC`, initializes mutex/cond, allocates ring buffer, and spawns background worker `usb_event_thread` via `pthread_create`.
     - `USB_EVENT_IOCTL_ENABLE = 0x4004e101` (`_IOW(0xe1, 1, uint32)`)
     - `USB_EVENT_IOCTL_DISABLE = 0x4004e102` (`_IOW(0xe1, 2, uint32)`)
     - `USB_EVENT_IOCTL_STOP = 0x0000e103` (`_IO(0xe1, 3)`)
   - Implemented `GuestUsbEvent` in `src/a6400/execution/guest_usb_event.py` and connected into `InterpreterProbe` and `experiment_ui_boot.py` under `--usb-event-device driver-bound`.
   - Added thread descriptor blocking read handler `handle_fd_wait` in `src/a6400/execution/guest_threads.py`.

4. **Execution Milestone**:
   - Advanced execution from 81,919,865 to **82,556,194 instructions** (+636,329 instructions).
   - Serviced syscalls increased from 1,164 to **1,349**.
   - Spawned 15 concurrent threads:
     - TID 1000: `main`
     - TID 1001: `THREAD_INFRA0`
     - TID 1002: `thread_1002`
     - TID 1003: `thread_1003`
     - TID 1004: `THREAD_INFRA1`
     - TID 1005: `grm_dn_vdf_if`
     - TID 1006: `UDATE_ASYNCSET`
     - TID 1007: `THREAD_INFRA2`
     - TID 1008: `thread_1008` (Sugilite display worker)
     - TID 1009: `InfraAudioDecode`
     - TID 1010: `UsbBusPower`
     - TID 1011: `InfraAvEffector`
     - TID 1012: `UsbControl`
     - TID 1013: `thread_1013`
     - TID 1014: `thread_1014` (`usb_event_thread`)
   - New authentic boundary reached: `open("/dev/usb/otgcore", O_RDWR)` on Major 242, Minor 2.
   - All 498 unit tests passing.

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
  --instructions 100000000 `
  --timeout-us 600000000 `
  --report artifacts/execution/ui-boot-usb-event-100m.json
```

---

## 3. Next Steps

1. Implement `GuestUsbOtgCore` for `/dev/usb/otgcore` (Major 242, Minor 2).
2. Reverse-engineer ioctl commands for `/dev/usb/otgcore` from `vmlinux.bin` and `libInfraUsbCmn.so`.
3. Advance execution past 82.55M instructions toward media mount and SD card filesystem reading.
