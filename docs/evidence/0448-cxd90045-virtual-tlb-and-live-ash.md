# E0448 — `UC_TLB_VIRTUAL` + `UC_HOOK_TLB_FILL`: live page-table translation hook

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0447.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The virtual TLB is wired and is doing the translations [C].**
   `UnicornMachine` now calls `uc.ctl_set_tlb_mode(UC_TLB_VIRTUAL)` and registers
   `UC_HOOK_TLB_FILL` before the run (clean fallback: `virtual_tlb=False`,
   `virtual_tlb_error` in the report if an older Unicorn lacks it). The live run reports
   **`virtual_tlb = True`**, **`tlb_fills = 1195`**, **`tlb_fill_misses = 0`** — the hook
   is invoked for every translation and always resolves, so the stale SoftMMU entries
   that blocked `0x0402F666` in E0446/E0447 no longer exist.
2. **The fill hook never executes guest code [C].** Translation is pure `uc.mem_read`
   on physical memory plus the TTBR0 cached from `_read_cp15_ttbr0()` / `ret_to_user`:
   * pre-MMU (`_mmu_enabled == False`): identity `paddr = vaddr`;
   * high vectors and the identity-mapped MMIO window (`vaddr >= 0xFFFF0000`):
     identity `paddr = vaddr`;
   * kernel lowmem (`0x60000000 ≤ vaddr < 0x80000000`):
     `paddr = vaddr - 0x60000000`;
   * vmalloc/fixmap/MMIO (`vaddr ≥ 0x80000000`): a physical `swapper_pg_dir → L1 → L2`
     walk, with identity as the last resort for stubbed pages;
   * userspace (`vaddr < 0x60000000`, MMU on): live `TTBR0 → L1 → L2` walk, returning
     `paddr = PTE page | offset`, `perms = UC_PROT_ALL`, or **`False`** when the L1/L2
     entry is unmapped so Unicorn raises a clean translation fault for the existing
     demand-page delivery.
   `_mmu_enabled` is set on the first high-VA fetch.
3. **The `0x0402F666` loop is gone [C].** The live run now runs a different path instead
   of repeating the ld.so prefetch; it stops at `__memzero+0x24`
   (`0x60260104`) on a **write to VA `0xDF7FE000`** whose translation falls back to an
   unmapped identity PA (`unmapped: address=0xDF7FE000, access=20`). That is a
   **kernel TTBR1/vmalloc** translation gap (`swapper_pg_dir` base/offset), not the
   user-page TLB path.
4. **No shell [C]:** `serial 0 B`, `svc_hits = 0`, `user_entries = 0`; `mmio_write_count=22`.

## 1. Evidence

| item | value |
| --- | --- |
| virtual TLB | `virtual_tlb=True`, `tlb_fills=1195`, `tlb_fill_misses=0` [C] |
| stale-entry symptom | `0x0402F666` loop gone; stop moved to `__memzero+0x24` [C] |
| new blocker | write VA `0xDF7FE000` (`access=20`), `r0=0xDF7FE000`, `r1=4032` -> identity PA unmapped [C] |
| TTBR0 cache | `_read_cp15_ttbr0()` and `ret_to_user` refresh `_cached_ttbr0` [C] |
| MMU flag | set on first fetch with `vaddr >= 0x60000000` [C] |
| tests | `tests/emulator/test_virtual_tlb.py` (7): enabled, pre-MMU identity, kernel lowmem, high vectors, user L1/L2 walk, unmapped False, no-TTBR0 False — suite **1526 OK** |

## 2. Implemented

* `_walk_page_tables_phys()`: physical TTBR0 → L1 → L2 walk (no guest execution).
* `_walk_kernel_pt()`: physical `swapper_pg_dir` → L1 → L2 walk for kernel high VAs.
* `_translate_virtual()`: the documented translation rules.
* `_on_tlb_fill()`: counter/miss sampling, sets `_mmu_enabled`, fills
  `entry.paddr`/`entry.perms`.
* `_install_virtual_tlb()`: `ctl_set_tlb_mode(UC_TLB_VIRTUAL)` + `UC_HOOK_TLB_FILL`
  registration with fallback.
* TTBR0 cache refresh in `_read_cp15_ttbr0()` and the `ret_to_user` hook.
* Report fields: `virtual_tlb`, `virtual_tlb_error`, `tlb_fills`,
  `tlb_fill_misses`, `tlb_fill_samples`.

## 3. Next step

1. **Kernel TTBR1/vmalloc translation:** verify the `swapper_pg_dir` symbol address and
   the TTBR1 L1 base offset used by the host page-table walk (the `0xDF7FE000` write
   suggests the kernel VA does have a mapping that our walk missed), then re-run.
2. **Negative-translation re-fill:** after `do_page_fault`/`do_PrefetchAbort` installs a
   PTE, call `ctl_remove_cache(page, page + 0x1000)` so the `False` fill is re-invoked
   immediately (the ret hook already does this for dirty pages).
3. Re-run the scripted-RX boot and verify `0x0402F666`/ld.so syscalls (`svc_hits`),
   BusyBox `_start` (`0x0000C439`), `kuser_hits`/`tls_value`, then capture the live
   `/bin/ash` prompt and command output over `ttyAM0`.
