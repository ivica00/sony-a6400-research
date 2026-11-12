# E0412 — Live Wi-Fi baseline and SDIO detection contract

2026-11-12. Read-only camera observation over the recovered v1 MSC debugger and offline analysis of the live-build module preserved in E0410. Wi-Fi remained off. No Wi-Fi activation, SD changes or physical-memory reads.

## Live baseline

- The debugger served the baseline and remained responsive, with uptime advancing from 797.52 to 819.40 seconds.
- `mmc_drv` and `wlanMemoryAllocator` are loaded. `mmcioWrapper` and `bcmdhd` are absent, and there is no WLAN network interface.
- The current boot log shows successful SD slot-0 mount cycles, including controller tuning and discovery of `mmca10: p1`. The WLAN path selects slot 1, so this observation only establishes a working slot-0 path.
- `/sys/module/mmc_drv/parameters` is absent. The checked `/sys/bus/sdio/devices` and `/sys/class/mmc_host` paths are also absent in this baseline.

## Correction to E0410

In the preserved live `mmc_drv.ko`, `mmc_io_detect` at `0xee28` calls helper `0xeae4` at `0xee5c` and `0xeeb4`. The helper constructs command **5**, passes the requested OCR argument, calls the command executor and copies the response word back to the caller. The masks at `0xee6c` and `0xee74` check the returned OCR bits and SDIO function count respectively. After selecting a supported voltage, the driver polls CMD5 for the ready bit for up to about one second. These checks are on the CMD5 response. The prior description of this check as CMD52/CCCR vendor validation was incorrect.

The saved crash shows failure in the broader card-open sequence. It does not show whether CMD5 was sent, timed out, returned a rejected response or succeeded before a later step failed.

## Trace candidate

`mmc_trc_set_cmd_history`, `mmc_trc_set_err_status` and `mmc_trc_write_log_data` exist in the live-build module. The `mmcd_char_ioctl` call at `0x6378` resolves to `mmc_trc_get_area`, which selects a per-slot trace area. This establishes an internal call path only. The user-space return contract, slot-1 trace allocation and survival across the observed warm reboot still need verification. No trace ioctl was sent to the camera.

## SD capture across one owner-triggered Wi-Fi reboot

The Windows camera used libusb-win32 and presented no Windows disk device. The logger mounted only the identified removable SD partition at `/tmp_bt/wifi-sd-log` with synchronous FAT writes. A dry run created, verified and unmounted `WIFICHEK.LOG`. The main capture polled the filtered kernel log at approximately 250 ms intervals and synced changed snapshots. The owner disconnected USB and enabled Wi-Fi once.

After the reboot, the 5,601-byte `WIFICRSH.LOG` was copied through the service channel from a read-only SD mount. The final snapshot contains WLAN allocation at kernel timestamp 1217.682028, controller probe at 1218.038966, power-off at 1218.082326–1218.382743, then `mmcio_mount failed!` and `mmcio_wrapper_init failed!`. It contains neither the CPU exception nor a CMD5 response. This reproduces the mount failure with the card present and establishes that the UHS2 warning also occurs during successful earlier slot-0 mounts in the same log.

The read-only SD mount was removed. The v1 debugger was restarted and answered in MSC at post-reboot uptime 62.08 seconds. The SD logger was not relaunched.
