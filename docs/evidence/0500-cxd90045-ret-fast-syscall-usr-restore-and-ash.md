# E0500 — `ret_fast_syscall` restore fixed: `ARM_pc = 0x0403EB16` paired with `ARM_sp = 0x5E864C04`; `VA 0x5E865030` is gone

Date: 2026-11-13. **Strictly offline.** No camera access, no USB, no writes. Inputs: E0414
dumps, E0416 contract, E0420–E0499 offline chain, the read-only dump set in
`artifacts/dumps/a6400-nflasha-readonly/` (full `/proc/kallsyms`).

## 0. Short answer

1. **Root cause of the skipped `pop` found and fixed [C].** `_svc_return_address()` was
   probing the SVC bytes with `uc.mem_read`, which fails from inside a `UC_HOOK_INTR`
   callback for user VAs; the helper then fell back to `pc + 2` and produced
   `ARM_pc = 0x0403EB18` instead of `0x0403EB16`, so the kernel's fast return landed one
   instruction late and skipped `pop {r7, pc}`. The probe now uses the guest page-table
   read (`_read_user16/32`, only when `_cached_ttbr0` is set to avoid a nested MRC) with a
   `uc.mem_read` fallback.
2. **`ret_fast_syscall` is not executed natively any more [C].** The `vector_swi` frame at
   `0x6010DEC0` now contains exactly the paired values:
   `ARM_sp (+0x34) = 0x5E864C04`, `ARM_lr (+0x38) = 0x0403E98D`,
   **`ARM_pc (+0x3C) = 0x0403EB16`**, `ARM_cpsr (+0x40) = 0x600000F0`, `r0 = 0x55000`
   (new `brk` value). The banked `stmdb r8,{sp,lr}^` at `0x6010DFB0` is emulated
   single-shot (`sp_usr = 0x5E864C04`, `lr_usr = 0x0403E98D`), so the fast-syscall
   `ldmdb`/`movs pc,lr` restores the user frame atomically.
3. **`VA 0x5E865030` is gone [C].** With `ARM_pc = 0x0403EB16` the `pop {r7, pc}` and the
   `__brk` wrapper epilogue (`0x0403E98C..0x0403E9A2`) execute; the previous bogus
   `0x0403EB20` resume and the invalid-stack-page read no longer appear.
4. **New frontier, much deeper [C]:** the run now advances through the loader to frame
   generation **30** (up from 15) and stops at `instruction_limit` with
   `PC = 0x6010DE20` (kernel fast-return path) while the fault classification shows
   repeated **`0x0402F666` prefetch** faults (`ld-2.11.2.so` entry page). `svc_hits = 1`
   (`brk`), `serial 0 B` — no shell yet.

## 1. Evidence

| item | value |
| --- | --- |
| probe bug | `uc.mem_read` in INT hook failed → fallback `pc+2` → `ARM_pc = 0x0403EB18` [C] |
| fix | page-table probe `_read_user16/32` (+ `uc.mem_read` fallback) [C] |
| frame at `0x6010DEC0` | `+0x34 = 0x5E864C04`, `+0x38 = 0x0403E98D`, `+0x3C = 0x0403EB16`, `+0x40 = 0x600000F0`, `r0 = 0x55000` [C] |
| banked stmdb | single-shot; `sp_usr = 0x5E864C04`, `lr_usr = 0x0403E98D` [C] |
| progress | `pt_frame_gen = 30` (E0499: 15), `rec = 1`, `restores = 8` [C] |
| new fault | repeated `0x0402F666` prefetch; stop `instruction_limit` `PC 0x6010DE20` [C] |
| shell | `svc_hits = 1`, `serial 0 B` [C] |
| tests | `_svc_return_address` test still green; suite 1727 OK |

## 2. Implemented

* `_svc_return_address`: guest-page-table probing (with nested-MRC guard).
* Restored the `_emulate_vector_stmdb()` helper (it had been dropped by an earlier
  range replacement; the missing method made the vector `stmdb` execute natively and stop
  with `UC_ERR_EXCEPTION` at `0x6010DFB0`).
* `e0500_frames` dump hooks proving the paired frame values at `0x6010DEC0`.

## 3. Next step

1. Trace the repeated `0x0402F666` prefetch faults: is the loader re-entering `_start`
   code (a loop) or is the page translation stale again? Dump `pt_regs`, TTBR0 and the
   page PTE, then re-check the demand-page delivery for page `0x0402F000`.
2. Then continue the syscall chain (`uname`, `open`, `mmap2`, `set_tls`, `write`, `read`),
   BusyBox `_start 0x0000C439`, and the live `/bin/ash` prompt over `ttyAM0`.
