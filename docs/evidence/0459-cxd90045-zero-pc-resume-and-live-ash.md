# E0459 — `pt_regs`/kuser trace around `0x0402E790`: the PC=0 resume

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0457.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **User entry is confirmed and the demand page is delivered [C].** The classification
   trace shows the first user fetch fault at **`0x0402E790`** (ld.so entry), a data fault
   at `0x0404E85C`, and then the run stops on a **VA-0 fetch with `PC = 0x0`**
   (`unicorn_error`).
2. **The only kuser-helper hit is a kernel-context call [C].** The trace at
   `0xFFFF0FA0` (`memory_barrier`) records exactly one hit with
   `r0 = 0, r1 = 1, sp = 0x60472800`, **`lr = 0x6010DF38`** — i.e. the return address is
   `ret_to_user + 4` (`0x6010DF34 + 4`), a **kernel** stack/return context, not the
   ld.so user return (`0x0402Exxx`) expected for the first userspace barrier call.
   So the helper was entered through the kernel's `ret_to_user`/vector path, and the
   subsequent resume lands at `PC = 0`.
3. **The register trace at `0x0402E790` captured only empty dicts [C]**, so the exact
   user `pt_regs` at the entry fetch still needs the dedicated frame dump
   (`ret_to_user [SP+0x00..0x44]`), not the `--trace-reg` hook (which returned `{}` for
   that address in this run).
4. **No shell [C]:** `serial 0 B`, `svc_hits = 0`, `user_entries = 0`.

## 1. Evidence

| item | value |
| --- | --- |
| user entry fault | `0x0402E790` prefetch, delivered [C] |
| other faults | `0x0404E85C` data [C] |
| stop | `PC = 0x0` (VA-0 fetch, `unicorn_error`) [C] |
| kuser hit | 1× `0xFFFF0FA0`, `r0 0, r1 1, sp 0x60472800, lr 0x6010DF38` (= `ret_to_user+4`) [C] |
| `--trace-reg 0x0402E790` | one hit with empty register dict [C] |
| ret_to_user trace | 45 hits, register captures empty [C] |
| shell | none (`serial 0 B`, `svc_hits 0`) |

## 2. Implemented

No production code change this round (diagnostic round). Artifacts:
`artifacts/analysis/e0458/` (report with `trace_reg_values`, run log, tty log).

## 3. Next step

1. **Dump the real `pt_regs` frame** in `_deliver_user_exception` for the `0x0402E790`
   prefetch abort and again at `ret_to_user` (`[SP+0x00..0x44]`, including
   `ARM_pc +0x3C`, `ARM_lr +0x38`, `ARM_cpsr +0x40`), using a physical-memory dump in the
   hook (not `--trace-reg`, which returned empty dicts).
2. **Trace the kernel `ret_to_user`/vector path around `0x6010DF34`** to see why the
   resume PC is 0 and why a kuser barrier is invoked from a kernel-context `lr`
   (`0x6010DF38`); check whether `__pabt_usr`/`_emulate_banked_store` clobbers the
   `pt_regs` PC slot, and whether the kuser helper hook at `0xFFFF0FA0` returns through a
   zeroed LR.
3. Fix the frame/return restoration, then verify `0x0402F666`/`0x04031AF0`, `svc_hits`
   and capture the live `/bin/ash` prompt over `ttyAM0`.
