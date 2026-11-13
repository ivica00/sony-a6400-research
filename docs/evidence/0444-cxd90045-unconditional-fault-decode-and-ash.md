# E0444 — Unconditional fault decode, `(PC, decoded VA)` guard and the remaining page/translation blocker

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0443.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **Decode is decoupled from the diagnostic cap [C].** The fallback now calls
   `_walk_user_va(pc)` (TTBR0 → L1 → L2) on **every** user-mode bare `UC_ERR_EXCEPTION`
   with a mapped PC page, keeps `live_fault_dumps` as a capped log only, and decodes the
   faulting instruction with capstone. A real bug was fixed: the decoder still passed the
   string-form PA to `int(pa, 16)` after the refactor, so it always returned `None`; with
   `int(pa)` the decoded path fires on every repetition.
2. **Loads and stores are distinguished [C].** `_decode_fault_address` returns
   `(va, is_write)` from the capstone mnemonic (`ldr*/ldm*/pop` → read, `str*/stm*/push` →
   write), and the Data Abort is delivered with `DFSR = 0x5`/`0x805` accordingly across
   `[rn, rm]` and `[rn, #imm]` addressing. Unit tests cover a Thumb `ldr r3,[r1,r0]`
   (→ `0x0404DF48`, read) and `str r3,[r1,#4]` (→ `0x0402E004`, write).
3. **Guard keyed on the decoded VA [C].** `_note_fault(pc, decoded_va, cpsr)` now uses the
   effective VA; the live run reports `fault_guard_key = [67312368, 67428168, 16]`
   (`0x04031AF0`, **`0x0404DF48`**, USR), and a unit test proves a different decoded VA
   resets the counter.
4. **The decode path works in the live run [C]:** the classification trace alternates
   `prefetch` (first classification of each new exception) with
   `kind='data-decoded', address=0x0404DF48, write=False`, and the guard fires exactly on
   `(0x04031AF0, 0x0404DF48, USR)` after 8 repetitions.
5. **Remaining blocker [C]/[I]:** even though `do_page_fault` returns
   `VM_FAULT_MINOR` (`0x00000000`) and we now drop Unicorn's translation cache for
   `0x0404D000` after the delivery (`page_cache_drops = 15`), the retried
   `ldr r3,[r1,r0]` still translation-faults. So either the file-backed page
   (`ld.so` second PT_LOAD, vaddr `0x1FDA8`, file offset `0x1FF48-0x3AF0`) is still not
   installed by the kernel path, or Unicorn's **data** translation cache is not invalidated
   by `ctl_remove_cache` (only the TB/instruction side is). The SWI path stays dormant
   (`svc_hits = 0`), no shell, `serial 0 B`.

## 1. Evidence

| item | value |
| --- | --- |
| decoded address | `(pc 0x04031AF0) → 0x0404DF48`, read, repeated [C] |
| guard | `[0x04031AF0, 0x0404DF48, 0x10]`, count 8, stop at guard [C] |
| `handle_mm_fault` | ret `0x00000000` (recorded with stale `last_ifar` label) [C] |
| cache drops | `page_cache_drops = 15` (`ctl_remove_cache(0x0404D000)`), no effect [C] |
| run | 19 s, user entries 20, prefetch 2, aborts 2, serial 0 B [C] |
| tests | Thumb load decode, Thumb store decode, decoded-VA guard — suite **1517 OK** |

## 2. Implemented

* `_walk_user_va()` (uncapped) + `_capture_live_fault_page()` (capped diagnostic only).
* `_decode_fault_address(pc, pa) → (va, is_write)` with load/store distinction.
* Unconditional mapped-page decode in the run-loop fallback + cache drop for the decoded
  page after delivery.
* Guard keyed on the decoded effective VA.
* Three unit tests.

## 3. Next step

1. Confirm whether the guest PTE for `0x0404D000` becomes present **and executable** after
   the decoded Data Abort: re-walk TTBR0/L1/L2 for `0x0404D000` **after** delivery and
   report the PTE bits (present/AP/X).
2. If the PTE is present but Unicorn retries the fault, the invalidation must target the
   **data TLB** (e.g. `ctl_set_tlb_mode`/`ctl_flush_tb` combined with `ctl_remove_cache`,
   or a controlled PTE re-write of the same value via `mem_write` to force a breakpoint
   flush) — the TB cache alone is insufficient.
3. If the PTE is **not** present, trace `handle_mm_fault`/`cramfs_readpage` for
   `0x0404D000` (file offset `(0x0404DF48-0x0402E000) = 0x1FF48` in the second PT_LOAD)
   and fix the file-backed page install.
4. Then enable SWI dispatch for real (`svc #0` detection is already wired) and continue to
   BusyBox `_start` (`0x0000C439`) and the live `/bin/ash` prompt over `ttyAM0`.
