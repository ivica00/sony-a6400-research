# E0496 — SWI return path: `ret_fast_syscall` is never reached; `ret_to_user` frames after `brk` are kernel frames, so the user PC still resumes in SVC/ARM

Date: 2026-11-13. **Strictly offline.** No camera access, no USB, no writes. Inputs: E0414
dumps, E0416 contract, E0420–E0495 offline chain, the read-only dump set in
`artifacts/dumps/a6400-nflasha-readonly/` (full `/proc/kallsyms` used for the symbol
addresses: `ret_fast_syscall 0x6010DEC0`, `ret_to_user 0x6010DF34`,
`vector_swi 0x6010DFA0`, `sys_brk 0x6019EAA0`).

## 0. Short answer

1. **A real SWI return-address bug was found and fixed [C].** `UC_HOOK_INTR` reports the
   PC *after* the SVC instruction (`0x0403EB16` for the `svc #0` at `0x0403EB14`), so the
   old `LR = pc + 2` skipped `pop {r7, pc}` and used `0x0403EB18`. New
   `_svc_return_address(pc, thumb)` probes the instruction bytes and returns the true
   return address (`0x0403EB16`); unit test covers both "PC at SVC" and "PC after SVC".
2. **Two more user-return guards implemented [C]:** the banked `ldmdb sp,{…}^` at
   `0x6010DF58` is now skipped for USR frames (it loaded the user PC in SVC mode), and the
   generation restore at `0x6010DF64` switches to the USR bank **before** writing
   `r0..r12`, so the GPRs land in the user bank.
3. **Remaining defect is on the kernel side of the SVC [C]:** the new `e0496_kernel`
   trace shows that after the `brk` SVC the execution reaches `0x6010DF34`
   (`ret_to_user`) repeatedly with **`frame_gen = None`** and **kernel stacks**
   (`0x7DC0FFB0`, `0x7DC07FB0`, `0x7E3FFFB0`), `CPSR 0x40000053`/`0x60000053`,
   `SPSR 0xA0000053`/`0x20000053`/`0x93` — i.e. **no USR `pt_regs` frame is ever built**
   for the syscall return. The `ret_fast_syscall` hooks
   (`0x6010DEE0/DEE4/DEEC/DEF8`) never fire. The user stream later re-enters at
   `0x0403EB14..` with `CPSR 0x60000093`/`0x600000D3` (SVC|ARM), reproducing the E0495
   `r1 = 0` / `VA 0x8` failure.
4. **No shell yet [C]:** `svc_hits = 1` (`brk`, `r7 = 45`), `serial 0 B`, `rec = 2`,
   `gen = 16`, `restores = 8`, `entries = 20`, stop `instruction_limit`
   (`PC 0x6025ED38`).

## 1. Evidence

| item | value |
| --- | --- |
| `svc #0` | at `0x0403EB14`; `UC_HOOK_INTR` reports `pc = 0x0403EB16` [C] |
| old LR bug | `LR = pc + 2 = 0x0403EB18` (skipped `pop {r7,pc}` at `0x0403EB16`) [C] |
| fix | `_svc_return_address` byte probe → `0x0403EB16`; unit test [C] |
| banked ldmdb | `0x6010DF58` skipped for USR frames (no PC load in SVC) [C] |
| restore bank | `CPSR` set to USR before writing `r0..r12` at `0x6010DF64` [C] |
| kernel trace | `0x6010DF34` hits with `frame_gen=None`, kernel `SP 0x7DC0FFB0…`, `CPSR 0x40000053`, `SPSR 0xA0000053/0x93` [C] |
| fast path | `ret_fast_syscall` hooks never fire [C] |
| user re-entry | `0x0403EB14..` with `CPSR 0x60000093`/`0xD3` (SVC/ARM) [C] |
| result | `svc_hits 1`, `serial 0 B`, `instruction_limit` `PC 0x6025ED38` [C] |
| tests | new `test_svc_return_address_uses_true_instruction`; 41 in `test_virtual_tlb` [C] |

## 2. Implemented

* `_svc_return_address(pc, thumb)` (Thumb `0xDF00` / ARM `0xEF` probes) and its use in
  `_on_interrupt`.
* Skip of the native banked `ldmdb` at `0x6010DF58` for USR frames; USR-bank-first
  restoration at `0x6010DF64`.
* `e0496_kernel` trace hooks on `0x6010DEE0/DEE4/DEEC/DEF8` (`ret_fast_syscall`) and
  `0x6010DF34/DF50/DF58/DF64` (`ret_to_user`) recording `SP/LR/PC/CPSR/SPSR/frame_gen`.

## 3. Next step

1. **Trace the SWI vector entry itself:** hook `0xFFFF0008` (high-vector stub) and
   `0x6010DFA0` (`vector_swi` symbol) and record `CPSR`, `SPSR_svc`, `SP`, `LR`, `r7`.
   Confirm the high-vector page is mapped/executable and that `vector_swi` saves a
   `pt_regs` with `ARM_cpsr = 0x600000F0` and `ARM_pc = 0x0403EB16`.
2. If the vector stub is not modelled (Unicorn may not route the `0xFFFF0008` fetch),
   emulate the vector entry explicitly: build the 18-word `pt_regs` from the live user
   registers + `SPSR` + return PC on the SVC stack and jump directly to `vector_swi`
   (the documented E0430 pattern) so the kernel's syscall return path produces a USR
   frame.
3. Then re-run and verify `0x0403EB16..0x0403EB2C` executes in `USR|Thumb`, followed by
   the fuller syscall chain (`uname`, `open`, `mmap2`, `set_tls`, `write`, `read`),
   BusyBox `_start 0x0000C439`, and the live `/bin/ash` prompt over `ttyAM0`.
