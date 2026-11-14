# E0501 — `0x0402F666` faults are TB/translation staleness, not a bad PTE or bad code; in-hook eviction attempts regressed and were reverted

Date: 2026-11-13. **Strictly offline.** No camera access, no USB, no writes. Inputs: E0414
dumps, E0416 contract, E0420–E0500 offline chain, the read-only dump set in
`artifacts/dumps/a6400-nflasha-readonly/` (full `/proc/kallsyms`).

## 0. Short answer

1. **The code is valid Thumb [C].** `ld-2.11.2.so` at `0x0402F660` is a real function:

   ```
   0x0402F660 push.w {r4-r11, lr}
   0x0402F664 sub sp, #0x9c
   0x0402F666 ldr.w r4, [pc, #0xbec]
   0x0402F66A add r7, sp, #0x10
   0x0402F66C ldr.w r6, [pc, #0xbe8]
   ...
   ```

   so `0x0402F666` is not a bogus PC and there is no infinite loop there — it is a fresh
   function the loader calls after `brk`, on a **new page** (`0x0402F000`).
2. **The PTE is already valid [C].** The repeated faults are accompanied by
   `_pte_report(0x0402F000)`: `TTBR0 0x1DC1C000`, `L1 0x1F13E831`, **`L2 0x0042FE7E`
   (valid)**, `PA 0x0042F000`, `AP 0x03`, `TEX 0x07`, `C/B 1` — the kernel has mapped the
   page; the instruction fetch still fails, i.e. the failure is in the translator/TB
   cache view (stale non-user translation created before the page was mapped), not in the
   page tables.
3. **Two candidate fixes were implemented and both regressed early boot, so they were
   reverted [C]:**
   * marking the prefetch fault page `_pte_dirty` with `_last_fault_page` (so
     `ret_to_user` re-walks/flushes it) — with this, the run stopped at
     `unicorn_error PC 0x04031AAC` with `gen = 3`, `svc_hits = 0`;
   * evicting the user return page TB (`ctl_remove_cache(pc_page)`) inside the
     `0x6010DF34` hook — same early stop.
   The reason is structural: the existing `_pte_dirty` path calls `_flush_cputlb()`,
   which **executes a guest MRC helper via a nested `emu_start` from inside a
   `UC_HOOK_CODE` callback**, and that is exactly the pattern the project already learned
   to avoid (E0456). Doing cache operations inside hooks is not safe in this machine.
4. **Reverted state is back to E0500 behaviour [C]:** `instruction_limit`
   (`PC 0x6010DE20`), `pt_frame_gen = 30`, `svc_hits = 1` (`brk`), `serial 0 B`,
   `fault_classification_trace` ends with the repeating `0x0402F666` prefetch entries.

## 1. Evidence

| item | value |
| --- | --- |
| code | `0x0402F660 push.w {r4-r11,lr}; 0x0402F664 sub sp,#0x9c; 0x0402F666 ldr.w r4,[pc,#0xbec]` [C] |
| PTE | `0x0402F000`: `TTBR0 0x1DC1C000`, `L1 0x1F13E831`, `L2 0x0042FE7E` valid, `PA 0x0042F000`, `AP 0x03`, `TEX 0x07`, `C/B` [C] |
| repeat | same `0x0402F666` prefetch 8×, then `instruction_limit` [C] |
| regression A | prefetch dirty-flag attempt: `unicorn_error PC 0x04031AAC`, `gen 3`, `svc 0` [C] |
| regression B | in-hook `ctl_remove_cache` attempt: same early stop [C] |
| revert | E0500 behaviour restored (`instruction_limit`, `gen 30`, `svc 1`, `serial 0`) [C] |
| tests | suite unchanged (diagnostic round, no API change kept) |

## 2. Implemented / reverted

* Kept: `e0500_frames`/`e0499_trace` diagnostics, E0500 SVC-return fix.
* Reverted: prefetch `_pte_dirty`/`_last_fault_page` marking and the in-hook return-page
  TB eviction (both caused an early `unicorn_error` at `0x04031AAC` because the flush
  path runs a nested guest `emu_start` from inside the hook).

## 3. Next step (clean, hook-safe design)

1. **Queue the invalidation instead of doing it in the hook:** from the fault
   classifier/`ret_to_user` hook, set `self._pending_evict_page = pc & ~0xFFF` and
   `self._pending_cputlb_flush = True`, then let the **run loop** (outside callbacks,
   before the next `emu_start`) perform `ctl_remove_cache(page, page+0x1000)`,
   `_flush_cputlb()` and `_walk_user_va`/PTE re-report. This is the same deferred pattern
   the project used for TTBR0 refresh (E0456) and avoids nested emulation.
2. Re-run and confirm `0x0402F666` executes once (no repeats), then the loader continues
   its next syscalls (`uname`, `open`, `mmap2`, `set_tls`, `write`, `read`).
3. Then BusyBox `_start 0x0000C439` and the live `/bin/ash` prompt over `ttyAM0`.
