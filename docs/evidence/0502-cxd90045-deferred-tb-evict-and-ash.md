# E0502 — Deferred TB eviction/flush in the outer loop: implemented, no effect — fill hook already translates `0x0402F000`; the repeat is the even-PC/T-bit return quirk

Date: 2026-11-13. **Strictly offline.** No camera access, no USB, no writes. Inputs: E0414
dumps, E0416 contract, E0420–E0501 offline chain, the read-only dump set in
`artifacts/dumps/a6400-nflasha-readonly/` (full `/proc/kallsyms`).

## 0. Short answer

1. **Hook-safe deferred work is implemented [C].** Fault delivery and the `ret_to_user`
   hook only record `_pending_evict_pages` / `_pending_cputlb_flush`; the actual
   `ctl_remove_cache(page, page+0x1000)`, `_flush_cputlb()` and `_flush_tlb()` run in the
   **outer run loop** via `_apply_pending_tlb_work()` immediately before `emu_start`.
   No cache/flush call happens inside a `UC_HOOK_CODE` callback, so the E0501 regression
   (`nested emu_start` from a hook) cannot recur.
2. **The deferred work does not change the outcome [C]:** the run still ends at
   `instruction_limit` (`PC 0x6010DE20`), `pt_frame_gen = 30`, `svc_hits = 1` (`brk`),
   `serial 0 B`, with the same repeating `0x0402F666` prefetch entries. Eviction/flush is
   therefore **not** the missing piece.
3. **The fill hook already translates the page on every attempt [C]:** `e0502_fill`
   records `0x0402F000` fetch (`access 18`) → **`0x0042F000`**, `0x0402F400` →
   `0x0042F400`, repeatedly, with `TTBR0 0x1DC1C000` and `mmu=True`. So `_on_tlb_fill`
   neither rejects the page nor returns a wrong PA.
4. **Remaining root cause (narrowed) [C]/[I]:** the fault PC is **even**
   (`0x0402F666`), i.e. the fast-syscall return resumed user code through the native
   `ret_fast_syscall` `movs pc, lr` at `0x6010DEF8` with `lr = 0x0403EB16` (even) and
   `SPSR.T = 1`. Unicorn couples `CPSR.T` to the PC LSB, and a native `movs pc, lr` with
   an even target leaves the core decoding **ARM** at that address — exactly the class of
   failure already fixed for the `ret_to_user` path via `_set_pc_and_cpsr(thumb_pc(...))`.
   The fast path is the one user-return path still executed natively, so it needs the
   same enforced odd-PC/`USR|Thumb` restore.
5. **No shell yet [C]:** `svc_hits = 1`, `serial 0 B`.

## 1. Evidence

| item | value |
| --- | --- |
| deferred helper | `_apply_pending_tlb_work()` called before both user `emu_start` sites [C] |
| request sites | prefetch branch (`_pending_evict_pages`, `_pending_cputlb_flush`) and `0x6010DF34` hook (frame PC page) — flags only [C] |
| outcome | `instruction_limit` `PC 0x6010DE20`, `gen 30`, `svc 1`, `serial 0` [C] |
| fill trace | `0x0402F000` fetch → `0x0042F000`; `0x0402F400` → `0x0042F400`; `TTBR0 0x1DC1C000` [C] |
| fault PC parity | `0x0402F666` even, `CPSR.T` should be 1 → Unicorn ARM-decode quirk [C]/[I] |
| tests | suite unchanged (no API change); deferred code inert without pending work |

## 2. Implemented

* `_apply_pending_tlb_work()` (outer-loop eviction + `_flush_cputlb`/`_flush_tlb`).
* Pending-set/flush requests from the prefetch classifier and the `ret_to_user` hook.
* `e0502_fill` trace for the `0x0402F000` page and `cpsr` added to the fault
  classification dictionary.

## 3. Next step

1. **Hook `0x6010DEF8` (`ret_fast_syscall` `movs pc, lr`) like `0x6010DF64`:** perform the
   user restore explicitly (`PC = thumb_pc(lr, SPSR)`, `CPSR = SPSR`,
   `SP_usr`/`LR_usr` from the frame) or, if `lr` is even and `SPSR.T = 1`, set the odd
   target before letting the instruction run. This should stop the ARM-mode decode at
   `0x0402F666` and eliminate the repeat.
2. Re-run: expect `0x0402F666` once, then the loader's next syscalls, BusyBox
   `_start 0x0000C439`, and the live `/bin/ash` prompt over `ttyAM0`.
