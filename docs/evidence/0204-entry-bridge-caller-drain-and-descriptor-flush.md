# E0204 — Entry Bridge Caller Drain, Wrapper Lifetime, and Descriptor-Patch Flush

## Implementation and contract

This milestone resolves Phase 1 of the UVC/PTP transition:
1. **Descriptor-patch `flush_code` replacement**: in `tools/native_camera/uvc_ptp_native_backend.c`, replaced the older `0x60119c80` ICIALLUIS call with the physically-verified multi-core `a6400_uvc_sync_code(sites[0], sites[3] + 4)`. This guarantees PoU D-cache cleaning, I-cache invalidation, branch-predictor invalidation, and synchronous per-core DSB/ISB on all 4 CPUs across all descriptor patch operations (`bind_ep0` / `unbind_ep0`).
2. **Native entry bridge and wrapper integration**: linked `tools/native_camera/uvc_ptp_native_ioctl_entry.S` (`a6400_uvc_native_ioctl_tail`) and created `tools/native_camera/uvc_ptp_entry_hook.{c,h}`.
   - Target slot: `0x602b8844` (`usb_gadgetcore_ioctl` entry point).
   - Original instruction: `0xe1a0c00d` (`mov ip, sp`).
   - Hook instruction: unconditional branch `0xea000000 | delta` targeting `a6400_uvc_native_entry_wrapper`.
   - Tail bypass reproduces original `mov ip, sp` and `push {r4..r7, fp, ip, lr, pc}`, repairs saved PC at `sp+28` to `0x602b8850`, restores `ip`, and resumes untouched original code at `0x602b884c`.
3. **Caller drain and publication safety**:
   - Publication strictly requires `struct a6400_verified_stops` where all 174 threads of PID 149 (the sole opener of `/dev/gadgetcore`) are verified stopped in user mode (`ptrace_stop`, CPSR mode 0x10). Zero callers can be inside or approaching `usb_gadgetcore_ioctl`.
   - CAS publication swaps `0xe1a0c00d` -> `branch`.
   - Synchronous 4-core cache flush `a6400_uvc_sync_code(0x602b8844, 0x602b8848)` before stop barrier release.
4. **Active caller tracking and exclusion**:
   - `entry_guard.gate` (`struct a6400_uvc_mode_gate`) tracks concurrent callers atomically.
   - MOD claims entry guard (`a6400_uvc_guard_claim` setting `HELD 0x80000000`), blocking any native ioctl with `-16` (EBUSY) before it enters native code.
5. **Caller drain before retirement and module code lifetime**:
   - Retirement requires verified stop scope AND `entry_guard.gate.word == 0` (drain complete).
   - CAS restores `0x602b8844` to `0xe1a0c00d`.
   - Synchronous 4-core cache flush ensures no core has stale branch instructions before threads resume.
   - Module self-pinning (`a6400_module_self_get / put`): held continuously while published or in HELD error state, unpinned only after verified retirement.

## Offline validation

1. **Entry drain probe (`probe_uvc_ptp_entry_drain.py`)**:
   - **36 compiled ARM controls pass** in Unicorn simulation with original kernel image and exact ABI structures.
   - Verifies publication under scope, cached VFS target interception, stack frame preservation, active exclusion under HELD, active caller drain rejection, clean retirement, unpinning, and post-retirement direct native execution.
2. **Descriptor lease test (`build_uvc_ptp_descriptor_lease.py`)**:
   - **155 offline transaction controls pass** with new multi-core cache sync wired to backend `flush_code`.
3. **Module candidate build and audit**:
   - Built candidate module `artifacts/native/uvc-ptp-module-e0204/usbg_video_a6400_shared_candidate.ko`: **70,356 bytes**, SHA-256 `9cd4e166c05ba8912900497e781b02c058ae39102304d4f6fa9e2ee25558fb96`.
   - Exactly **55 verified non-GPL kernel imports** (zero GPL-only imports).
   - **101 compiled ARM module audit controls pass** (`tools/research/audit_uvc_ptp_module.py`).
4. **Project test suite**:
   - All **605 project tests pass**.

## Status and next boundary

Phase 1 is now complete offline. The entry bridge, caller drain, and wrapper lifetime contracts are fully satisfied and verified, and descriptor-patch cache sync is updated.

Next step: **Phase 2 — Limited physical hook test in Mass Storage**. Verify the entry hook publication, native passthrough, MOD exclusion, retirement, and cleanup on the physical camera in Mass Storage mode before considering PC Remote mode switching.
