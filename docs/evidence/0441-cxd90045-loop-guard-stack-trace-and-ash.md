# E0441 — Fast repeated-fault guard, `handle_mm_fault` return measurement and the `0x04031AF0` loop

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0440.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **Diagnostic runs are now fast [C].** A repeated-fault circuit breaker
   (`max_same_fault_repeats = 8` on consecutive `(pc, faulting VA, mode)` deliveries)
   plus throttled TLB flushing (`_pte_dirty`, flush only when a page fault actually
   occurred) turns the 320M diagnostic run into **~16–17 s** instead of >30 min, and the
   full JSON report is written every time.
2. **The E0439/E0440 stack fix is verified [C].** Delivery trace entries now show
   `thread_info = 0x7DC0E000`, **`task = 0x7E36DBE0`** (valid, `>= 0x60000000`),
   `svc_stack_refreshes = 51`, and the old `do_page_fault+0x34` NULL-`task->mm` crash is
   gone. Frames now show `ARM_cpsr = 0x70` (USR), `ARM_pc = 0x04031AF0`.
3. **`handle_mm_fault` return values are captured [C]** at the verified return site
   `0x60116E9C` (after `bl handle_mm_fault` at `0x60116E98`):
   * `0x00000204` for `0x0402E790`, `0x00000200` for `0x04031AA8` (SIGBUS-class codes),
   * **`0x00000000` for `0x04031AF0`** — the kernel reports the fault as handled
     (`VM_FAULT_MINOR`), with `task = 0x7E36DBE0` valid.
4. **Still looping [C].** Despite the success return, the prefetch at `0x04031AF0`
   repeats exactly 8 times and the guard stops the run (`fault_guard_key =
   [67312368, 67312368, 16]`, `fault_guard_count = 8`). Explicit
   `ctl_remove_cache(page, page+0x1000)` drops were attempted (`page_cache_drops = 7`)
   and did not break the loop.
   So the guest page table may be correct while **Unicorn's instruction-fetch
   translation for that page is still stale**, or the return-PC restore path
   re-executes the same faulting fetch.
5. **No SWI enablement / no shell [C]:** `svc_hits = 0`, `kuser_hits = 0`, serial 0 B;
   `enable_svc_dispatch` remains off because the page loop must be fixed first.

## 1. Evidence

| item | value |
| --- | --- |
| guard | `max_same_fault_repeats=8`; run stops at `fault_guard_count=8`, 16 s |
| TLB throttling | `_pte_dirty`; `tlb_flushes=20` (was 253) |
| stack fix | `thread_info 0x7DC0E000`, **`task 0x7E36DBE0`**, `svc_stack_refreshes=51` |
| delivery trace | `sp 0x7DC0FFF8`, `thread_info 0x7DC0E000`, `task 0x7E36DBE0` for `0x0402E790`, `0x04031AA8`, `0x04031AF0` |
| `handle_mm_fault` | `0x60116E9C` capture; `0x204`/`0x200` for earlier pages, **`0x00000000` for `0x04031AF0`** |
| page cache drops | `page_cache_drops = 7` (`ctl_remove_cache`) |
| loop | same `0x04031AF0` prefetch 8×, `user_entries` stops at `0x04031AF0` |
| tests | guard + `_kernel_phys` tests — suite **1512 OK** |

## 2. Implemented

* `_note_fault(pc, address, cpsr)` circuit breaker + `fault_guard_key/count` report; the
  run loop breaks with `repeated_fault` on 8 repeats.
* `_pte_dirty` throttling: `ret_to_user` flushes only when a fault delivered since the
  last return; `tlb_flushes` dropped 253 → 20.
* `mm_fault_returns` capture at `0x60116E9C` (ret value, `last_ifar`, task).
* `ctl_remove_cache(page, page+0x1000)` on successful `handle_mm_fault`
  (`page_cache_drops`).
* `_kernel_phys` unit test + guard unit test.

## 3. Next step

1. **Distinguish stale fetch translation from re-fault**: check whether the fault is a
   *new* fetch (`last_ifar` changes) or our delivery re-entering the same PC; then walk
   the guest L1/L2 PTE for `0x04031000` (from `task->mm->pgd = [task+0xCC]`) after the
   first successful `handle_mm_fault` to confirm the hardware PTE is valid + executable.
2. If the PTE is valid and Unicorn still faults on fetch, the fix is in the emulator's
   instruction-cache invalidation for that page (not `ctl_remove_cache`), or a controlled
   page-cache injection; if the PTE is not valid, inspect `cramfs_readpage` /
   `set_pte_ext` for file offset `0x3000`.
3. Then enable `enable_svc_dispatch=True` (E0438 SWI + intno 3/4), verify `futex_init`
   and `svc_hits`, and continue to BusyBox `_start` (`0x0000C439`) and live `/bin/ash`.
