# E0205 — Physical Native Entry Hook Lifecycle and Four-Core Coherence Verified

## Overview and Physical Contract

This milestone fulfills **Phase 2** of the UVC/PTP roadmap: a controlled, bounded verification of the native entry hook lifecycle on the live Sony ILCE-6400 camera in **Mass Storage mode**.

The test proves on authentic camera hardware that:
1. The kernel text slot at `0x602b8844` (`usb_gadgetcore_ioctl`) can be atomically modified to branch (`0xea000000 | delta`) into the module entry wrapper and atomically restored back to the original instruction `0xe1a0c00d` (`mov ip, sp`).
2. Modification and restoration occur exclusively under an attested stop scope: all 174 threads of PID 149 (`im.elf`, sole owner of `/dev/gadgetcore` FD 82) are verified frozen in user mode (`ptrace_stop`, CPSR mode `0x10`), providing complete ingress and caller drain.
3. Multi-core cache coherence (`a6400_uvc_sync_code`) broadcasts PoU D-cache clean, I-cache invalidate, branch-predictor invalidate, and DSB/ISB across all 4 physical Cortex-A7 CPUs via `on_each_cpu(wait=1)` on both publication and retirement (`seen=0xf expected=0xf result=0`).
4. Module self-pinning (`a6400_module_self_get / put`) tracks the published lifecycle and releases cleanly on retirement.
5. All 174 threads of the camera application resume normally without crash, freeze, or hang.
6. Module unloads cleanly (`rmmod usbg_video`), restoring `/proc/modules` byte-equal to its pre-test baseline.

---

## Physical Verification Evidence

### 1. Pre- and Post-Owner Baseline
- Pre-diagnostic capture: `artifacts/analysis/uvc-ptp-owners-pre-e0205`
  - Sole `/dev/gadgetcore` owner: PID 149 (`im.elf`), FD 82, major 242 minor 1.
  - Active threads: exactly 174 threads.
  - Validated by `tools/research/validate_uvc_ptp_owner_receipts.py` (8/8 cases passed).
- Post-diagnostic capture: `artifacts/analysis/uvc-ptp-owners-post-e0205`
  - Sole `/dev/gadgetcore` owner: PID 149 (`im.elf`), FD 82, major 242 minor 1.
  - Active threads: exactly 174 threads (100% TID match).
  - Validated by `tools/research/validate_uvc_ptp_owner_receipts.py`.

### 2. Physical Execution Sequence
- Diagnostic runner: `tools/research/run_uvc_ptp_stop_diagnostics.py` with `--entry-hook`.
- Output directory: `artifacts/analysis/uvc-ptp-stop-diag-e0205`
- Module deployed: `artifacts/native/uvc-ptp-module-e0204/usbg_video_a6400_shared_candidate.ko`
  - Size: 70,356 bytes
  - SHA-256: `9cd4e166c05ba8912900497e781b02c058ae39102304d4f6fa9e2ee25558fb96`
  - Camera path: `/tmp_bt/uvc_stop_diag_20261108_205437_400924.ko`
- Freeze helper deployed: `artifacts/native/uvc-ptp-freeze-e0205/native_usb_freeze_probe.elf`
  - Size: 11,312 bytes
  - SHA-256: `efac568b9b0c020900061c6c3cd04fc8e1c0defd21453c8156675ff0c0f99499`
  - Camera path: `/tmp_bt/uvc_cpu_barrier_20261108-205441-430416`
- Results:
  - `insmod`: status 0 (allocated 256 KB coherent buffer `0x05ac0000`).
  - `mknod`: status 0 (`/tmp_bt/..._video c 248 33`).
  - `freeze_process`: 174/174 threads attached via ptrace, verified in `ptrace_stop`, user mode CPSR `0x10`.
  - Diagnostic ioctl `0xc020f025` (`A6400_UVC_ENTRY_HOOK_CYCLE`):
    - Caller drain verified: `completed=174, expected=174, error=0`.
    - Hook published at `0x602b8844` (`0xe1a0c00d` -> `branch`).
    - Cache sync 1: `[a6400_code_sync] seen=f expected=f result=0`.
    - Hook retired at `0x602b8844` (`branch` -> `0xe1a0c00d`).
    - Cache sync 2: `[a6400_code_sync] seen=f expected=f result=0`.
    - ioctl result: 0, errno: 0.
  - `freeze_resume`: 174/174 threads resumed cleanly in 1418 ms (`elapsed_ms=1418`).
  - Helper log: `ENTRY_HOOK verified_publication_cycle=1`, `END result=0 captured=174 expected=174 saved_user_regs_only=1`.
  - `TracerPid`: 0 verified in `/proc/149/status`.
  - `rmmod`: status 0 (freed coherent buffer, module unloaded).
  - Cleanup: device node and `.ko` deleted from `/tmp_bt`.
  - Module list check: `/proc/modules` byte-equal restoration verified (`module_list_restored: true`).
  - Camera debugger: PID 700 responsive throughout.

### 3. Kernel Diagnostic Log (`dmesg`)
```text
[  348.250229] [a6400_uvc] owned coherent alloc cpu=ffd80000 phys=05ac0000 size=262144
[  349.628286] [a6400_code_sync] seen=f expected=f result=0
[  349.628402] [a6400_code_sync] seen=f expected=f result=0
[  349.668942] [a6400_uvc] free_phys called (registered=0)
[  349.669792] [a6400_uvc] owned coherent free phys=05ac0000 size=262144
```

---

## Conclusions and Boundary Progression

Phase 2 is now **physically verified** on live camera hardware:
- Native entry hook publication, multi-core cache invalidation, hook retirement, and clean unload are proven safe.
- The camera kernel lowmem section mapping permits live runtime modification and restoration without MMU protection faults.
- Four-core cache synchronization executes cleanly across all active CPUs without deadlocks or missed invalidations.
- Application process `im.elf` survives the freeze-hook-sync-retire-sync-resume cycle without disruption.

We are now ready to progress to **Phase 3**: Preparation and execution of the first PC Remote mode switch and simultaneous UVC + PTP USB enumeration.
