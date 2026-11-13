# E0454 — `cpu_v7_switch_mm` hook address and live-SP `mm`/`active_mm` fallback

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0453.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **Root cause of the dead hook found [C]:** `_symbol_address('cpu_v7_switch_mm')` returns
   **`None`** in this machine's decoded kallsyms, so `_install_switch_mm_hook()` returned
   before registering anything (`switch_mm_hits = 0` was therefore expected, and the
   earlier `switch_mm_hooked=True` report was misleading). The hook window was also
   single-address (`begin == end`), which Unicorn treats as empty (`end` exclusive).
2. **Fixed both:** the hook now falls back to the verified image address
   **`0x6011A26C`** and uses a `0x20`-byte window; `_resolve_user_pgd()` now reads the
   **live SVC `SP`** and falls back from `mm = [task+0xCC]` to
   `active_mm = [task+0xD0]`, accepting any page-aligned `pgd_pa != 0x00104000`.
3. **But the hook still records 0 hits even at the absolute address [C]:** the run reports
   `switch_mm_address = 0x6011A26C`, `switch_mm_hits = 0`. So in this boot path the
   kernel does **not** execute `cpu_v7_switch_mm` at `0x6011A26C` (different TTBR0 write
   site / inlined `cpu_switch_mm`, or the switch happens outside the hooked range).
4. **Live state unchanged [C]:** `_resolve_user_pgd` still sees `sp = 0x7DC0FFB0`,
   task `0x7E36DBE0`, **mm = 0** (and active_mm fallback also 0), TTBR0 read
   `0x00104000`; the fill hook walks the kernel L1 for user VAs and the run stops at
   `__migrate_disable+0x30` with 2 VA-0 misses; `kuser_hits = 1`, `svc_hits = 0`.
5. **No shell [C]:** `serial 0 B`, `user_entries = 0`.

## 1. Evidence

| item | value |
| --- | --- |
| symbol lookup | `_symbol_address('cpu_v7_switch_mm')` = `None` [C] |
| absolute fallback | `switch_mm_address = 0x6011A26C`, window `+0x20` [C] |
| hits | **`switch_mm_hits = 0`** even at the absolute address [C] |
| live SP / mm | `sp 0x7DC0FFB0`, task `0x7E36DBE0`, `mm = 0`, `active_mm = 0` [C] |
| TTBR0 | still `0x00104000` (kernel `swapper_pg_dir`) [C] |
| stop | `__migrate_disable+0x30`, `tlb_fills=2969`, `tlb_fill_misses=2` [C] |
| tests | 16 in `test_virtual_tlb.py` (absolute-address hook registration, …) — suite **1535 OK** |

## 2. Implemented

* `_install_switch_mm_hook()`: verified `0x6011A26C` fallback address and a
  `begin .. begin+0x20` window; records `switch_mm_address`.
* `_resolve_user_pgd()`: live SVC `SP` + `mm` → `active_mm` (`[task+0xD0]`) fallback.
* Report fields `switch_mm_address`, `switch_mm_hits`, `switch_mm_values`,
  `mm_resolve_trace`.
* One new unit test (absolute-address hook registration).

## 3. Next step

1. **Find the real TTBR0 write site:** decode all kallsyms names containing
   `switch_mm`/`cpu_switch_mm`/`set_ttbr0` and hook each candidate, or hook
   `kernel_execve` return and read TTBR0 immediately (the user pgd is installed during
   `execve`), caching it before the first user fetch.
2. **Fix the `ret_to_user` stack mismatch:** the sampled SVC `SP` still resolves
   `mm = NULL`; capture `SP`/`thread_info`/`task` directly from the `ret_to_user` frame
   (and from the exception-delivery frame) rather than the stale stack, then use
   `active_mm`/`pgd` or the switch-site value.
3. Once `_cached_ttbr0` holds a real user `pgd_pa`, verify `0x0402F666`/`0x04031AF0`
   translate via the fill hook, `svc_hits` records ld.so/BusyBox syscalls, and capture
   the live `/bin/ash` prompt over `ttyAM0`.
