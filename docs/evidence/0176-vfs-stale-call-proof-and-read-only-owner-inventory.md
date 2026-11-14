# E0176 — Already Loaded VFS Call and Read-Only USB Owner Inventory

Date: 2026-11-08. Continuation of E0175. No hook installation, payload transfer, USB mode change, or writes to the camera.

## Original VFS Contract

`tools/research/probe_uvc_ptp_vfs_publication.py` SHA-verifies the original kernel and executes `vfs_ioctl` at `0x601ce2b0`. The original code reads `file+0x10`, then `file_operations+0x20` at `0x601ce2cc`, and calls the loaded pointer via `BLX r3` at `0x601ce2d8`.

In an explicit interleaving fixture, execution stops before `BLX`, after loading the old target. The test changes the slot to the new target and resumes the original CPU context. The call goes to the old target; only the next original VFS call uses the new target. File/fops are fixture objects, and targets are explicit return recorders; they do not represent a physical hook or Sony configuration change.

**10 checks pass**. Report: `artifacts/analysis/uvc-ptp-publication-e0176/manifest.json`. Passing file/command/argument and returning the result were also confirmed. Replacing a single pointer does not by itself cover an already-loaded call. The fact that the wrapper's new entry count is zero also does not count such an old call.

## Exact Original Device

The original init devnode reference was verified: literal `0x604a5988` points to record `0x604dab9c`; the name at `+0x18` is `usb/gadgetcore`, and fields `+0x1e/+0x20/+0x22` give major **242**, minor **1**, count **1**. This is not video node `248:33`.

## Built Read-Only Tool

`tools/native_camera/uvc_ptp_owner_inventory.c` was built into `artifacts/native/uvc-ptp-owner-inventory-e0176/uvc_ptp_owner_inventory`, **3376 bytes**, SHA-256 `38aede0fa7969b3aa7119c155c884d77c93b15d9062ff47a08bbaf5240ebd2f7`.

The freestanding ARMv7 softfp ELF has no libc/interpreter dependency. It uses only read-only `open`, `getdents64`, `stat64`, `close`, stdout `write`, and `exit`. It first checks `/dev/usb/gadgetcore` as character `242:1`, then searches open FDs in `/proc` by device number, and lists the threads of the owner process. It does not use `readlink` name as proof of FD identity, does not stop threads, and does not write files. `writes=0` in its protocol means it does not modify files/device; it sends a text report to stdout.

The result is **observational=1**, even when there are no errors. Vanished FD/process or malformed directory record report an error; there are limits on the number of processes, FDs, and threads. Observing the owner is not an atomic snapshot nor proof that a new process cannot open the device.

The first build was rejected due to the compiler's division helper. The final source converts numbers without runtime division and does not need libgcc/libc. There is no `PT_INTERP` in the ELF. The tool was neither transferred nor run on the camera.

## Tool Verification

`tools/research/audit_uvc_ptp_owner_inventory.py` executes the real compiled ARM tool with explicit proc/stat syscall fixtures. **23 checks pass**: exact owner by rdev, its threads, final summary, closing directories, wrong node before proc read, unavailable proc, malformed dirent, and vanished FD with incomplete result. Every allowed syscall is checked; `ptrace`, `kill`, `ioctl`, and write-open are not permitted.

Manifests are in `artifacts/native/uvc-ptp-owner-inventory-e0176/manifest.json` and `artifacts/analysis/uvc-ptp-owner-inventory-e0176/manifest.json`. Proc and stat data are explicit test fixtures, not data from the current camera.

## Current Accessibility

A read-only attempt `python -m tools.camera_debugger info` returned: `Expected one existing MSC/MTP camera; found 0. No mode switch attempted.` In the current PC Remote mode, that existing debugger channel is unavailable. This is not a claim that Windows does not see the camera; E0173 separately read the PC Remote USB descriptors.

Therefore, there is no live owner list or proc state. Existing `native_freeze.h` applies only to PID149 and does not by itself prove coverage of all owners of the gadgetcore device. It must not be used as universal confirmation that all old ioctl calls have finished.

## Next Integration Condition

Safe deployment must cover real device owners, already-started VFS entries, wrapper lifetime, and independent gadget/EP0 callbacks. The inventory is prepared for the read-only part of that procedure, while MOD gate/wrapper E0174/E0175 remain outside the production module. No unsafe pointer swap was installed and activation readiness was not declared. E0164 remains unloaded and `physical_test_ready:false`.
