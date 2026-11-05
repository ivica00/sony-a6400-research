# Evidence 0077: `/dev/cec` Driver Contract and 87.95M Instruction Milestone

**Date**: 2026-11-04
**Status**: Verified
**Test Suite**: 525 passing unit tests

---

## 1. Executive Summary

Following the `sys_pipe` (`r7 = 42`) and `sys_poll` (`r7 = 168`) implementation (Evidence 0076), `THREAD_INFRA2` (TID 1007) authenticated `/usr/kmod/cec.ko` (79,248 bytes) via `init_module` and stopped at `open("/dev/cec", O_RDWR)` at 86,941,990 instructions.

In this milestone:
1. **`/dev/cec` Driver Contract (`src/a6400/execution/guest_cec.py`)**:
   - Confirmed `/dev/cec` device numbers from `devno.ko` (`udif_devnodes` entry 47: `major = 248`, `minor = 27`, `count = 1`) and live hardware telemetry (`reports/a6400_hw_dump.txt`, `L197: 248 cec`).
   - Reverse-engineered `cec.ko` file operations:
     - `cec_dev_open` (`0x5d28`): allocates 0x50-byte state struct, initializes RT mutex, spinlock, waitqueue, and calls `cec_core_open()`.
     - `cec_dev_release` (`0x5c78`): calls `cec_core_set_connect(0)` and `cec_core_release()`.
     - `cec_dev_poll` (`0x5a6c`): returns `0x104` (`POLLOUT | POLLWRNORM`) when the RX queue is empty; ORs `0x41` (`POLLIN | POLLRDNORM`) when RX events are queued.
     - `cec_dev_write` (`0x5af4`): requires `count >= 28` (`0x1c`, returning `-EMSGSIZE = -90` if `count <= 0x1b`), copies 28 bytes and calls `cec_core_set_device_status()`.
     - `cec_dev_read` (`0x5b80`): pops queued RX event or returns `-EAGAIN` (`-11`) if empty.
     - `cec_dev_ioctl` (`0x6074`): 10 `_IOWR('C', nr, size)` commands:
       - `0xc0044301`: `cec_core_set_connect` (user pointer to 4-byte int)
       - `0xc0044302`: `cec_core_set_power` (4-byte int)
       - `0xc0044303`: `cec_core_set_status` (4-byte int)
       - `0xc0044304`: `cec_core_set_request` (4-byte int)
       - `0xc0114304`: `cec_core_set_send` (user pointer to 17-byte CEC frame)
       - `0xc0084305`: `cec_core_set_register` (user pointer to 8-byte register struct, R/W)
       - `0xc0044306`: `cec_core_set_cycle_time` (4-byte int)
       - `0xc004430a`: `cec_core_set_key_interval` (4-byte int)
       - `0xc004430b`: `cec_core_get_abort_flag` (writes 4-byte abort flag to user arg)
       - `0xc001430e`: `cec_core_set_lgc_addr` (1-byte logical address)

2. **Execution Milestone (87.95M Instructions)**:
   - Execution advances from 86,941,990 to **87,946,134 instructions** (+1,004,144 instructions).
   - Serviced syscalls increase from 1,867 to **2,185** (+318 serviced syscalls).
   - Open file descriptors increase from 71 to **74** (opening `/dev/cec` on `fd = 21`, `fd = 22`, `fd = 23`).
   - Concurrent threads increase from 24 to **27** (+3 new threads):
     - Named `TID 1023` -> `InfraStillEncode`
     - Spawned and named `TID 1024` -> `CEC Msg Thread` (executes `CEC_IOCTL_SET_STATUS 0xc0044303` and blocks on `poll(fds=[21])`)
     - Spawned and named `TID 1025` -> `InfraAvbbcIf`
     - Spawned `TID 1026` (`thread_1026`)

3. **New Boundary Reached**:
   - Stopped at `87,946,134` instructions in `TID 1004 (THREAD_INFRA1)` on UIPC queue `0x003e014d` (`Backup` service):
     - `{"reason": "unsupported_backup_operation", "operation": 5, "words": [5, 0, 2, 4063565, 0, 0, 1408559340, 1408559600, ...]}`
   - Next milestone: inspect `libbackup.so` / `backup.ko` for Backup service operation `5` (`Backup_get_datasize` / `Backup_read_multi` / `Backup_sync`) on queue `0x003e014d`.

---

## 2. BootLogger Real-Time Trace Excerpt (86.81M -> 87.95M)

```text
[BOOT  86.81M | PIPE ] Created pipe:[1] -> read_fd=19, write_fd=20 [TID 1022 HDMI Dev Thread]
[BOOT  86.92M | POLL ] Thread TID 1022 (HDMI Dev Thread) blocked on poll(fds=[16, 19]) -> switched to TID 1007
[BOOT  86.93M | KMOD ] Opened kernel module /usr/kmod/cec.ko (fd=21) [TID 1007 THREAD_INFRA2]
[BOOT  86.94M | KMOD ] Authenticated & initialized /usr/kmod/cec.ko (79,248 bytes) -> 0 [TID 1007 THREAD_INFRA2]
[BOOT  86.94M | DEV  ] Opened device /dev/cec (major=248, minor=27) -> fd=21 [TID 1007 THREAD_INFRA2]
[BOOT  86.94M | DEV  ] Opened device /dev/cec (major=248, minor=27) -> fd=22 [TID 1007 THREAD_INFRA2]
[BOOT  87.01M | DEV  ] Opened device /dev/cec (major=248, minor=27) -> fd=23 [TID 1007 THREAD_INFRA2]
[BOOT  87.01M | IOCTL] First cec ioctl 0xc0044301 (_IOWR('C', 0x01, 4)) -> 0 [TID 1007 THREAD_INFRA2]
[BOOT  87.02M | THRD ] Spawned thread TID 1024 (parent=TID 1007 THREAD_INFRA2, total=25)
[BOOT  87.02M | THRD ] Named thread TID 1023 -> "InfraStillEncode"
[BOOT  87.02M | THRD ] Spawned thread TID 1025 (parent=TID 1004 THREAD_INFRA1, total=26)
[BOOT  87.02M | THRD ] Named thread TID 1024 -> "CEC Msg Thread"
[BOOT  87.11M | THRD ] Spawned thread TID 1026 (parent=TID 1007 THREAD_INFRA2, total=27)
[BOOT  87.91M | IOCTL] First cec ioctl 0xc0044303 (_IOWR('C', 0x03, 4)) -> 0 [TID 1024 CEC Msg Thread]
[BOOT  87.91M | POLL ] Thread TID 1024 (CEC Msg Thread) blocked on poll(fds=[21]) -> switched to TID 1008
[BOOT  87.91M | THRD ] Named thread TID 1025 -> "InfraAvbbcIf"
```
