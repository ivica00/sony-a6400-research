# E0499 — Post-`brk` resume lands at `0x0403EB20` (skipping the thunk `pop`), so the next function reads `0x5E865030` above the stack page

Date: 2026-11-13. **Strictly offline.** No camera access, no USB, no writes. Inputs: E0414
dumps, E0416 contract, E0420–E0498 offline chain, the read-only dump set in
`artifacts/dumps/a6400-nflasha-readonly/` (full `/proc/kallsyms`).

## 0. Short answer

1. **The two sites are decoded [C].** `0x0403E980` is the `__brk` wrapper caller
   (`push {lr}; mov r3,r0; mov.w ip,#0x2d; bl 0x0403EB10; cmn.w r0,#0x1000; …;
   ldr pc,[sp],#4`), and `0x0403EB20` is a *different* function
   (`ldr r1,[pc,#0x30]; ldr r2,[r2,#0x5c]; add r1,pc; push {r4}; ldm.w r1,{r3,r4};
   ldr r0,[r1,#8]; …`).
2. **`register trace shows the post-syscall resume is wrong [C].`** At `0x0403EB20`
   after the `brk` syscall the trace still shows **`SP = 0x5E864C04`** (the thunk's
   pushed frame) and **`LR = 0x0403E98D`** (the wrapper return address), while PC is
   `0x0403EB20` — i.e. the `pop {r7, pc}` at `0x0403EB16` and the wrapper epilogue
   (`0x0403E98C..0x0403E9A2`) were skipped. The return address from the SVC *is*
   `0x0403EB16` (E0496/E0498), so the kernel return path is not restoring
   `ARM_pc = 0x0403EB16`/`ARM_sp = 0x5E864C04` as a pair.
3. **Consequence [C]:** with the skipped epilogue, `r2` is still `0x5E864FD4` (initial
   stack data) when `0x0403EB22 ldr r2,[r2,#0x5c]` executes, so the effective address is
   `0x5E865030` — page `0x5E865000`, i.e. just above the initial stack page.
4. **The page really is unmapped [C]:** `do_page_fault` is entered for
   `0x5E865030` (`r1 = 0x5` read translation, `pt_regs.pc = 0x0403EB22`,
   `pt_regs.cpsr = 0x600000F0`, `pt_regs.sp = 0x5E864C04`), and the PTE re-walk shows
   `0x5E865000`: `L1 0x1F17F831`, **`L2 0x00000000` (invalid)** — no VMA/page behind it,
   so the fault is fatal and the run settles at `instruction_limit`
   (`PC 0x6025ED38`).
5. **No shell yet [C]:** `svc_hits = 1` (`brk`, `r7 = 45`), `serial 0 B`, `gen = 15`,
   `rec = 2`, `restores = 8`, `entries = 20`.

## 1. Evidence

| item | value |
| --- | --- |
| wrapper | `0x0403E980 push {lr}; 0x0403E982 mov r3,r0; 0x0403E984 mov.w ip,#0x2d; 0x0403E988 bl 0x0403EB10; 0x0403E98C cmn.w r0,#0x1000; …; 0x0403E9A2 ldr pc,[sp],#4` [C] |
| next function | `0x0403EB20 ldr r1,[pc,#0x30]; 0x0403EB22 ldr r2,[r2,#0x5c]; 0x0403EB24 add r1,pc; 0x0403EB26 push {r4}; 0x0403EB28 ldm.w r1,{r3,r4}; 0x0403EB2C ldr r0,[r1,#8]` [C] |
| pre-svc | `0x0403EB14`: `r7 = 0x2D` (45), `SP = 0x5E864C04`, `LR = 0x0403E98D`, `CPSR 0x600000F0` [C] |
| post-svc | `0x0403EB20`: **`SP = 0x5E864C04`**, **`LR = 0x0403E98D`**, `r0 = 0x55000`, `r2 = 0x5E864FD4` [C] |
| fault | `0x0403EB22 ldr r2,[r2,#0x5c]` → `0x5E865030`; `do_page_fault` r1=0x5 [C] |
| PTE | `0x5E865000`: `L1 0x1F17F831`, `L2 0x00000000` (invalid) [C] |
| run | `instruction_limit` `PC 0x6025ED38`, `svc_hits 1`, `serial 0 B` [C] |
| tests | suite unchanged; diagnostic hooks only |

## 2. Implemented

* `e0499_trace` register hooks at `0x0403E980/98C/992/9A2`, `0x0403EB10/20/22/26/28/2C`.
* Captured the `do_page_fault` frame for the `0x5E865030` access (already in
  `do_page_fault_frames`) and the invalid-PTE rewalk for `0x5E865000`.

## 3. Next step

1. **Trace the kernel syscall return path frame-for-frame:** at `vector_swi`
   (`0x6010DFA0`) dump the 18-word `pt_regs` it built, then at `ret_fast_syscall`
   (`0x6010DEC0..DEF8`) and `ret_to_user` (`0x6010DF34..DF64`) dump the same words and the
   register state; verify `ARM_pc = 0x0403EB16` is restored **together with**
   `ARM_sp = 0x5E864C04` and `ARM_lr = 0x0403E98D` (so the thunk `pop {r7,pc}` runs).
2. If `ret_fast_syscall`'s banked `ldmdb sp,{…}^` at `0x6010DEEC` is still executed
   natively (it is only skipped at `0x6010DF58`), emulate it like
   `_emulate_vector_stmdb()` from the frame words, then re-run; the wrapper epilogue
   should execute and the `0x5E865030` read should disappear (it is a side effect of the
   skipped `pop`).
3. Then verify the fuller syscall chain (`uname`, `open`, `mmap2`, `set_tls`, `write`,
   `read`), BusyBox `_start 0x0000C439`, and the live `/bin/ash` prompt over `ttyAM0`.
