# Evidence Record 0075: HDMI Driver Contract and Pipe Subsystem Boundary

**Date**: 2026-11-04  
**Milestone**: 86,810,403 instructions executed (+1,043,688 instructions past 85.76M boundary); 1,844 serviced syscalls (+97 syscalls); 24 concurrent firmware threads (+4 threads); 70 open file descriptors; `/dev/hdmi` contract verified and `pipe` (`r7 = 42`) subsystem boundary reached.

---

## 1. Summary of Achievements

1. **HDMI Character Driver Contract (`/dev/hdmi`)**:
   - Evidenced in physical hardware dump `reports/a6400_hw_dump.txt` (line 196, line 288):
     - **Major: 248, Minor: 25** (`crwxrwxrwx 1 root root 248, 25 /dev/hdmi`)
     - Confirmed in `vmlinux.bin` / `devno.ko` `udif_devnodes` table at `0x3d2ba8` (`MKDEV(248, 25)`).
   - Reverse-engineered kernel module `hdmi.ko` (`firmware/.../kmod/hdmi.ko`):
     - `hdmi_dev_open` (0x7e04): state allocation (0x54 bytes), private data initialization.
     - `hdmi_dev_release` (0x7d4c): cleanup and unregistration.
     - `hdmi_dev_poll` (0x7b40): returns `0x104` (`POLLOUT | POLLWRNORM`).
     - `hdmi_dev_write` (0x7bc8): requires size $\ge$ 18 bytes (`-EMSGSIZE` if smaller).
     - `hdmi_dev_read` (0x7c54): non-blocking read returns `-EAGAIN` (`-11`) on empty queue.
     - `hdmi_dev_ioctl` (0x813c): dispatches 19 authentic `_IOWR('H', nr, 4)` commands (`0xc0044801..0xc0044813`).
   - Reverse-engineered consumer in `libInfraHdmi.so` (`HDMI::HdmiCtrlImpl`):
     - `0xc0044801`: `initialize` / `finalize` / `setMonitoringHPD`
     - `0xc0044802`: `getMonitorStatus` (writes 96 bytes `Shdmi_monitor_data`)
     - `0xc0044803`: `setPower`
     - `0xc0044804`: `setTmds`
     - `0xc0044805`: `setReso` (20 bytes)
     - `0xc0044806`: `setXvYcc` (36 bytes)
     - `0xc0044807`: `setSrcDev` (1 byte)
     - `0xc0044808`: `setAudio` (12 bytes)
     - `0xc004480b`: `setContent`
     - `0xc004480d` / `0xc004480e`: `setMonitoringHPD`
     - `0xc004480f`: `setDimension`
     - `0xc0044810`: `setVSIF`
     - `0xc0044811`: `setColorbar` (`set_colorbar_for_musashi`)
     - `0xc0044813`: `setForceStop`
   - Implemented `GuestHdmi` in `src/a6400/execution/guest_hdmi.py`.
   - Integrated into `InterpreterProbe` and `tools/research/experiment_ui_boot.py` under `--hdmi-device driver-bound`.
   - Added 8 unit tests in `tests/test_guest_hdmi.py` (all 514 unit tests passing).

2. **Execution Milestone (86.81M Instructions)**:
   - Execution advanced from 85,766,715 to **86,810,403 instructions** (+1,043,688 instructions).
   - Serviced syscalls increased from 1,747 to **1,844** (+97 serviced syscalls).
   - Open descriptors increased from 66 to **70** (including three `/dev/hdmi` file descriptors: fd 15, fd 16, fd 18, and `/dev/mem` fd 17).
   - Spawned 4 new threads, reaching **24 concurrent threads**:
     - TID 1000: `main` (blocked_futex)
     - TID 1001: `THREAD_INFRA0` (blocked_futex)
     - TID 1002: `thread_1002` (blocked_futex)
     - TID 1003: `thread_1003` (blocked_futex)
     - TID 1004: `THREAD_INFRA1` (blocked_futex)
     - TID 1005: `grm_dn_vdf_if` (blocked_uipc)
     - TID 1006: `UDATE_ASYNCSET` (blocked_futex)
     - TID 1007: `THREAD_INFRA2` (runnable)
     - TID 1008: `thread_1008` (active Sugilite GPU/display render worker)
     - TID 1009: `InfraAudioDecode` (blocked_uipc)
     - TID 1010: `UsbBusPower` (blocked_futex)
     - TID 1011: `InfraAvEffector` (blocked_uipc)
     - TID 1012: `UsbControl` (blocked_futex)
     - TID 1013: `InfraDecoder` (blocked_uipc)
     - TID 1014: `thread_1014` (`usb_event_thread`, blocked_read on `/dev/usb/event`)
     - TID 1015: `thread_1015` (blocked_futex)
     - TID 1016: `BusPower` (blocked_futex)
     - TID 1017: `InfraMovieEditor` (blocked_uipc)
     - TID 1018: `Hotplug` (blocked_futex)
     - TID 1019: `InfraMovieEncode` (blocked_uipc)
     - **TID 1020: `HDMI Msg Thread`** (blocked_uipc)
     - **TID 1021: `InfraMovieEncThm`** (blocked_uipc)
     - **TID 1022: `HDMI Dev Thread`** (running)
     - **TID 1023: `thread_1023`** (runnable)

3. **New Boundary Reached**:
   - Stopped at syscall `r7 = 42` (`pipe`) at PC `0x50296afc` (`__pipe` in `libc-2.11.2.so`).
   - Caller: `HDMI Dev Thread` (TID 1022).
   - Arguments: `r0 = 0x1817055c` (pointer to `int pipefd[2]`).
   - Next milestone: implement `sys_pipe` (`r7 = 42`) in `InterpreterProbe` with standard POSIX pipe descriptor allocation and virtual IPC pipe buffer.

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
  --hdmi-device driver-bound `
  --instructions 100000000 `
  --timeout-us 600000000 `
  --report artifacts/execution/ui-boot-hdmi-100m.json
```

---

## 3. Boundary Details

```json
{
  "interrupt": 2,
  "pc": 1344891644,
  "instruction_address": 1344891640,
  "instruction_bytes": "000000ef",
  "thumb": false,
  "svc_immediate": 0,
  "r7": 42,
  "arguments": [
    404155740,
    404155474,
    336,
    0,
    215512,
    215524,
    220920
  ]
}
```
- PC `1344891644` (`0x50296afc`) = `libc-2.11.2.so` + `0x96afc` (`__pipe`)
- Syscall `r7 = 42` = `__NR_pipe`
- Pointer `r0 = 404155740` (`0x1817055c`) points to `pipefd[2]` array.
