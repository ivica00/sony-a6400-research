# Evidence 0076: Anonymous Pipe (`sys_pipe`), Event Loop Polling (`sys_poll`), and `/dev/cec` Boundary (86.94M Instructions)

**Date**: 2026-11-04
**Status**: Verified
**Test Suite**: 521 passing unit tests

---

## 1. Executive Summary

Following the `/dev/hdmi` driver contract (Evidence 0075), execution stopped at 86,810,403 instructions in `HDMI Dev Thread` (TID 1022) at `sys_pipe` (`r7 = 42`).

Using the newly created `BoundaryAnalyzer` (`tools/camera_link.py`), we resolved the caller to `HDMI::DeviceThread<HDMI::HDMIPlatform, HDMI::OSALLog<154u, 1>>::_run()` (`0x3f818` in `/usr/lib/libInfraHdmi.so`) and `HDMI::_poll` (`0x3e53c`):

1. **`HDMI::DeviceThread::_run()` Self-Pipe & Poll Architecture**:
   - At `0x3f834`, `DeviceThread::_run()` calls `pipe(r7 + 0x74)` (`sys_pipe`, `r7 = 42`) to allocate a self-pipe (`[read_fd, write_fd]`) used to wake the device thread on shutdown (`DeviceThread::exit()`).
   - It stores `read_fd` at `this + 0xc` and `write_fd` at `this + 0x10`.
   - At `0x3f88e..0x3f98e`, it constructs a 2-element `pollIOBase` array for:
     - Element 0: `/dev/hdmi` (`fd = 16`, polling for `POLLIN = 0x0001`).
     - Element 1: `pipe:[1]` (`read_fd = 19`, polling for `POLLIN | POLLERR | POLLHUP`).
   - At `0x3f98e`, it calls `HDMI::_poll(items, 2, -1, ::poll)` (`sys_poll`, `r7 = 168`, `nfds = 2`, `timeout = -1`).
   - Because `/dev/hdmi` reports `0x104` (`POLLOUT | POLLWRNORM`, no `POLLIN` pending) and `pipe:[1]` is empty (`revents = 0`), `sys_poll` blocks `TID 1022 (HDMI Dev Thread)` on `fds = [16, 19]` via `GuestThreads.handle_fd_wait` and switches context to `TID 1007 (THREAD_INFRA2)`.

2. **GuestPipe & `sys_poll` Implementation (`src/a6400/execution/guest_pipe.py`)**:
   - Created `GuestPipe` managing anonymous FIFO channels (`create`, `read`, `write`, `poll`, `close_end`).
   - Wired `sys_pipe` (`r7 = 42`), `sys_poll` (`r7 = 168`), and pipe `read`/`write`/`close` into `InterpreterProbe`, including automatic wakeup of blocked readers/pollers via `GuestThreads.handle_fd_wake`.
   - Integrated `BootLogger` and `BoundaryAnalyzer` (`tools/camera_link.py`) into `tools/research/experiment_ui_boot.py` for real-time milestone streaming and automatic post-stop symbol & ground-truth diagnosis.

3. **Execution Milestone (86.94M Instructions)**:
   - Execution advances from 86,810,403 to **86,941,990 instructions** (+131,587 instructions).
   - Serviced syscalls increase from 1,844 to **1,867** (+23 serviced syscalls).
   - Open file descriptors increase from 70 to **71** (plus `pipe:[1]` `read_fd = 19`, `write_fd = 20`).
   - After `TID 1022 (HDMI Dev Thread)` blocks on `poll(fds=[16, 19])`, `TID 1007 (THREAD_INFRA2)` resumes, opens `/usr/kmod/cec.ko` (79,248 bytes, `fd = 21`), authenticates and initializes it via `init_module` (`r7 = 128`), and advances to `open("/dev/cec", O_RDWR)`.

4. **New Boundary Reached (`/dev/cec`)**:
   - Stopped at `open("/dev/cec", O_RDWR)` (`r7 = 5`, `flags = 2`) in `TID 1007 (THREAD_INFRA2)`.
   - `BoundaryAnalyzer` automatically matched `/dev/cec` in `reports/a6400_hw_dump.txt` (`L197: 248 cec`, `L279: cec 53250 3`, `L468: [cec_state]`), and `devno.ko` (`udif_devnodes`) confirms `/dev/cec` is character device **major 248, minor 27**.

---

## 2. BootLogger Real-Time Trace Excerpt (85.69M -> 86.94M)

```text
[BOOT  85.69M | KMOD ] Opened kernel module /usr/kmod/hdmi.ko (fd=15) [TID 1007 THREAD_INFRA2]
[BOOT  85.70M | KMOD ] Authenticated & initialized /usr/kmod/hdmi.ko (238,744 bytes) -> 0 [TID 1007 THREAD_INFRA2]
[BOOT  85.77M | DEV  ] Opened device /dev/hdmi (major=248, minor=25) -> fd=15 [TID 1007 THREAD_INFRA2]
[BOOT  85.78M | DEV  ] Opened device /dev/hdmi (major=248, minor=25) -> fd=16 [TID 1007 THREAD_INFRA2]
[BOOT  86.45M | DEV  ] Opened device /dev/mem (major=1, minor=1) -> fd=17 [TID 1007 THREAD_INFRA2]
[BOOT  86.54M | DEV  ] Opened device /dev/hdmi (major=248, minor=25) -> fd=18 [TID 1007 THREAD_INFRA2]
[BOOT  86.55M | IOCTL] First hdmi ioctl 0xc0044801 (_IOWR('H', 0x01, 4)) -> 0 [TID 1007 THREAD_INFRA2]
[BOOT  86.60M | THRD ] Spawned thread TID 1020 (parent=TID 1007 THREAD_INFRA2, total=21)
[BOOT  86.60M | THRD ] Named thread TID 1019 -> "InfraMovieEncode"
[BOOT  86.69M | THRD ] Spawned thread TID 1021 (parent=TID 1004 THREAD_INFRA1, total=22)
[BOOT  86.70M | THRD ] Named thread TID 1020 -> "HDMI Msg Thread"
[BOOT  86.75M | THRD ] Spawned thread TID 1022 (parent=TID 1007 THREAD_INFRA2, total=23)
[BOOT  86.75M | THRD ] Named thread TID 1021 -> "InfraMovieEncThm"
[BOOT  86.81M | THRD ] Spawned thread TID 1023 (parent=TID 1004 THREAD_INFRA1, total=24)
[BOOT  86.81M | THRD ] Named thread TID 1022 -> "HDMI Dev Thread"
[BOOT  86.81M | PIPE ] Created pipe:[1] -> read_fd=19, write_fd=20 [TID 1022 HDMI Dev Thread]
[BOOT  86.92M | POLL ] Thread TID 1022 (HDMI Dev Thread) blocked on poll(fds=[16, 19]) -> switched to TID 1007
[BOOT  86.93M | KMOD ] Opened kernel module /usr/kmod/cec.ko (fd=21) [TID 1007 THREAD_INFRA2]
[BOOT  86.94M | KMOD ] Authenticated & initialized /usr/kmod/cec.ko (79,248 bytes) -> 0 [TID 1007 THREAD_INFRA2]
```
