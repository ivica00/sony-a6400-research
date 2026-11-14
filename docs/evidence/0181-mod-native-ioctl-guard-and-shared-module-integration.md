# E0181 — MOD ioctl Guard Integration and Verified Physical Lifecycle of Shared Module

Date: 2026-11-08. Camera is connected in Mass Storage mode. All writes on the camera are strictly limited to RAM `/tmp_bt`. Debugger PID 703 preserved; all 605 emulator tests pass.

---

## 1. Integration of MOD ioctl Guard into Kernel Module

Continuing from E0174 (atomic access gate), E0175 (wrapper of original ioctl), and E0180 (resolution of module references and symbols), formal integration of the protective wrapper into the kernel module `usbg_video_a6400_shared_candidate.ko` was completed:

1. **Removal of Ad-Hoc Flag**:
   - In `tools/native_camera/uvc_ptp_module_shim.c`, the local simple variable `static volatile unsigned int gate;` was removed.
   - Formal headers `uvc_ptp_mode_gate.h` and `uvc_ptp_ioctl_guard.h` were included.
   - Structure defined:
     ```c
     static struct a6400_uvc_ioctl_guard native_guard = {
         .gate = {0},
         .original = (a6400_native_ioctl_fn)0x602b8844u,
         .fault = 0
     };
     ```
   - Wrapper function exposed for the original VFS gadgetcore entry:
     ```c
     long a6400_uvc_native_gadgetcore_ioctl(void *file, unsigned int command, unsigned long arg)
     {
         return a6400_uvc_guard_dispatch(&native_guard, file, command, arg);
     }
     ```

2. **Atomic Exclusivity During MOD Operations**:
   - Operations `a6400_uvc_shared_ioctl` and `a6400_uvc_shared_release` call `a6400_uvc_guard_claim(&native_guard)`. If an original ioctl is in progress (`count >= 1`), claim returns `-EBUSY` (`-16`), preventing concurrent state modification.
   - While MOD holds the transaction (`HELD` bit `0x80000000`), any call through `a6400_uvc_native_gadgetcore_ioctl` is immediately rejected with `-EBUSY` without touching original kernel code.
   - Registration hooks (`a6400_uvc_shared_register_hook` and `unregister_hook`) strictly check whether the gate is in the `HELD` state before modifying descriptor pointers.
   - Upon completion of the operation, `a6400_uvc_guard_release(&native_guard)` is called, atomically returning the gate to the zero state.

3. **Builder and C Compilation Additions**:
   - `tools/research/build_uvc_composite_module.py` was updated to include `uvc_ptp_mode_gate.c` and `uvc_ptp_ioctl_guard.c` in compiling the shared candidate.
   - ARMv7 softfp compilation without libc dependencies adds exactly 0 new external symbols, since the modules use only built-in GCC atomic intrinsics (`__sync_bool_compare_and_swap`, `__sync_val_compare_and_swap`).

---

## 2. Static and Emulation Verification

1. **Built Candidate**:
   - Path: `artifacts/native/uvc-ptp-module-e0181/usbg_video_a6400_shared_candidate.ko`.
   - Size: **60,084 bytes**.
   - SHA-256: `be567fcd9db143190b41c1dbb07a5917cb6f348540a12d9b9a8f0103a0f197d1`.
   - Undefined symbols count: exactly **49**, all 100% confirmed in the export table of kernel `3.0.27_nl-rt106+`. Zero GPL-only imports.

2. **Unicorn ARM Emulation Tests**:
   - Updated `tools/research/audit_uvc_ptp_module.py` with mapping of original ioctl address `0x602b8844` and testing the new contracts.
   - All **33 checks pass** (`offline_module_audit_passed`):
     - `concurrent-release-rejected`: when a native call is in progress (`count=1`), release returns `-EBUSY`.
     - `concurrent-ioctl-rejected`: when a native call is in progress, ioctl returns `-EBUSY`.
     - `native-ioctl-dispatch-forwarded`: when the gate is free, the original call is forwarded to `0x602b8844`.
     - `native-ioctl-held-rejected`: when MOD holds the transaction (`HELD`), the original call is rejected with `-EBUSY`.
   - Standalone tests of `build_uvc_ptp_mode_gate.py`: all **42 checks pass**.

---

## 3. Physical Verification on Live Sony ILCE-6400 Camera

A dedicated automated verification tool `tools/research/run_uvc_ptp_module_lifecycle.py` was created, executing the complete load and unload lifecycle while generating verification logs:

1. **Preflight and Transfer**:
   - Debugger PID 703 active in MSC mode.
   - `/proc/modules` before test is 2,349 bytes; module `usbg_video` is not present.
   - Candidate transferred to `/tmp_bt/uvc_shared_lifecycle_20261108-162333-300861.ko` with automatic readback verification (SHA-256 byte-equal).

2. **Physical `insmod`**:
   - `insmod` command returns status `0` and flags `0`.
   - `/proc/modules` confirms successfully loaded module:
     ```text
     usbg_video 47073 0 - Live 0x5f59b000 (P)
     ```
   - Video node was not opened and activation ioctl was not called (safe probe without taking over the USB line).

3. **Physical `rmmod`**:
   - `rmmod usbg_video` command returns status `0` and flags `0`.
   - `/proc/modules` after removal is identical to initial state (`modules-after.txt` byte-equal to `modules-before.txt`, 2,349 bytes).
   - Temporary `.ko` file in `/tmp_bt` immediately deleted.

4. **System Integrity After Cycle**:
   - Debugger PID 703 fully functional and responsive before and after the cycle.
   - Process `im.elf` (PID 149): `State: S (sleeping)`, `TracerPid: 0`, `Threads: 175` — no crashes or anomalies.
   - All logs stored in `artifacts/hardware/uvc-ptp-module-lifecycle-e0181/manifest.json`.

---

## 4. Regression Verification

* All **605 emulator tests** pass in 17.997 s (`OK`).
* All writes on the physical camera were executed exclusively in RAM `/tmp_bt`.
