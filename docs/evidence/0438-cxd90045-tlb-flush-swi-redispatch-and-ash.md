# E0438 — TLB flush on `ret_to_user`, INTR abort re-dispatch and SWI Thumb offset

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0437.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **Real TLB flush implemented and exercised [C].** `_flush_tlb()` now calls Unicorn's
   `ctl_flush_tb()` (with `UC_CTL_TLB_FLUSH` fallback), and a `ret_to_user`
   (`0x6010DF34`) entry hook flushes **after** the kernel has written the new PTE.
   Live run: **`tlb_flushes = 253`**.
2. **Case A is excluded [C].** Despite flushing on every `ret_to_user`, the
   `0x04031AF0` fault still repeats exactly as before: 16 `do_page_fault` frames, same
   stop at `do_page_fault+0x34` (`0x60116DC8`), `user_entries = 20`, `prefetch = 106`,
   `aborts = 3`. So the loop is **not** a stale Unicorn TLB entry.
3. **Case B is the remaining suspect [C]/[I].** The page `0x04031000` (file offset
   `0x3000` of `ld-2.11.2.so`, first PT_LOAD) never becomes present:
   `handle_mm_fault` for the file-backed VMA apparently does not install the PTE (cramfs
   readpage / VMA path), so `do_page_fault` is re-entered until the secondary fault.
   Capturing the `handle_mm_fault` return value is the next measurement.
4. **INTR abort re-dispatch implemented [C].** `_on_interrupt` now handles
   `intno == 3` (prefetch: re-dispatch `_deliver_prefetch_abort` with addr = faulting PC)
   and `intno == 4` (data: `_deliver_data_abort` with `last_dfar`), in addition to
   `intno == 2` SWI — fixing the E0437 finding that registering `UC_HOOK_INTR` suppresses
   Unicorn's `UC_ERR_EXCEPTION` for aborts. Hook remains gated by `enable_svc_dispatch`
   (default off) pending a live verification run.
5. **Thumb SWI offset implemented [C].** `LR_svc = pc + 2` when `CPSR.T` is set,
   `pc + 4` otherwise; `CPSR = 0x13 | 0x80` (SVC, IRQ masked, ARM state), `SPSR = old CPSR`.

## 1. Evidence

| item | value |
| --- | --- |
| TLB flush | `ctl_flush_tb()` + `ret_to_user` hook; `tlb_flushes = 253` [C] |
| loop after flush | 16 `do_page_fault` frames, stop `do_page_fault+0x34`, same counters [C] |
| user-mode frame | `ARM_pc 0x04031AF0`, `ARM_cpsr 0x70`, `ARM_sp 0x5E864C70`, `ARM_lr 0x0402E79F` [C] |
| INTR re-dispatch | `intno` 3 → prefetch delivery, `intno` 4 → data delivery, unit-tested [C] |
| SWI offsets | Thumb `+2` / ARM `+4`, SVC `0x13|0x80`, unit-tested [C] |
| run counters | user 20, prefetch 106, aborts 3, svc 0 (hook off), serial 0 B |
| tests | 4 new/updated tests — suite **1502 OK** |

## 2. Implemented

* `_flush_tlb()` uses `ctl_flush_tb()`; `_tlb_flushes` counter + `tlb_flushes` report.
* `ret_to_user` code hook flushing translations on every kernel→user return.
* `_on_interrupt`: abort re-dispatch for `intno` 3/4; Thumb/ARM SWI return offset;
  SVC CPSR with IRQ masked, ARM state.
* Tests: `test_swi_lr_uses_thumb_state`, `test_intr_aborts_are_redispatched`,
  `test_tlb_flush_is_counted`, updated unknown-exception test.

## 3. Next step

1. **Measure `handle_mm_fault`**: capture its return value (VM_FAULT_* code) for the
   `0x04031AF0` prefetch fault by tracing the return site inside `do_PrefetchAbort`; if it
   returns `VM_FAULT_SIGBUS`/`VM_FAULT_OOM`, inspect `cramfs_readpage` / the VMA around
   `0x04031000`.
2. If `handle_mm_fault` succeeds, dump the L1/L2 PTE for VA `0x04031000` after the first
   pass (`set_pte_ext`) to confirm the hardware PTE is valid but not used by Unicorn.
3. Re-enable `enable_svc_dispatch` with the new abort re-dispatch and verify `futex_init`
   still passes, `svc_hits` records ld.so syscalls, then continue to BusyBox `_start`
   (`0x0000C439`) and the live `/bin/ash` prompt over `ttyAM0`.
