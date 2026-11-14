# E0495 — `__brk` epilogue decoded; the `VA 0x8` read happens because user code re-enters in SVC/ARM mode after the syscall

Date: 2026-11-13. **Strictly offline.** No camera access, no USB, no writes. Inputs: E0414
dumps, E0416 contract, E0420–E0494 offline chain, the read-only dump set in
`artifacts/dumps/a6400-nflasha-readonly/` (full `/proc/kallsyms` used for address checks).

## 0. Short answer

1. **`__brk` is decoded [C]** (`ld-2.11.2.so`, file offset `0x10B10`):

   ```
   0x0403EB10 push {r7, lr}
   0x0403EB12 mov  r7, ip
   0x0403EB14 svc  #0
   0x0403EB16 pop  {r7, pc}     ; return thunk (svc_trace returns 0x0403EB16)
   0x0403EB18 nop.w
   0x0403EB1C nop.w
   0x0403EB20 ldr  r1, [pc, #0x30]   ; next function (libc div helper)
   0x0403EB22 ldr  r2, [r2, #0x5c]
   0x0403EB24 add  r1, pc
   0x0403EB26 push {r4}
   0x0403EB28 ldm.w r1, {r3, r4}
   0x0403EB2C ldr  r0, [r1, #8]      ; <- VA 0x8 read
   ```

   The failing read is not a `pop`; the stepper's trace label `rec:pop` covers the
   `ldm.w` form at `0x0403EB28`. It reads from `r1`, which is **0** at that point.
2. **The real defect is mode, not the stepper operand [C].** The `e0495_trace` shows the
   whole `0x0403EB14..0x0403EB2C` block executing with **`CPSR = 0x60000093` (ARM, SVC
   mode) and `SP = 0x7DC0FF68` (kernel stack)** — user code is being re-entered in
   SVC/ARM instead of `USR|Thumb`. Consequently:
   * `0x0403EB20 ldr r1,[pc,#0x30]` / `0x0403EB24 add r1,pc` are decoded as ARM and
     compute a wrong GOT base → **`r1 = 0`**;
   * `0x0403EB28 ldm.w r1,{r3,r4}` then reads from `0` and `0x0403EB2C ldr r0,[r1,#8]`
     faults at **`VA 0x8`**;
   * the recovery `rec_state` at `0x0403EB28` confirms `cpsr = 0x60000093`,
     `sp = 0x7DC0FF68`, `r1 = 0`.
3. **The `svc #0` itself is correct [C]:** the hook at `0x0403EB14` shows user state
   (`CPSR 0x600000F0`, `SP 0x5E864C04`, `r7 = 0x2D = 45` `brk`), and `svc_trace` records
   `{pc 0x0403EB16, r7 45}`. The breakage happens on the **return** from the syscall:
   the re-entered user PC is restored while `CPSR` is still SVC/ARM and `SP` still the
   kernel bank.
4. **No shell yet [C]:** `svc_hits = 1`, `serial 0 B`, `rec = 2`, `gen = 15`,
   `restores = 8`, `entries = 20`, stop `instruction_limit` (`PC 0x6025ED38`).

## 1. Evidence

| item | value |
| --- | --- |
| `__brk` | `push {r7,lr}` / `mov r7,ip` / `svc #0` (`0x0403EB14`) / `pop {r7,pc}` [C] |
| next function | `0x0403EB20 ldr r1,[pc,#0x30]` … `0x0403EB28 ldm.w r1,{r3,r4}` / `0x0403EB2C ldr r0,[r1,#8]` [C] |
| pre-svc state | `CPSR 0x600000F0`, `SP 0x5E864C04`, `r7 0x2D` (45 = `brk`) [C] |
| post-svc state | `0x0403EB18..2C`: `CPSR 0x60000093` (ARM SVC), `SP 0x7DC0FF68` (kernel), `r1 = 0` [C] |
| fault | `0x0403EB2C` read at `VA 0x8` (r1=0) [C] |
| recovery state | `rec_state pc 0x0403EB28 cpsr 0x60000093 sp 0x7DC0FF68 r1 0` [C] |
| run | `svc_hits 1`, `serial 0 B`, `instruction_limit` `PC 0x6025ED38` [C] |
| kept | `e0495_trace` hooks (`0x0403EB14/16/20/24/26/28`), `rec_state` entries, target-page TB eviction on every fallback user resume [C] |

## 2. Implemented

* `e0495_trace` register snapshots across the `brk` epilogue and the following libc
  helper, plus `rec_state` (pre-recovery `r0/r1/r2/SP/LR/CPSR`).
* Target-page TB eviction (`ctl_remove_cache(page, page+0x1000)`) before every fallback
  `emu_start` on a user resume.
* `__brk` epilogue disassembly (file offset `0x10B10`).

## 3. Next step

1. **Fix the SVC return mode:** in the deferred SWI dispatch path
   (`_on_interrupt` → `0xFFFF0008`), make sure the syscall returns through
   `ret_to_user` with an **`USR|Thumb`** `pt_regs` (`ARM_cpsr = 0x600000XX`, user `SP`,
   user PC) and that no user PC is ever resumed while `CPSR` is SVC/ARM. The generation
   guard correctly refuses to restore a non-USR frame, which is why execution stays in
   SVC; the frame built by the syscall path must be USR instead.
2. Then re-run; the `0x0403EB20..0x0403EB2C` block should compute a valid GOT base
   (`r1 = 0x0404DE00`-style), `lsd/ldr` should not hit `VA 0x8`, and later SVCs (`uname`,
   `open`, `mmap2`, `set_tls`, `write`, `read`) should appear in `svc_trace`.
3. Finally verify BusyBox `_start 0x0000C439` and capture the live `/bin/ash` prompt over
   `ttyAM0`.
