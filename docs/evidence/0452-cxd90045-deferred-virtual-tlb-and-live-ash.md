# E0452 — Deferred `UC_TLB_VIRTUAL` activation on userspace entry

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0451.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **Deferred activation implemented [C].** `UnicornMachine` now supports
   `virtual_tlb_on_userspace=True`: the kernel runs its whole early boot in standard
   **`UC_TLB_CPU`** mode (the E0446-proven clean path: `start_kernel`,
   `init_section_page_cgroup`, `futex_init`, `do_initcalls`, cramfs mount,
   `run_init_process`), and the `ret_to_user` (`0x6010DF34`) hook requests the switch on
   the first user return: it sets `_vtlb_requested`, calls `uc.emu_stop()`, and the run
   loop installs `ctl_set_tlb_mode(UC_TLB_VIRTUAL)` + `UC_HOOK_TLB_FILL` before the next
   slice. This **avoids the `init_section_page_cgroup` NULL entirely** — the kernel boot is
   no longer affected by the virtual TLB.
2. **The switch happens in the live run [C].** Report: `virtual_tlb_on_userspace = True`,
   `virtual_tlb = True`, `tlb_fills = 2969`, and the kernel reached the first
   `ret_to_user` (after full init). A kuser helper was already hit
   (`kuser_hits = 1`, `0xFFFF0FA0` memory barrier) — user code started.
3. **New blocker: the TTBR0/TTBR1 values read at activation are wrong [C].** The
   activation primes the page-table caches by executing the MRC helpers, but both
   `_read_cp15_ttbr0()` and `_read_cp15_ttbr1()` return **`0x00104000`** at that moment
   (the expected `swapper_pg_dir`), even though earlier runs showed `TTBR0 = 0x1DC1C000`
   once user mode was established. With `TTBR0 = 0x104000` the fill hook walks the
   **kernel** L1 for user addresses, so user translations fail; the run then stops at
   `__migrate_disable+0x30` with two TLB misses at VA `0x0`.
4. **No shell [C]:** `serial 0 B`, `svc_hits = 0`, `user_entries = 0`.

## 1. Evidence

| item | value |
| --- | --- |
| deferred activation | `virtual_tlb=False` until `ret_to_user`, then `True` [C] |
| kernel boot | clean CPU-mode boot through init (no `init_section_page_cgroup` NULL) [C] |
| fills | `tlb_fills = 2969`, `tlb_fill_misses = 2` (both VA `0x0`) [C] |
| kuser | `kuser_hits = 1` (`0xFFFF0FA0`) — user code entered [C] |
| TTBR at activation | both TTBR0/TTBR1 read `0x00104000` (wrong for TTBR0) [C] |
| new stop | `__migrate_disable+0x30`, VA `0x0` [C] |
| tests | 13 in `test_virtual_tlb.py` (deferred waits for userspace, deferred flag) — suite **1531 OK** |

## 2. Implemented

* `virtual_tlb_on_userspace` flag; install is skipped at construction when set.
* `ret_to_user` hook: first user return → `_vtlb_requested = True` + `uc.emu_stop()`.
* Run loop: after a clean `emu_start` return, install the virtual TLB + fill hook,
  set `_mmu_enabled`, and prime `_cached_ttbr0`/`_cached_ttbr1` via the MRC helpers.
* Report fields `virtual_tlb_on_userspace`.
* Two unit tests (deferred waits for userspace; deferred flag/reporting).

## 3. Next step

1. **Fix TTBR0 priming at activation.** The read at `ret_to_user` entry apparently
   happens while the kernel's `swapper_pg_dir` is still in TTBR0 (the user pgd is written
   later by `switch_mm` / the return path). Instead of priming once, refresh
   `_cached_ttbr0` in the `ret_to_user` hook on every return (after the instruction) and,
   critically, **also cache TTBR0 from the user-mode entry path** — or read the user pgd
   from `current->mm->pgd` (task struct reachable via the SVC stack thread_info) as a
   fallback so the first user fetch sees the real user L1 base.
2. Re-run and verify `0x0402F666`/`0x04031AF0` translate through the fill hook, `svc_hits`
   records ld.so syscalls, and `user_mode_entries` reaches BusyBox `_start`
   (`0x0000C439`).
3. Capture the live `/bin/ash` prompt and command output over `ttyAM0`.
