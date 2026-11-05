# Evidence 0079: `/dev/mmca-char` & `/dev/ms-char` Driver Contracts and 102.27M Milestone (`fstat64("/dev/urandom")` Boundary)

**Date**: 2026-11-04
**Status**: Verified
**Test Suite**: 534 passing unit tests

---

## 1. Executive Summary

Following the `Backup_read_multi` and WBI `/dev/stream` (`PA 0x20030000`) milestone (Evidence 0078), execution stopped at 88,268,051 instructions in `TID 1004 (THREAD_INFRA1)` inside `mcmn_init` (`0x945c` in `/usr/lib/libInfraMediaCommon.so`) at `open64("/dev/mmca-char", O_RDWR | O_NOATIME | O_LARGEFILE)`.

In this milestone:
1. **`mcmn_drv_init` / `mcmn_drv_mod_init` Reverse Engineering (`libInfraMediaCommon.so`, `mmc_drv.ko`, `ms_drv.ko`)**:
   - Disassembled `mcmn_init` (`0x945c`), `mcmn_drv_init` (`0xb428`), `mcmn_drv_mod_init` (`0x13848`), `mcmn_drv_mmc_init` (`0x128c4`), `mcmn_drv_ms_init` (`0x14ed4`), and `mcmn_drv_sata_init` (`0x16ed0`).
   - Verified `mmcd_char_open` (`0x28b4`), `mmcd_char_close` (`0x28c8`), `minor_to_hwid` (`0x9ae4`), `mmcd_char_ioctl` (`0x5898`), `mmc_trc_set_area` (`0xfdfc`), and `mmc_trc_get_area` (`0xff80`) in `/usr/kmod/mmc_drv.ko` (major 250, minors 0..2).
   - Verified `ms_char_open` (`0x343c`), `ms_char_close` (`0x3450`), `ms_char_ioctl` (`0x356c`), and `msdl_ioctl_set_errlog_area` (`0x46fc`) in `/usr/kmod/ms_drv.ko` (major 249, minor 0).
   - Confirmed against live Sony ILCE-6400 hardware telemetry (`reports/a6400_hw_dump.txt` lines 198–204, 292–320) that major 249 registers `ms-char`, `mcmn`, `stream`, and `stream2`, with no `sata` driver registered (`/dev/sata` major 249 minor 2 returns `-ENXIO = -6`, causing `mcmn_drv_sata_init` at `0x16f06` to return cleanly).

2. **`GuestMmcChar` Implementation (`src/a6400/execution/guest_mmca_char.py`)**:
   - Services `open`, `close`, and all 20 `mmcd_char_ioctl` commands (`0x01`, `0x20120328`, `0x03`, `0x04`, `0x05`, `0x06`, `0xf0..0xfd`) for `/dev/mmca-char` (`250:0`), `/dev/mmcb-char` (`250:1`), and `/dev/mmcc-char` (`250:2`).
   - Enforces the 64-byte size alignment check (`(size & 0x3f) == 0`, else status `-3 = 0xfffffffd`) on `MMC_CHAR_IOCTL_SET_TRC_AREA` (`0x04`) and records the physical trace ring areas (`0x20030800` size `0x400` for `hwid 0`, `0x20031900` size `0x200` for `hwid 1`, `0x20031000` size `0x400` for `hwid 2`).
   - Services `open`, `close`, and all 8 `ms_char_ioctl` commands (`0x80047601..0x80047604`, `0x80047664`, `0xc0047665`, `0x80047666`, `0x80047667`) for `/dev/ms-char` (`249:0`), recording the MemoryStick error-log area (`0x20030400` size `0x400`).

3. **Execution Milestone (102,265,088 Instructions — +14.00M Instruction Advance)**:
   - Execution advances from 88,268,051 to **102,265,088 instructions** (+13,997,037 instructions).
   - Serviced syscalls increase from 2,275 to **3,181** (+906 serviced syscalls).
   - Open file/device records increase from 75 to **98** (+23 files/devices/modules).
   - Concurrent threads increase from 27 to **37** (+10 new threads: `4x IFsys`, `InfraNfc`, `InfraBluetoothMa`, `WlanResource_Mai`, `WlanResource_Irq`, `IMD-Default`, `NetServiceMainTh`, plus `CEC Dev Thread` named on `TID 1026`).
   - `TID 1007 (THREAD_INFRA2)` authenticates and initializes `/usr/kmod/wlanMemoryAllocator.ko` (7,080 bytes) via `init_module`, loads the full Airplane Mode, NFC, Bluetooth, and Wi-Fi/NetService stacks, and stops at `fstat64(fd=27, statbuf)` on `/dev/urandom` (`r7 = 197`, reason `urandom_operation_not_implemented`).

---

## 2. BootLogger Real-Time Trace Excerpt (88.27M -> 102.27M)

```text
[BOOT  88.27M | DEV  ] Opened device /dev/mmca-char (major=250, minor=0) -> fd=25 [TID 1004 THREAD_INFRA1]
[BOOT  88.27M | IOCTL] First mmca_char ioctl 0x00000004 (_IO('0x00', 0x04, 0)) -> 0 [TID 1004 THREAD_INFRA1]
[BOOT  88.27M | DEV  ] Opened device /dev/mmcb-char (major=250, minor=1) -> fd=25 [TID 1004 THREAD_INFRA1]
[BOOT  88.27M | DEV  ] Opened device /dev/mmcc-char (major=250, minor=2) -> fd=25 [TID 1004 THREAD_INFRA1]
[BOOT  88.27M | DEV  ] Opened device /dev/ms-char (major=249, minor=0) -> fd=25 [TID 1004 THREAD_INFRA1]
[BOOT  88.27M | IOCTL] First mmca_char ioctl 0x80047667 (_IOR('v', 0x67, 4)) -> 0 [TID 1004 THREAD_INFRA1]
[BOOT  88.44M | THRD ] Spawned thread TID 1027 (parent=TID 1004 THREAD_INFRA1, total=28)
[BOOT  88.44M | THRD ] Named thread TID 1026 -> "CEC Dev Thread"
[BOOT  88.44M | PIPE ] Created pipe:[2] -> read_fd=25, write_fd=26 [TID 1026 CEC Dev Thread]
[BOOT  88.45M | POLL ] Thread TID 1026 (CEC Dev Thread) blocked on poll(fds=[22, 25]) -> switched to TID 1007
[BOOT  88.46M | LIB  ] Loaded shared library /usr/lib/libInfraAirplaneMode.so (fd=27) [TID 1007 THREAD_INFRA2]
[BOOT  88.56M | LIB  ] Loaded shared library /usr/lib/libInfraNfc.so (fd=27) [TID 1007 THREAD_INFRA2]
[BOOT  88.84M | THRD ] Spawned thread TID 1028 (parent=TID 1007 THREAD_INFRA2, total=29)
[BOOT  88.84M | THRD ] Named thread TID 1027 -> "IFsys"
[BOOT  88.84M | THRD ] Spawned thread TID 1029 (parent=TID 1004 THREAD_INFRA1, total=30)
[BOOT  88.84M | THRD ] Named thread TID 1028 -> "InfraNfc"
[BOOT  88.87M | LIB  ] Loaded shared library /usr/lib/libInfraBluetooth.so (fd=27) [TID 1007 THREAD_INFRA2]
[BOOT  88.88M | LIB  ] Loaded shared library /usr/lib/libInfraBluetoothCore.so (fd=27) [TID 1007 THREAD_INFRA2]
[BOOT  88.90M | LIB  ] Loaded shared library /usr/lib/libBTAdjust.so (fd=27) [TID 1007 THREAD_INFRA2]
[BOOT  89.91M | THRD ] Spawned thread TID 1030 (parent=TID 1007 THREAD_INFRA2, total=31)
[BOOT  89.96M | THRD ] Named thread TID 1029 -> "IFsys"
[BOOT  89.97M | THRD ] Spawned thread TID 1031 (parent=TID 1004 THREAD_INFRA1, total=32)
[BOOT  89.97M | THRD ] Named thread TID 1030 -> "InfraBluetoothMa"
[BOOT  90.13M | LIB  ] Loaded shared library /usr/lib/libWlanResource.so (fd=27) [TID 1007 THREAD_INFRA2]
[BOOT  90.14M | LIB  ] Loaded shared library /usr/lib/iw.so (fd=27) [TID 1007 THREAD_INFRA2]
[BOOT  90.16M | LIB  ] Loaded shared library /usr/lib/libnl-3.so.200 (fd=27) [TID 1007 THREAD_INFRA2]
[BOOT  90.17M | LIB  ] Loaded shared library /usr/lib/libnl-genl-3.so.200 (fd=27) [TID 1007 THREAD_INFRA2]
[BOOT  90.18M | LIB  ] Loaded shared library /usr/lib/libnl-route-3.so.200 (fd=27) [TID 1007 THREAD_INFRA2]
[BOOT  90.19M | LIB  ] Loaded shared library /usr/lib/libnl-nf-3.so.200 (fd=27) [TID 1007 THREAD_INFRA2]
[BOOT  90.21M | LIB  ] Loaded shared library /usr/lib/libnl-cli-3.so.200 (fd=27) [TID 1007 THREAD_INFRA2]
[BOOT  90.98M | THRD ] Spawned thread TID 1032 (parent=TID 1007 THREAD_INFRA2, total=33)
[BOOT  90.98M | THRD ] Named thread TID 1031 -> "IFsys"
[BOOT  91.46M | THRD ] Spawned thread TID 1033 (parent=TID 1004 THREAD_INFRA1, total=34)
[BOOT  91.46M | THRD ] Named thread TID 1032 -> "WlanResource_Mai"
[BOOT  91.46M | THRD ] Spawned thread TID 1034 (parent=TID 1007 THREAD_INFRA2, total=35)
[BOOT  91.46M | THRD ] Named thread TID 1033 -> "IFsys"
[BOOT  91.92M | THRD ] Spawned thread TID 1035 (parent=TID 1004 THREAD_INFRA1, total=36)
[BOOT  91.92M | THRD ] Named thread TID 1034 -> "WlanResource_Irq"
[BOOT  91.95M | KMOD ] Opened kernel module /usr/kmod/wlanMemoryAllocator.ko (fd=27) [TID 1007 THREAD_INFRA2]
[BOOT  91.96M | KMOD ] Authenticated & initialized /usr/kmod/wlanMemoryAllocator.ko (7,080 bytes) -> 0 [TID 1007 THREAD_INFRA2]
[BOOT  91.98M | LIB  ] Loaded shared library /usr/lib/libWlanAdjust.so (fd=27) [TID 1007 THREAD_INFRA2]
[BOOT  91.99M | LIB  ] Loaded shared library /usr/lib/libWlanControlCommon.so (fd=27) [TID 1007 THREAD_INFRA2]
[BOOT  92.00M | LIB  ] Loaded shared library /usr/lib/libExternalCommand.so (fd=27) [TID 1007 THREAD_INFRA2]
[BOOT  92.49M | LIB  ] Loaded shared library /usr/lib/libNetService.so (fd=27) [TID 1007 THREAD_INFRA2]
[BOOT 102.14M | THRD ] Spawned thread TID 1036 (parent=TID 1007 THREAD_INFRA2, total=37)
[BOOT 102.15M | DEV  ] Opened device /dev/gpio (major=240, minor=0) -> fd=27 [TID 1032 WlanResource_Mai]
[BOOT 102.17M | THRD ] Named thread TID 1035 -> "IMD-Default"
[BOOT 102.22M | IOCTL] First /dev/uipc ioctl 0x80000003 (_IOR('0x00', 0x03, 0)) -> 0 [TID 1004 THREAD_INFRA1]
[BOOT 102.23M | THRD ] Named thread TID 1036 -> "NetServiceMainTh"
[BOOT 102.26M | DEV  ] Opened device /dev/urandom -> fd=27 [TID 1007 THREAD_INFRA2]
```

---

## 3. Boundary Diagnosis at 102.27M Instructions

```text
==============================================================================
=== A6400 EMULATOR BOUNDARY & GROUND-TRUTH DIAGNOSIS ===
==============================================================================
Status              : unsupported_filesystem
Instructions        : 102,265,088
Serviced Syscalls   : 3,181
Active Thread       : TID 1007 (THREAD_INFRA2) [37 total threads]
Syscall (r7=197)    : sys_fstat64(int fd, struct stat64 *statbuf)
------------------------------------------------------------------------------
Raw Boundary        : {"reason": "urandom_operation_not_implemented", "path": "/dev/urandom", "source_sha256": "305e289ecc1d768544af71c83d58ce23ec4d232be1e7572d9d4f68f0f12188cc", "pc": 1344362390, "r7": 197, "arguments": [27, 293596024, 293596024]}
==============================================================================
```
