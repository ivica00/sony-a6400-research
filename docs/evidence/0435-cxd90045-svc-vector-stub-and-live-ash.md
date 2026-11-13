# E0435 — `__dabt_svc`/`__pabt_svc` vector-stub delivery (implemented) and the bad-pgd oops (unchanged)

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0434 boot.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **Symmetric SVC-mode `vector_stub` delivery is implemented and unit-tested [C].**
   `_deliver_svc_exception(pc, cpsr, kind)` writes the 12-byte scratch frame
   `{r0, faulting_pc, cpsr}` at `VECTOR_SCRATCH_PA + 0x10` (VA `0x62002010`), sets
   `CPSR = 0x13|0xC0`, sets `r0 = scratch_va` and jumps **directly** to
   `__dabt_svc` (`0x6010D980`) or `__pabt_svc` (`0x6010DBA0`), **keeping the live SVC
   `SP` and `LR` untouched** (Unicorn banks SP, so the CPU is already on the kernel
   thread stack). `__dabt_svc`'s disassembly confirms the ABI:
   `sub sp,#0x44; stm sp,{r1..ip}; ldm r0,{r3,r4,r5}; … str r3,[sp,#-4]!;
   mov r3,lr; stm r7,{r2,r3,r4,r5,r6}` — i.e. `r0` = 12-byte frame, `lr` = fault-time
   kernel LR, `r2` = saved-SP slot.
2. **Data/prefetch deliveries now select the SVC path when `CPSR.M == 0x13` [C]**,
   still populating `last_dfar/last_dfsr` / `last_ifar/last_ifsr` for the
   `v7_early_abort` / `v7_early_pabort` MRC hooks; `search_exception_tables()` remains
   available to the kernel for genuine invalid probes (direct `__ex_table` fixups are
   unchanged for kernel-mode faults that have an entry).
3. **The bad-pgd oops is UNCHANGED with the new path [C]** — the SVC-vector hypothesis
   of E0434 is **falsified**. Live run again logs
   `Unable to handle kernel paging request at virtual address 04031af0`,
   `pgd = 7f146dd8`, `[04031af0] *pgd=00000003(bad)`, `Oops: 80000005`, and stops at
   `do_page_fault+0x34` (`0x60116DC8`) during `die()`. USR execution still starts
   (`user_mode_entries` 20 entries, `0x0402E790`, CPSR 0x70) but the run does not reach
   BusyBox `_start` or the shell; serial 0 B.
4. **Consequence for the next round:** the kernel is walking a page table whose
   `pgd` is not the current user mm's table when handling `0x04031af0` (bad entry `0x3`).
   The next step is to trace **`current`/`current->mm` and `do_page_fault` entry args**
   at the oops, and check whether PID 1 has already exited/fallen back (init_mm
   context) or whether our delivered `pt_regs`/`r2` slot misleads `do_DataAbort`.

## 1. Evidence

| item | value |
| --- | --- |
| `__dabt_svc` ABI | `0x6010D980`: `r0` = frame, live SVC SP, `lr` = fault-time LR [C] |
| `__pabt_svc` ABI | `0x6010DBA0`, same `svc_entry` shape [C] |
| scratch frame | `{r0, faulting_pc, cpsr}` at `0x62002010` [C] |
| SP/LR | preserved (SVC bank not overwritten) [C] |
| tests | `test_svc_data_abort_enters_dabt_svc_with_scratch_frame`, `test_svc_prefetch_abort_enters_pabt_svc_with_scratch_frame` — suite **1495 OK** |
| live run | 106 prefetch aborts, `pabt_mrc_hits=212`, user entries `0x0402E790..0x04031AF0`, stop `do_page_fault+0x34`, serial 0 B |
| oops | unchanged: `*pgd=00000003(bad)`, `Oops 80000005`, `04031af0` |

## 2. Implemented

* `_deliver_svc_exception` + SVC branches in `_deliver_data_abort` and
  `_deliver_prefetch_abort`.
* Two unit tests covering the scratch frame, the handler entry PC, the `r0` value and
  the preserved live SVC `SP`.
* Note: SVC-path deliveries are not yet included in `data_aborts_delivered`
  (reported `0` in this run) — counter accounting to be fixed in the next round.

## 3. Next step

1. At `do_page_fault` entry (`0x60116D94`) capture `r0/r1/r2`, and resolve
   `current`/`current->mm->pgd` (kernel `current` symbol) to see which mm the bad
   `pgd=7f146dd8` belongs to; print `do_DataAbort` entry args too.
2. Determine whether the kernel access to `0x04031af0` happens **after the user process
   has exited** (init_mm / no mm, kernel fallback path) or while PID 1 is still alive;
   that decides whether a fix belongs in `__ex_table`/probe handling or in the mm state.
3. Then continue to BusyBox `_start` (`0x0000C439`) and the live `/bin/ash` prompt over
   `ttyAM0` (kuser `0xFFFF0FE0`/`0xFFFF0FC0` are already emulated and will be reported
   via `kuser_hits` once reached).
