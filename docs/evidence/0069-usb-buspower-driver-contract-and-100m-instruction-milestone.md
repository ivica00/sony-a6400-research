# Evidence 0069: USB Bus Power Driver Contract and 100 Million Instruction Milestone

## Context & Objectives

Following Evidence 0068 (GPIO contract implementation and module loader verification), firmware execution had loaded kernel modules `/usr/kmod/usbg_buspower.ko`, `/usr/kmod/usb_darwin.ko`, and `/usr/kmod/usb_buspwr.ko`, reaching `libUsbBusPower.so::_ZN11UsbBusPower16OpenResourceFileEv` and stopping at `open("/dev/usb/buspwr", O_RDWR)` with `unsupported_filesystem` at 81,719,231 instructions.

The goal was to:
1. Establish the authentic Sony `/dev/usb/buspwr` driver contract (major 248, minor 13).
2. Implement `GuestUsbBusPower` with strict user memory task limits (`TASK_SIZE <= 0x5f000000`).
3. Verify comprehensive unit test coverage and regression freedom.
4. Advance the main process (`im.elf`) boot execution past 81.71M instructions and observe the resulting firmware behavior.

## Investigation & Reverse Engineering

### 1. Device Node and Driver Interface
- Character device node: `/dev/usb/buspwr`
- Device numbers: Major 248 (0xf8), Minor 13 (0x0d)
- Confirmed by:
  - `nflasha7` inode 240 (character device `c 248 13`)
  - `devno.ko` offset `0x1d0`: `"usb/buspwr"` -> `0xf8`, `0x0d`
  - `/usr/kmod/usb_buspwr.ko` data section relocations: `usb_buspwr_fops_open`, `usb_buspwr_fops_close`, `usb_buspwr_fops_ioctl` registered via `udif_cdev_register`.

### 2. Disassembly of `libUsbBusPower.so` and `usb_buspwr.ko`
- `_ZN11UsbBusPower16OpenResourceFileEv` (`0x3438`):
  Calls `open("/dev/usb/buspwr", O_RDWR)` (fd stored at `this + 0x58`).
- Methods issue ioctl commands with base `0xf200`:
  - `0xf200`: `SetSuspendEnable`
  - `0xf201`: `SetSuspendDisable`
  - `0xf202`: `SetCurrentLimit100mA`
  - `0xf203`: `SetCurrentLimit500mA`
  - `0xf204`: `SetChargingEnable`
  - `0xf205`: `SetChargingDisable`
  - `0xf206`: `StartNotifyEvent`
  - `0xf207`: `StopNotifyEvent`
  - `0xf209`: `GetCurrentPortType` (writes uint32 `port_type` at pointer)
  - `0xf20a`: `GetCurrentBattState` (writes uint32 `batt_state` at pointer)
  - `0xf20c`: `SetPortState` (command 61964)
- Disassembly of `usb_buspwr_fops_ioctl` in `usb_buspwr.ko`:
  - Jump table dispatches commands from `0xf200` to `0xf220` (`sub r3, r5, #0xf200; cmp r3, #0x20`).
  - Known commands in range return 0; out-of-range commands return `-EINVAL` (-22).

## Implementation

1. **`src/a6400/execution/guest_usb_buspower.py`**:
   - `GuestUsbBusPower`:
     - Tracks device state (`suspend_enabled`, `charging_enabled`, `current_limit_ma`, `notify_events_enabled`, `port_type`, `batt_state`).
     - Dispatches ioctl commands in authentic range `[0xf200, 0xf220]`.
     - Strictly enforces task limit `arg < 0x5f000000` on pointer arguments.
2. **`src/a6400/execution/interpreter_probe.py`**:
   - Added `/dev/usb/buspwr` path checking in `sys_open` with device number `[248, 13]`.
   - Added `usb_buspower` dispatch in `sys_ioctl`.
   - Added `usb_buspower` cleanup in `sys_close`.
3. **`tools/research/experiment_ui_boot.py`**:
   - Added `--usb-buspower-device` argument (`driver-bound` / `stop`).
4. **Unit Tests (`tests/test_guest_usb_buspower.py`)**:
   - 10 new unit tests covering open, close, bounds checks, suspend controls, charging controls, and ioctl dispatch.
   - All 486 tests in the test suite pass cleanly (16.059s).

## Boot Experiment Execution & Results

Executed:
```powershell
python -m tools.research.experiment_ui_boot \
  --argument i \
  --stimulus none \
  --urandom-open \
  --urandom-entropy deterministic \
  --tmp-overlay experimental-empty \
  --proc-overlay experimental-empty \
  --stream-device image-driver \
  --regular-inode-rdev \
  --readonly-image-times \
  --backup-service preset-backed \
  --graphics-service authentic-grm \
  --null-page read-zero \
  --madvise-dontneed \
  --gles-device kernel-bound \
  --gpio-device driver-bound \
  --kmod-service verified-image \
  --usb-buspower-device driver-bound \
  --instructions 100000000 \
  --timeout-us 600000000 \
  --report artifacts/execution/ui-boot-buspower-bound-100m.json
```

### Key Milestones Achieved:
1. **Instruction Budget Exhaustion**:
   - Process executed **100,000,000 instructions** without hitting an unhandled filesystem, memory, or syscall boundary.
   - Status: `instruction_budget_exhausted`.
2. **Massive Syscall Servicing**:
   - **1,013,768** total syscalls serviced!
   - 112 opens, 129 mmap2 allocations, 67 mprotect calls, 10 thread clones, 19 futex operations, 3 module loads.
3. **USB Bus Power Operations Serviced**:
   - `open("/dev/usb/buspwr", O_RDWR)` -> fd 12
   - `ioctl(12, 0xf20c, 0x11800000)` (`SetPortState`) -> returned 0.
4. **Authentic Firmware Diagnostic Output**:
   - Emitted stderr: `!!! GLES Vecgen disabled.`
5. **Thread Concurrency & Active GPU Worker**:
   - 11 active guest threads:
     - `1000: main` (blocked_futex)
     - `1001: THREAD_INFRA0` (blocked_futex)
     - `1002: thread_1002` (blocked_futex)
     - `1003: thread_1003` (blocked_futex)
     - `1004: THREAD_INFRA1` (blocked_futex)
     - `1005: grm_dn_vdf_if` (blocked_uipc)
     - `1006: UDATE_ASYNCSET` (blocked_futex)
     - `1007: THREAD_INFRA2` (blocked_futex)
     - `1008: thread_1008` (state: running) - active GPU/display worker thread running `ModelYuvMuteToInstance` state machine in `libObj.so`.
     - `1009: thread_1009` (runnable)
     - `1010: thread_1010` (runnable)
6. **Continuous Sugilite GLES Rendering Pipeline**:
   - Thread 1008 executed over 1,012,670 authentic `GLES_GET_RESOURCE_SUB` (`0xc004820d`) queries, semaphores (`0xc0048211`, `0xc0048212`), and power queries (`0x8004820a`) on `/dev/dmpgles2`.

## Next Steps
1. Investigate the `ModelYuvMuteToInstance` state transitions in TID 1008:
   - Identify the condition that advances `ModelYuvMute` from its query loop to frame rendering and surface presentation.
2. Connect the verified physical SD card media pipeline (`E:\` ADMA2 transfer bridge) into the userland `mcmn_drv` / `libInfraMediaDetect.so` / `libInfraMediaMount.so` services.
3. Keep physical SD `E:\` strictly read-only.
