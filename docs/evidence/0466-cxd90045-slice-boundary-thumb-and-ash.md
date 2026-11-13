# E0466 — Slice-boundary Thumb resume attempts at `0x6010DF64`: pending resume vs nested `emu_start`

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0465.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **Two slice-boundary Thumb-resume variants were implemented and measured [C].**
   * **(A) Pending resume:** at `0x6010DF64`, after restoring `r0..r12`, `SP`, `LR` and
     `CPSR`, the hook stores `_pending_user_resume = (thumb_pc(pending_user_lr, spsr), spsr)`
     and calls `uc.emu_stop()`; the run loop consumes the tuple, calls
     `_set_pc_and_cpsr()`, `ctl_flush_tb()` and restarts with
     `emu_start(begin = resume_pc)` (odd `0x0402E791`).
   * **(B) Nested resume:** the same restore, followed by an immediate nested
     `uc.emu_start(0x0402E791, ...)` inside the hook.
2. **Variant (A) reproduces the E0463/E0464 state [C]:** `user_entry_trace` still shows
   `0x0402E790`, `cpsr 0x30`, `thumb True`; `user_restores = 2`, `user_mode_entries = 1`,
   `kuser_hits = 3`, then `UC_ERR_INSN_INVALID` at `0x0402E798` and stop `PC = 0x0402E79C`
   — i.e. the explicit odd `emu_start(begin)` did **not** change the decode mode.
3. **Variant (B) made it worse and was reverted [C]:** the nested start produced a
   prefetch fault at `PC = 0x0` and then a kernel fault at `0x60110398`
   (`data @ 0x8`), with `user_mode_entries = 0` — so the nested `emu_start` inside the
   code hook is not a usable resume mechanism here. The code was returned to variant (A).
4. **Conclusion so far [C]/[I]:** the wrong-mode decode is not caused by the `begin`
   address alone; Unicorn's TCG translation block for `0x0402E790` is evidently cached in
   ARM mode and is reused despite `CPSR.T = 1` and an explicit odd `begin`. No shell:
   `svc_hits = 0`, `serial 0 B`.

## 1. Evidence

| item | value |
| --- | --- |
| variant A trace | `0x0402E790`, `cpsr 0x30`, `thumb True` [C] |
| variant A stop | `UC_ERR_INSN_INVALID` `0x0402E798`, stop `0x0402E79C` [C] |
| variant A counters | `user_restores 2`, `user_mode_entries 1`, `kuser_hits 3` [C] |
| variant B result | prefetch `PC 0x0`, kernel fault `0x60110398` (`data @ 0x8`), no user entry [C] |
| suite | 1556 tests, all OK [C] |

## 2. Implemented

* `_pending_user_resume` state + run-loop consumption with `_set_pc_and_cpsr`,
  `ctl_flush_tb()` and `emu_start(begin = resume_pc)` (variant A, kept).
* Variant B (nested `emu_start`) was tried and **reverted**.
* Unit test for the pending-resume default state.

## 3. Next step

1. **Invalidate the ARM-mode translation block for `0x0402E790`** before resuming:
   `ctl_remove_cache(0x0402E790, 0x0402E7A8)` (or `ctl_flush_tb()` **plus**
   `ctl_remove_cache`) while the CPU is stopped, then `emu_start(0x0402E791)`, and verify
   with the entry trace whether the first instruction is decoded as Thumb (`0x790 →
   0x794 → 0x798 mov r0,sp`).
2. If Unicorn still reuses an ARM TB, **single-step the entry** with `count=1` per
   instruction from an explicitly set `CPSR`/`PC` (each step re-initialises TCG flags),
   which is the labelled bring-up aid path.
3. Then verify `0x0402F666`/`0x04031AF0`, enable `svc_hits`, and capture the live
   `/bin/ash` prompt over `ttyAM0`.
