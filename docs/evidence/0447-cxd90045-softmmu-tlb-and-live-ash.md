# E0447 — Unicorn SoftMMU TLB mechanisms: `UC_TLB_VIRTUAL` API found, `SCTLR` toggle rejected

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0446.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The clean mechanism exists in this Unicorn build [C].** Unicorn 2.1.4 exposes
   `UC_CTL_TLB_TYPE`, `UC_TLB_CPU`, **`UC_TLB_VIRTUAL`**, **`UC_HOOK_TLB_FILL`**, and the
   Python API `Uc.ctl_set_tlb_mode(mode)` / `Uc.ctl_tlb_mode(mode)`. The TLB-fill callback
   signature is `(uc, vaddr, access, entry, user_data)` where `entry` is a
   `uc_tlb_entry` with `paddr` (c_ulonglong) and `perms` (c_ulong): a hook can walk the
   live guest `TTBR0 → L1 → L2` page tables and install `(pa, UC_PROT_*)` directly,
   bypassing the stale SoftMMU cache. This is the general fix for every demand-paged
   binary and has **not yet been wired** (next step).
2. **Mechanism 1 (`SCTLR` write to reach QEMU `sctlr_write → tlb_flush``) was tried and
   rejected [C].** A helper was added that reads SCTLR, toggles the A bit (bit 1) with
   `M` still set, writes it back, restores SCTLR, then `DSB`/`ISB` — on the assumption
   that a changed `SCTLR` value makes QEMU flush the SoftMMU TLB. Live run: boot broke
   **much earlier** (`stop_reason=unicorn_error`, `PC 0x6040BC88`,
   `__kstrtab_flush_delayed_work_sync+0x17`), `user_entries = 0`, `cputlb_flushes = 0`
   (the helper raised before completing), `prefetch = 0`. The experiment was reverted;
   the working E0446 CP15 sequence (TTBR0 rewrite + `TLBIALL` + `DSB` + `ISB`) is
   restored and the suite is green again.
3. **Evidence that the PTE side is already correct [C]:** the reverted run's ret-hook
   re-walk still reported a valid PTE for `0x0404E000` (`L2 0x00691C7F`, `PA 0x00691000`,
   `AP 0x03`), i.e. the kernel does install pages; only the emulator's *view* is stale.
4. **No shell [C]:** `serial 0 B`, `svc_hits = 0`.

## 1. Evidence

| item | value |
| --- | --- |
| Unicorn API | `ctl_set_tlb_mode`, `UC_TLB_VIRTUAL`, `UC_HOOK_TLB_FILL`; `uc_tlb_entry{paddr, perms}` [C] |
| SCTLR experiment | `stop_reason=unicorn_error` at `0x6040BC88`, `user_entries=0`, `cputlb_flushes=0` [C] |
| reverted flush | TTBR0 rewrite + TLBIALL `0xEE080F17` + DSB + ISB (count=5) restored [C] |
| PTE during failed run | `0x0404E000`: `L2 0x00691C7F`, valid, `PA 0x00691000`, AP `0x03` [C] |
| suite | **1519 tests OK** after revert |

## 2. Implemented / reverted

* Investigated the Unicorn TLB API surface (recorded above, including the exact fill
  callback/`uc_tlb_entry` layout).
* Added, tested and **reverted** the SCTLR-toggle variant of `_flush_cputlb`.
* Restored the E0446 helper; suite and status card stay at 1519 tests.

## 3. Next step — wire `UC_TLB_VIRTUAL` + `UC_HOOK_TLB_FILL`

1. `uc.ctl_set_tlb_mode(UC_TLB_VIRTUAL)` before `emu_start`, register
   `UC_HOOK_TLB_FILL` and, in the callback, translate `vaddr` with:
   * user VA (`< PAGE_OFFSET`): live `TTBR0 → L1 → L2` walk → `paddr = pa`, `perms =
     UC_PROT_ALL`; return False when the PTE is invalid so the existing fault-delivery
     path runs;
   * kernel linear VA (`0x60000000+`): `paddr = vaddr - PAGE_OFFSET`;
   * high vectors (`0xFFFF0000..0xFFFF0FFF`): `paddr = vaddr - 0xFFFF0000`;
   * MMIO ranges: identity (the machine stubs are mapped at their physical addresses).
2. Guard against re-entrancy: the fill hook must not call `_read_cp15_ttbr0` while
   filling; cache the last TTBR0 value from the ret_to_user hook and walk page tables
   with plain `uc.mem_read` at already-identity-mapped physical addresses.
3. Re-run the scripted-RX boot; verify `0x0402F666` executes, `user_mode_entries` reaches
   BusyBox (`_start 0x0000C439`), `svc_hits` records ld.so/BusyBox syscalls, then capture
   the live `/bin/ash` prompt over `ttyAM0`.
