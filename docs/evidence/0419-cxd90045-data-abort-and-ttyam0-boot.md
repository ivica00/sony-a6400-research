# E0419 — Guest data-abort delivery, `__ex_table` verification and `ttyAM0` status

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0418 exclusive
analysis. Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The fault site is the kernel's own futex capability probe.** `cmpxchg_futex_value_locked`
   (0x6015BD7C) is called with a NULL user address; the faulting instruction is
   `ldrex r2,[r5]` at 0x6015BDCC with `r5 = 0` (return address 0x6012B630). A matching
   `__ex_table` entry exists in the image: **entry at VA 0x60454438 = (insn 0x6015BDCC,
   fixup 0x60364BD4)**, and the fixup code is `mov r7,r3; b 0x6015BDE4` — the `-EFAULT`
   path expected by `futex_init()`. **[C]**
2. **ARMv7 data-abort delivery implemented** in `unicorn_machine.py`: on a guest memory
   fault it populates DFAR/DFSR through emulated `mcr p15,0,rX,c6/c5,c0,0` (Unicorn
   models both CP15 registers, verified by round-trip), switches to ABT mode
   (`CPSR 0x17|0xC0`), writes banked `SPSR_abt` and `LR_abt = PC+8`, and enters the high
   vector at **0xFFFF0010**, with a bounded double-fault guard (limit 4096, same-PC > 8)
   and an abort trace in the report. **[C]**
3. In a 400 M-instruction run, **2 data aborts were delivered** (futex probe at
   0x6015BDCC/VA 0, then a write fault at 0x60111104/VA 0), but the kernel still printed
   **"Unhandled fault" / "Internal error"** and Oopsed at the futex instruction instead of
   applying the `__ex_table` fixup; the run then reached `cpu_v7_do_idle+0x8` with the init
   call path killed. Both DFSR=0x5 (translation section) and DFSR=0x7 (translation page)
   gave the same result, so the abort *reaches* the kernel fault path but its kernel-mode
   probe/fixup decision does not pick up the exception table. **[C]**
4. Consequently **`ttyAM0` serial output is still 0 bytes** in
   `artifacts/analysis/e0419-ttyam0-init/nflasha1-ttyAM0.log`. The PL011 console
   registration, `cramfs` root mount (0x00700000) and `/sbin/init` are **not reached**;
   no new unmapped MMIO peripheral was probed. No console/boot-to-userspace claim is made.
5. Tested: 5 new tests for CP15 DFAR round-trip, ABT-mode/vector/banked-register state,
   write-fault WnR encoding and double-fault guard, plus a static `__ex_table` entry check
   (`insn 0x6015BDCC → fixup 0x60364BD4`, entry VA 0x60454438). **[C]**

## 1. Evidence

| item | value |
| --- | --- |
| fault | `ldrex r2,[r5]`, `r5=0`, PC 0x6015BDCC, lr 0x6012B630 |
| `__ex_table` | entry VA 0x60454438: insn 0x6015BDCC, fixup 0x60364BD4 (`mov r7,r3; b 0x6015BDE4`) |
| delivery | 2 aborts: (0x6015BDCC, VA 0, fsr 0x5 read), (0x60111104, VA 0, fsr 0x805 write) |
| kernel reaction | `Unhandled fault` + `Internal error` Oops at 0x6015BDCC, then idle |
| serial | 0 bytes |
| new MMIO | none |
| suite | **1467 tests OK** (see status card) |

## 2. Data-abort delivery design

* Fault detection: a `UC_ERR_READ_UNMAPPED` / `UC_ERR_WRITE_UNMAPPED` / `UC_ERR_EXCEPTION`
  in the slice run is decoded (`_fault_state`) to instruction mnemonics and the effective
  address; write faults are detected from `str*`/`stm`/`push` mnemonics.
* State population: DFAR/DFSR via emulated `mcr` instructions in a scratch code page
  (works with the real kernel because kernel lowmem maps it; falls back to a physical
  address for MMU-off synthetic test machines).
* Exception entry: ABT mode (`0x17`, I/F masked), banked `SPSR_abt` = interrupted CPSR,
  `LR_abt = PC+8` (the kernel's data abort stub subtracts 8), `PC = 0xFFFF0010`.
* Guards: 4096-abort cap and a same-PC repeat limit (>8) so unrecoverable faults fail
  closed; every delivery is recorded in `data_abort_trace` with pc/address/fsr/write.

## 3. Why the `__ex_table` recovery did not happen

The abort is delivered and the kernel prints its own fault report (so DFAR/DFSR reached
`do_DataAbort`), but the kernel-mode fault path takes the fatal branch instead of the
`search_exception_tables()` fixup. Candidates still to verify:

1. The saved `pt_regs->ARM_pc` seen by `instruction_pointer()` may not be 0x6015BDCC
   (e.g. the stub's `sub lr, lr, #8` vs the vector entry used), so the table lookup misses.
2. The supplied fsr value must match the kernel's `fsr_info` dispatch exactly
   (0x5 and 0x7 both produced the fatal path in this build).
3. A labelled bring-up alternative: patch the futex probe call site to skip the NULL
   probe, or map VA 0 in the guest page tables *after* `paging_init` (the attempted
   `start_kernel` boot patch did not hit in this build — `boot_patch_hits` empty — so the
   symbol/patch point needs revisiting).

## 4. Next step

1. Capture `pt_regs`/`instruction_pointer` inside the delivered abort (trace hook on
   `do_DataAbort`/`die`) and fix the saved-PC/fsr combination so the `__ex_table`
   fixup at 0x60364BD4 is applied and `futex_init()` continues.
2. Then capture the first `ttyAM0` bytes from the PL011 console registration and continue
   to the `cramfs` mount and `/sbin/init`, logging every new unmapped MMIO peripheral.
3. Keep the data-abort path bounded and fail-closed; no fabricated console output.
