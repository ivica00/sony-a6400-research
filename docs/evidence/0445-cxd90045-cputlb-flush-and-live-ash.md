# E0445 — `0x0404D000` PTE re-walk, SoftMMU `CPUTLB` flush and the stale-DFAR root cause

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0444.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **`0x0404D000` PTE re-walk implemented and measured [C].** After the decoded Data Abort
   delivery the machine re-walks `TTBR0 → L1 → L2` for VA `0x0404D000` and records the
   raw descriptors (`pte_rewalks`, PTE/AP/TEX/C/B decode). Two outcomes are now captured:
   * before the fix: `L2 = 0x00000000`, `valid = False` — the kernel had **not** installed
     the page;
   * after the fix: `L2 = 0x004D6E7F`, `valid = True`, `PA = 0x004D6000`,
     `AP = 0x03` (full access), `C/B = 1` — the page **is installed**.
2. **Real SoftMMU `CPUTLB` flush implemented [C].** `_flush_cputlb()` executes a
   privileged helper: `mrc p15,0,r1,c2,c0,0` → `mcr p15,0,r1,c2,c0,0` (TTBR0 rewrite),
   `mcr p15,0,r0,c8,c7,0` (**TLBIALL**), `DSB`, `ISB`; it preserves registers and the
   Thumb bit via the PC LSB. `cputlb_flushes` is reported (2 in the fixed run).
   `ctl_remove_cache` is kept as a code-TB drop only (`page_cache_drops`).
3. **Root cause of the missing PTE: stale DFAR/DFSR [C].** The user-mode Data Abort path
   in `_deliver_data_abort` called `_set_cp15_fault` and delivered to `__dabt_usr`
   **before** updating `last_dfar`/`last_dfsr` (those were only set on the kernel-mode
   path). The kernel's `v7_early_abort` MRC hooks therefore injected an **old** fault
   address/status, so `do_DataAbort`/`do_page_fault` handled the wrong page and never
   installed `0x0404D000`. Moving the
   `fsr`/`last_dfar`/`last_dfsr` assignment above the user branch fixes it.
4. **Result of the fix [C].** The decoded Data Abort for `(0x04031AF0 → 0x0404DF48)` now
   produces a valid PTE for `0x0404D000`; execution moves past that load. The next loop
   is a **different** user prefetch at `PC = 0x0402F666` (ld.so page `0x0402F000`), retried
   8× and stopped by the guard: `fault_guard_key = [0x0402F666, 0x0402F666, USR]`,
   `prefetch_aborts_delivered = 17`. That is ordinary demand-paging work now, not the
   stale-DFAR bug.
5. **No shell [C]:** `svc_hits = 0`, serial 0 B, run 16 s, `user_entries = 20`.

## 1. Evidence

| item | value |
| --- | --- |
| PTE before fix | `TTBR0 0x1DC1C000`, L1 `0x1F13E831`, **L2 `0x00000000`**, valid False [C] |
| PTE after DFAR fix | L2 **`0x004D6E7F`**, valid True, `PA 0x004D6000`, `AP 0x03`, TEX `0x06`, C/B 1 [C] |
| CPUTLB helper | TTBR0 rewrite + TLBIALL (`0xEE080F17`) + DSB + ISB; `cputlb_flushes=2` [C] |
| stale-DFAR bug | user branch used old `last_dfar`/`last_dfsr`; fixed by hoisting the assignment [C] |
| new loop | `PC 0x0402F666` (page `0x0402F000`), prefetch, 8×, guard stops [C] |
| run | 16 s, user 20, prefetch 17, aborts 2, kuser 0, serial 0 B |
| suite | **1517 tests OK** (no regressions from the delivery change) |

## 2. Implemented

* `_pte_report(va)`: TTBR0/L1/L2 walk + PTE bit decode (present/AP/TEX/C/B/PA).
* `_flush_cputlb()`: TTBR0 rewrite + `TLBIALL` + `DSB` + `ISB`, register/T-bit safe.
* `pte_rewalks` / `cputlb_flushes` report fields.
* **Critical fix:** `_deliver_data_abort` sets `fsr`/`last_dfar`/`last_dfsr` before the
  user-mode `__dabt_usr` delivery, so the kernel's MRC hooks inject the correct fault.

## 3. Next step

1. The guard now stops on a plain prefetch loop at `0x0402F666` (page `0x0402F000`):
  re-walk that page's PTE after the first prefetch delivery; if it becomes valid but the
  instruction fetch still faults, apply the same `_flush_cputlb()` on the **prefetch**
  path (currently only the decoded data path flushes).
2. Then enable `enable_svc_dispatch=True` (SWI + intno 3/4) and verify `svc_hits`
   (ld.so syscalls: `brk`, `open`, `mmap2`, `set_tls`, `write`, `read`, …).
3. Continue to BusyBox `_start` (`0x0000C439`) and capture the live `/bin/ash` prompt and
   command output over `ttyAM0`.
