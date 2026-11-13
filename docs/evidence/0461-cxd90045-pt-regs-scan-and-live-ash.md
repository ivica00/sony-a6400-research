# E0461 — `pt_regs` base located: `ARM_pc` is correct in the frame; `PC=0` is a restore-path issue

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0460.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The real base is `SP` itself (`ti + 0x1FB0`), not `SP - 0x48` [C].** A base finder
   (`_find_pt_regs_base`) now probes `ti + 0x1FB0`, `+0x1FB8`, `+0x1FA8` and a
   `SP-0x100..SP+0x100` sweep, accepting a frame whose `cpsr` slot (`+0x40`) has mode
   bits `0x10` and whose `pc` slot (`+0x3C`) is a userspace address
   (`0x8000..0x5FFFFFFF`, `0` rejected). At `do_PrefetchAbort` / `do_page_fault`
   entry the probe finds base **`0x7DC0FFB0`** with **`ARM_pc = 0x0402E790`** and
   **`ARM_cpsr = 0x70`** (USR+Thumb) for the first ld.so fetch, and `ARM_pc = 0x0404E85C`
   for the later data fault.
2. **`ARM_pc` is NOT zeroed by the abort delivery [C].** The frame recorded at
   `ret_to_user` also still has `ARM_pc = 0x0402E790` (`ARM_lr` slot `0`, expected at the
   ld.so entry point; `ARM_cpsr` slot `0x30`). So the `PC = 0x0` stop is **not** produced
   by `_deliver_user_exception` or `vector_stub` — the frame handed to `ret_to_user`
   already contains the correct user PC.
3. **Therefore the `PC=0` must occur at/after the final user restore [I]:** the tail of
   `ret_to_user` (`ldmia sp,{r0-pc}^` / `movs pc, lr`) or Unicorn's T-bit↔PC-LSB coupling
   (even PC `0x0402E790` with `T=1`) is the remaining suspect; the earlier kuser hit with
   `lr = 0x6010DF38` (`ret_to_user+4`) is consistent with the kernel-side return path, not
   with a clobbered user frame.
4. **No behavioural change yet [C]:** run still stops at VA-0 fetch `PC = 0x0`;
   `svc_hits = 0`, `kuser_hits = 1`, `serial 0 B`, no shell.

## 1. Evidence

| item | value |
| --- | --- |
| base finder | `ti+0x1FB0/+0x1FB8/+0x1FA8` + `SP±0x100` sweep, USR cpsr + user pc [C] |
| base at abort entry | `0x7DC0FFB0` (`SP`) [C] |
| frame at `do_PrefetchAbort` | `pc 0x0402E790`, `cpsr 0x70` [C] |
| frame at `do_page_fault` | `pc 0x0404E85C`/`0x0402E790`, `cpsr 0x70` [C] |
| frame at `ret_to_user` | `pc 0x0402E790`, `lr 0`, `cpsr 0x30` [C] |
| stop | VA-0 fetch `PC = 0x0` [C] |
| tests | finder accepts crafted user frame, rejects `pc = 0` (23 in `test_virtual_tlb.py`) — suite **1545 OK** |

## 2. Implemented

* `_find_pt_regs_base(sp)` — candidate + stack-sweep `pt_regs` base finder.
* `_record_user_frame(tag, sp)` — records `r0`, `ARM_sp +0x34`, `ARM_lr +0x38`,
  `ARM_pc +0x3C`, `ARM_cpsr +0x40` from the located base.
* Captures at `do_PrefetchAbort` (`0x601085EC`), `do_page_fault` (`0x60116D94`) and
  `ret_to_user` (`0x6010DF34`); report field `pt_regs_user_frames`.
* Two unit tests for the base finder.

## 3. Next step

1. **Disassemble and hook the tail of `ret_to_user`** (`0x6010DF34..0x6010DFD0`) to find
   the final `ldmia sp,{r0-pc}^` / `movs pc, lr` and capture the frame immediately before
   it; confirm `ARM_pc` still `0x0402E790` there.
2. **Check Unicorn's T-bit↔PC-LSB coupling on the restore**: the user `cpsr` slot has
   `T=1` with an even PC; if the restore writes CPSR before PC (or vice versa), Unicorn may
   clear T and decode ARM at `0x0402E790` (bytes belonging to Thumb code), which is a
   plausible route to the observed `PC = 0x0`. Verify by single-stepping the restore
   instruction and dumping `CPSR`/`PC` before/after.
3. If needed, emulate the final restore manually (write registers from the frame, then set
   CPSR, then PC with the correct LSB) and continue; then verify `0x0402F666`/`0x04031AF0`,
   `svc_hits` and capture the live `/bin/ash` prompt over `ttyAM0`.
