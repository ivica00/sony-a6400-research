# E0456 — Thumb-2 `MCR` scan and first-userspace `TTBR0` refresh

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0455.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **Thumb-2 encoding scan added and unit-tested [C].** `scan_ttbr0_write_sites()` now also
   matches the 32-bit Thumb-2 `mcr p15,0,Rt,c2,c0,0` halfword pair
   (`hw1 == 0xEE02`, `(hw2 & 0x0FFF) == 0x0F10`, `Rt = (hw2 >> 12) & 0xF`) at 2-byte
   alignment, in addition to the ARM `0xEE020F10` word form. A unit test builds the pair
   (`0xEE02`,`0x3F10`) and expects `(0x60100000, 3)`; a negative test rejects other second
   halfwords.
2. **No Thumb-2 site exists in this kernel [C].** The live scan still reports exactly the
   same four ARM-mode sites (`0x6011A280`, `0x6011A34C`, `0x60124154`, `0x6035D280`), so
   `CONFIG_THUMB2_KERNEL` does **not** apply to the TTBR0-write instructions here — the
   Thumb-2 hypothesis for the dead hooks is falsified for this image.
3. **First-userspace refresh hook added [C].** A `UC_HOOK_CODE` over the user VA range
   (`0x1000..0x60000000`) detects the first USR-mode instruction, sets
   `_user_refresh_requested`, calls `uc.emu_stop()`, and the run loop then performs
   `_refresh_user_ttbr0()`/`_read_cp15_ttbr1()` **outside** the hook (no guest execution
   inside callbacks).
4. **The run still never reaches user mode [C]:** `_cached_ttbr0` is never set to the user
   `pgd` (`0x1DC1C000`), `ttbr0_write_hits = 0`, the user-range hook never fires
   (`user_entries = 0`), and the run stops at `__migrate_disable+0x30` with two VA-0 TLB
   misses. `kuser_hits = 1`, `svc_hits = 0`, `serial 0 B` — **no shell**.

## 1. Evidence

| item | value |
| --- | --- |
| Thumb-2 scan support | `hw1 == 0xEE02` + `(hw2 & 0x0FFF) == 0x0F10`, Rt from hw2[15:12] [C] |
| Thumb-2 sites found | **none**; still only the four ARM sites [C] |
| TTBR0 write hits | **`ttbr0_write_hits = 0`** [C] |
| first-user refresh | hook installed (`0x1000..0x60000000`), never fired [C] |
| live TTBR0 | not captured as `0x1DC1C000` [C] |
| stop | `__migrate_disable+0x30`, 2 VA-0 misses, `tlb_fills=2969` [C] |
| tests | Thumb-2 scanner positive/negative (20 in `test_virtual_tlb.py`) — suite **1542 OK** |

## 2. Implemented

* Thumb-2 halfword-pair scanning in `scan_ttbr0_write_sites()`.
* First-userspace `UC_HOOK_CODE` (`0x1000..0x60000000`) that stops the slice and refreshes
  `_cached_ttbr0`/`_cached_ttbr1` outside the callback.
* Two unit tests (Thumb-2 positive/negative).

## 3. Next step

1. **Explain why none of the four ARM TTBR0-write sites executes.** Test a control code
   hook on `ret_to_user` (`0x6010DF34`) with the same window form and a counter: if it
   fires, the hook mechanism is fine and the TTBR0 write genuinely happens elsewhere
   (different opcode, `TTBCR`/context-switch helper, or an MCR variant such as
   `c2,c0,0` written from a different site outside the scanned bytes).
2. **Break the chicken-and-egg:** hook `kernel_execve` (or its return) and read/prime
   TTBR0 there, or pre-seed `_cached_ttbr0` from `current->mm->pgd` using the **live
   frame SP** captured in the `ret_to_user`/exception-delivery frame rather than the
   stale SVC stack.
3. Once `_cached_ttbr0` holds `0x1DC1C000`, verify `0x0402F666`/`0x04031AF0` translate via
   the fill hook, `svc_hits` records ld.so/BusyBox syscalls, then capture the live
   `/bin/ash` prompt over `ttyAM0`.
