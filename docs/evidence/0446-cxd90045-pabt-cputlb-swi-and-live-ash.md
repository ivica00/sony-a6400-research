# E0446 — Prefetch-abort CPUTLB flush, `0x0402F000` PTE verification and the SWI gate

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0445.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **Prefetch-abort page installs now get the real SoftMMU flush [C].** The
   `ret_to_user` hook flushes whenever `_pte_dirty` is set (both Prefetch and Data
   Abort paths set it): it runs `_flush_cputlb()` (TTBR0 rewrite + `TLBIALL` + `DSB` +
   `ISB`), `_flush_tlb()`, an optional `ctl_remove_cache(page)`, and records
   `_pte_report(page)` in `pte_rewalks`. Live run: **`cputlb_flushes = 19`**,
   **`page_cache_drops = 28`**.
2. **`0x0402F000` PTE verified valid and executable [C].** After the first prefetch
   delivery the re-walk reports: `L2 = 0x0042FE7E`, `valid = True`,
   `PA = 0x0042F000`, `hw_pte = 0x0042F67E`, **`AP = 0x03`** (full user access),
   `TEX = 0x07`, `C/B = 1`.
3. **But the fault still repeats 8× [C].** `fault_guard_key = [0x0402F666, 0x0402F666,
   USR]`, `fault_guard_count = 8`; the guard stops the run. Even with the valid,
   executable PTE and 19 SoftMMU flushes, Unicorn's translated view of
   `0x0402F000` is not refreshed: **the guest CP15 `TLBIALL`/`TTBR0` writes executed by
   our helper are not honoured by this Unicorn build** (Unicorn replaces QEMU's TLB
   maintenance; `ctl_flush_tb` only drops code TBs, not SoftMMU TLB entries).
4. **SWI hook enabled [C] but no syscall reached.** `enable_svc_dispatch = True` installs
   `UC_HOOK_INTR` with the E0438 Thumb-aware `intno==2` dispatch and `intno` 3/4 abort
   re-dispatch. `svc_hits = 0` because execution never gets past the
   `0x0402F666` loop, so the `futex_init`/syscall verification is still pending.
5. **No shell [C]:** `serial 0 B`, `user_entries = 20`, run 17 s.

## 1. Evidence

| item | value |
| --- | --- |
| prefetch flush | ret_to_user `_pte_dirty` → `_flush_cputlb()` + `ctl_remove_cache`; `cputlb_flushes=19`, `page_cache_drops=28` [C] |
| `0x0402F000` PTE | `L2 0x0042FE7E`, valid, `PA 0x0042F000`, `AP 0x03`, TEX `0x07`, C/B 1 [C] |
| loop | `[0x0402F666, 0x0402F666, USR]`, count 8, guard stop [C] |
| SWI | `enable_svc_dispatch=True`, `svc_hits=0` (loop not passed) [C] |
| runs | 17 s, prefetch 17, aborts 2, kuser 0, serial 0 B |
| tests | prefetch dirty-page + CPUTLB helper tests — suite **1519 OK** |

## 2. Implemented

* `_last_fault_page` tracking in both abort deliveries.
* `ret_to_user` hook: `_pte_report(page)` → `_flush_cputlb()` → `_flush_tlb()` →
  `ctl_remove_cache(page)`, then clears `_pte_dirty`.
* `enable_svc_dispatch = True` (E0438 SWI + intno 3/4 re-dispatch) for the live run.
* Two unit tests: prefetch delivery marks the fault page dirty, CPUTLB helper runs.

## 3. Next step

1. **The remaining blocker is Unicorn TLB invalidation for guest PTE updates.** Options:
   * investigate Unicorn's `ctl_set_tlb_mode` / `ctl_flush_tb` combination (or a
     `UC_CTL_TLB_FLUSH`-equivalent) that drops the SoftMMU TLB, not just TBs;
   * alternatively pre-map all `ld-2.11.2.so` pages into the guest address space before
     handing control to user mode (a labelled emulator aid: populate the PTE/PA mapping
     for the whole first+second PT_LOAD from the extracted ld.so image), which removes
     the need for runtime PTE/TLB refreshes for that file.
2. Once `0x0402F666` executes, verify `svc_hits` (ld.so syscalls) then continue to BusyBox
   `_start` (`0x0000C439`).
3. Capture the live `/bin/ash` prompt and command output over `ttyAM0`.
