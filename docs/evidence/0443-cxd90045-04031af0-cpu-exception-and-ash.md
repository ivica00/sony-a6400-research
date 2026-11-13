# E0443 — Live bytes/CPSR at `0x04031AF0`, Thumb-state coupling and the decoded-address Data Abort

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0442.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The live page is correct and the instruction is the file's instruction [C].**
   TTBR0 = `0x1DC1C000`, L1 = `0x1F13E831`, L2 = `0x00431E7E`, PA = `0x00431AF0`.
   Live bytes at `0x04031AE8..0x04031B00`:
   `e91a 2160 0a18 a260 0b58 33b9 1ae0 0833 …` — halfword at PC = **`0x580B`**
   (`ldr r3, [r1, r0]`), matching `ld-2.11.2.so` file offset `0x3AF0` byte-for-byte.
   **The page is not corrupt.**
2. **`0x04031AF0` is a register-indirect data load, not SWI/UNDEF [C].**
   At the fault: `CPSR = 0x00000070` (USR + Thumb), `r0 = 0x0001FF48`,
   `r1 = 0x0402E000`, `r2 = 0x0404DF48`, `sp = 0x5E864C70`, `lr = 0x0402E79F`.
   Effective address = `r1 + r0 = 0x0404DF48` — inside ld.so's **second PT_LOAD**
   (`vaddr 0x1FDA8`, memsz `0xB98`), i.e. a not-yet-demand-paged data page.
   Unicorn reports it as a bare `Unhandled CPU exception (UC_ERR_EXCEPTION)` with
   **no** `READ_UNMAPPED`/`WRITE_UNMAPPED` hook hit and `effective_address = None`,
   because the failure is a guest **translation fault** (not a physical unmapped access).
3. **Decoded-address Data Abort implemented [C].** The fallback now walks the live page
   (TTBR0 → L1 → L2 → PA), decodes the faulting Thumb instruction with capstone,
   computes `base + offset` (`0x0404DF48`) and calls `_deliver_data_abort` with that
   address (`fault_classification_trace` entry `kind='data-decoded'`). The first such
   delivery was observed. The capture list is capped at 8 dumps, so later repeats fell
   back to the prefetch path; raising the cap and verifying the page install is the
   immediate next step.
4. **Two real emulator bugs fixed on the way [C]:**
   * **Unicorn couples CPSR.T to the PC LSB**: writing an even PC clears Thumb state
     (verified: `CPSR 0x70` + even PC → `0x50`; `CPSR 0x50` + odd PC → `0x70`). The
     TTBR0 capture helper now restores the PC with the correct LSB, so the dumps show
     `CPSR 0x70` and user execution stays in Thumb.
   * The same helper previously clobbered `r0..r3/lr`; it now saves/restores them.
5. **SVC (#0) gate [C]:** a mapped page alone is not a SWI. SWI dispatch now requires
   the live halfword at PC to be `0xDF00` (`svc #0`), so page faults are no longer
   turned into supervisor calls (`svc_hits = 0` in this run).
6. **No shell [C]:** run stops at the guard/prefetch fallback (`0x6010DE20`,
   `__pabt_usr`), user entries 20, serial 0 B.

## 1. Evidence

| item | value |
| --- | --- |
| TTBR0 / PTE walk | `0x1DC1C000` → L1 `0x1F13E831` → L2 `0x00431E7E` → PA `0x00431AF0` [C] |
| live bytes | `e91a21600a18a2600b5833b91ae00833…`, halfword at PC `0x580B` [C] |
| fault state | `CPSR 0x70`, `r0 0x1FF48`, `r1 0x0402E000`, `sp 0x5E864C70`, `lr 0x0402E79F` [C] |
| effective address | `r1 + r0 = 0x0404DF48` (ld.so second PT_LOAD) [C] |
| exception | bare `UC_ERR_EXCEPTION`, no unmapped hook, `effective_address=None` [C] |
| decoded delivery | `kind='data-decoded'`, address `0x0404DF48` delivered once [C] |
| T-bit coupling | even PC clears T; odd PC sets T (direct CPSR/PC writes) [C] |
| SWI gate | requires halfword `0xDF00`; `svc_hits=0` this run [C] |

## 2. Implemented

* `_read_cp15_ttbr0()` (register-preserving, T-bit-safe PC restore).
* `_capture_live_fault_page()`: TTBR0/L1/L2 walk, PA, live bytes, halfwords, regs.
* `_decode_fault_address()`: capstone Thumb/ARM decode of `[base, offset]` → VA.
* Fallback path: mapped page + non-`svc` → decoded Data Abort delivery.
* SVC gate on the live `0xDF00` halfword.

## 3. Next step

1. Raise `live_fault_dumps` cap (or keep a dedicated decode path independent of the cap)
   and re-run: verify `_deliver_data_abort(0x0404DF48)` results in a present PTE for
   `0x0404D000` after `ret_to_user` and that `0x04031AF0` executes exactly once.
2. If the page installs but Unicorn still faults, drop the translation cache for
   `0x0404D000` after the delivery (as done for `0x04031000`).
3. Then enable `enable_svc_dispatch=True` (E0438 SWI + intno 3/4), verify `futex_init`
   and `svc_hits`, and continue to BusyBox `_start` (`0x0000C439`) and live `/bin/ash`
   over `ttyAM0`.
