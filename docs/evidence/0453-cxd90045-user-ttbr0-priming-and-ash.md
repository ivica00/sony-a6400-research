# E0453 — User `TTBR0` priming via `current->mm->pgd` and `cpu_v7_switch_mm`

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0452.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **`cpu_v7_switch_mm` verified [C].** `0x6011A26C`:
   `mov r2,#0; ldr r1,[r1,#0x188]; orr r0,r0,#0x6a; mcr p15,0,r2,c13,c0,1;
   isb; mcr p15,0,r0,c2,c0,0; isb; mcr p15,0,r1,c13,c0,1; isb; mov pc,lr` — i.e.
   **`r0` at entry is the page-aligned `pgd` physical address** (ASID bits are OR'd in
   just before the `TTBR0` write).
2. **User-TTBR0 priming implemented [C]:** `_resolve_user_pgd()` walks
   `thread_info = SP & ~0x1FFF` → `task = [ti+0xC]` → `mm = [task+0xCC]` →
   `pgd = [mm+8]` → `pgd_pa`; `_refresh_user_ttbr0()` prefers the live CP15 TTBR0 and
   falls back to `current->mm->pgd` only when TTBR0 still reads `0x00104000`; and
   `_install_switch_mm_hook()` hooks `cpu_v7_switch_mm` to keep `_cached_ttbr0`
   synchronized across `execve`/`fork`/context switches (report
   `switch_mm_hits`/`switch_mm_values`, `mm_resolve_trace`).
3. **The live run still does not reach userspace [C]:** `switch_mm_hooked = True` but
   **`switch_mm_hits = 0`** (the hook never fired — symbol/registration to debug),
   `_resolve_user_pgd()` found `task = 0x7E36DBE0` but **`mm = 0`** on the sampled
   `ret_to_user` stack (`sp = 0x7DC0FFB0`, the known foreign/stale-stack pattern from
   E0439), and CP15 TTBR0 still read `0x00104000`. The fill hook therefore continued to
   walk the kernel L1 for user VAs and the run stopped at `__migrate_disable+0x30` with
   two VA-0 misses; `kuser_hits = 1`, `svc_hits = 0`.
4. **No shell [C]:** `serial 0 B`, `user_entries = 0`.

## 1. Evidence

| item | value |
| --- | --- |
| `cpu_v7_switch_mm` | `0x6011A26C`, `r0` = pgd phys, `mcr p15,0,r0,c2,c0,0` after `orr r0,#0x6a` [C] |
| mm offsets | `thread_info->task` `+0xC`, `task->mm` `+0xCC`, `mm->pgd` `+8` [C] |
| switch_mm hook | installed (`switch_mm_hooked=True`) but **0 hits** [C] |
| pgd resolver | task `0x7E36DBE0`, **mm = 0** on the sampled stack (`sp 0x7DC0FFB0`) [C] |
| TTBR0 read | still `0x00104000` (kernel `swapper_pg_dir`) [C] |
| stop | `__migrate_disable+0x30`, 2 VA-0 misses, `tlb_fills=2969` [C] |
| tests | 15 in `test_virtual_tlb.py` (empty-chain None, refresh no-fallback) — suite **1534 OK** |

## 2. Implemented

* `_read32_kernel()`, `_resolve_user_pgd()`, `_refresh_user_ttbr0()`.
* `_install_switch_mm_hook()` on `cpu_v7_switch_mm` (tracks `r0 & ~0x3FFF`).
* `ret_to_user` and deferred-activation paths now use `_refresh_user_ttbr0()`.
* Report fields `switch_mm_hooked`, `switch_mm_hits`, `switch_mm_values`,
  `mm_resolve_trace`.
* Two unit tests.

## 3. Next step

1. **Why does the switch_mm hook not fire?** Verify the symbol address against the live
   guest (`_symbol_address` value vs the disassembled `0x6011A26C`) and that
   `hook_add(UC_HOOK_CODE, begin=addr, end=addr)` semantics are correct in this Unicorn
   build (try a wider window or a different hook type), then confirm `switch_mm_hits > 0`.
2. **Fix the thread_info/stack mismatch:** the sampled `ret_to_user` stack resolves a task
   with `mm = NULL`; use the live SVC `SP` from the `ret_to_user` frame (not the stale
   `mode_sp`) and validate `task`/`mm`/`pgd` chain, or read the user pgd from the
   `cpu_v7_switch_mm` hook once it fires.
3. Once `_cached_ttbr0` holds the user pgd, verify `0x0402F666`/`0x04031AF0` translate via
   the fill hook, `svc_hits` records ld.so/BusyBox syscalls, then capture the live
   `/bin/ash` prompt over `ttyAM0`.
