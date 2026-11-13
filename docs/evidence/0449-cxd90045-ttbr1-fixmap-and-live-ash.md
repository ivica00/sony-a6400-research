# E0449 — TTBR1 (`swapper_pg_dir`) walk fix, fixmap `0xDF7FE000` resolution and the next blocker

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0448.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The kernel TTBR1 base is now read live and is correct [C].** `_read_cp15_ttbr1()`
   (MRC `p15,0,r0,c2,c0,1`) executes in the helper page outside the TLB-fill callback and
   returns `0x00104000` in the live guest — exactly the physical address expected for
   `swapper_pg_dir` (`0x60104000 - 0x60000000`). It is cached as soon as the run loop sees
   `PC >= 0x60000000`.
2. **The `>= 0x80000000` walk is fixed [C].** `_walk_kernel_pt()` now tries the live TTBR1
   base (with both the full `(va>>20)&0xFFF` index and the TTBCR.N=2 `&0x3FF` variant) plus
   `swapper_pg_dir`-derived bases as candidates, accepts an L1 **section**
   (`(l1&2)==2` → `(l1&0xFFF00000)|offset`) or a **coarse table** L1→L2 small page
   (`(l2&2)==2` → `(l2&0xFFFFF000)|offset`), and only accepts a PA that lies in the
   machine's mapped RAM/MMIO ranges. Unmapped `vmalloc`/`fixmap` VAs now return `False`
   instead of a bogus identity PA; identity remains only for the
   `0xF0000000..0xFFFFFFFF` hardware window.
3. **`__memzero` / `0xDF7FE000` is gone [C].** The fixmap write that stopped E0448 is
   resolved through the TTBR1 walk; the boot now reaches **`__rt_mutex_init+0x10`**
   (`0x6015EE9C`).
4. **New blocker — a genuine kernel NULL write [C].** The run stops on a write to
   **VA `0x00000000`** (`unmapped: access=17`), reported as the single TLB-fill miss;
   this is a kernel data-structure pointer that is NULL during `__rt_mutex_init`, not a
   translation/TLB problem.
5. **No shell [C]:** `serial 0 B`, `svc_hits = 0`, `user_entries = 0`;
   `tlb_fills = 98326`, `tlb_fill_misses = 1`.

## 1. Evidence

| item | value |
| --- | --- |
| TTBR1 read | helper MRC returns **`0x00104000`** (cached `_cached_ttbr1`) [C] |
| walk | TTBR1/swapper candidate L1 section + L1→L2 small page, PA must be mapped [C] |
| fixmap | `0xDF7FE000` resolved; `__memzero+0x24` stall gone [C] |
| new stop | `__rt_mutex_init+0x10` (`0x6015EE9C`), NULL write VA `0x0`, access 17 [C] |
| fills | `tlb_fills=98326`, `tlb_fill_misses=1` [C] |
| tests | `test_virtual_tlb.py` 11 tests (TTBR1 section, TTBR1 L2 small page, unmapped vmalloc None, MMIO identity, …) — suite **1530 OK** |

## 2. Implemented

* `_read_cp15_ttbr1()` (register/T-bit safe MRC helper, cached `_cached_ttbr1`).
* Candidate-scan `_walk_kernel_pt()` (TTBR1 base ± index variants, `swapper_pg_dir`
  variants, section + L1→L2, mapped-PA acceptance).
* `_pa_mapped()` RAM/MMIO range check.
* Fallback policy: identity only for `>= 0xF0000000`; `None` (real fault) for unmapped
  `vmalloc`/`fixmap`.
* TTBR1 early caching in the run loop once the kernel runs at a high VA.
* Virtual TLB is **opt-in** (`virtual_tlb_enabled=False` by default, enabled by
  `run_nflasha1_boot`) so the legacy memory/exception tests keep their previous semantics.

## 3. Next step

1. Investigate the NULL write at `__rt_mutex_init+0x10`: disassemble the function, read
   the caller/arguments, and identify which kernel structure is zero (likely a mutex
   pointer not initialised because an earlier Sony init path returned early).
2. After that, continue through kernel init → `futex_init` → `run_init_process` →
   `ld-2.11.2.so` syscalls (`svc_hits`), then BusyBox `_start` (`0x0000C439`) and the live
   `/bin/ash` prompt over `ttyAM0`.
