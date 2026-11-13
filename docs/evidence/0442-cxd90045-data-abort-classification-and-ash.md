# E0442 — Data-abort vs prefetch-abort classification for `0x04031AF0`

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0441.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **Classification is now structural and explicit [C].** Dedicated
   `UC_HOOK_MEM_READ_UNMAPPED` / `UC_HOOK_MEM_WRITE_UNMAPPED` hooks capture the exact
   faulting address and access type (`_last_unmapped`, `_last_unmapped_write`) before
   `emu_start` exits, and the run loop routes any captured READ/WRITE access to
   `_deliver_data_abort` (`DFAR = address`, `DFSR = 0x5`/`0x805`). Only instruction fetch
   or an unknown user-mode fault with **no** captured memory access is a prefetch abort.
   Every fault is recorded in `fault_classification_trace`
   (`pc`, `address`, `kind`, `write`, raw Unicorn message).
2. **The E0436 hypothesis is confirmed for kernel data faults [C].** Trace entries now
   show the exec-BSS faults as `kind='data'`:
   `0x6025DB1C@0x48AC6 write`, `0x6025DB34@0x0404E85C write`, and the futex probe
   `0x6015BDCC@0` read — exactly the READ/WRITE routing the task asked for.
3. **But `0x04031AF0` is NOT a READ/WRITE_UNMAPPED [C].** All of its faults report the
   raw message **`Unhandled CPU exception (UC_ERR_EXCEPTION)`** with
   `effective_address = None` and `mnemonic = None`, and **neither** the generic nor the
   specific unmapped hooks fire for that PC. That is not a data-load page fault signature:
   Unicorn cannot produce an address/decoded instruction for the PC, so the fault has no
   memory-access information to classify. It remains delivered as a prefetch abort
   (unknown-user-fault fallback) and still loops 8×; the guard stops the run (17 s).
4. **Consequence [I].** The remaining issue is the emulator's handling of the instruction
   at `0x04031AF0` itself (decode/execution state), not the DFAR/IFSR classifier: a true
   `UC_ERR_READ_UNMAPPED` always carries a readable effective address (as shown by the
   three kernel entries) and would now be routed to `do_DataAbort`.
5. **No SWI / no shell [C]:** `svc_hits = 0`, `enable_svc_dispatch` stays off, serial 0 B.

## 1. Evidence

| item | value |
| --- | --- |
| hooks | `UC_HOOK_MEM_READ_UNMAPPED` / `UC_HOOK_MEM_WRITE_UNMAPPED` installed |
| kernel data faults | `0x6025DB1C@0x48AC6` (write), `0x6025DB34@0x0404E85C` (write), `0x6015BDCC@0` (read) → `kind='data'` [C] |
| `0x04031AF0` faults | message `Unhandled CPU exception (UC_ERR_EXCEPTION)`, address `None`, `kind='prefetch'` [C] |
| guard | `[67312368, 67312368, 16]`, count 8, run 17 s |
| user entries | 20 (until `0x04031AF0`) |
| stack | `task 0x7E36DBE0` valid, `svc_stack_refreshes` 51 |
| `handle_mm_fault` | `0x00000000` for `0x04031AF0` (from E0441; still success) |
| tests | 2 new hook/capture tests — suite **1514 OK** |

## 2. Implemented

* READ/WRITE unmapped hooks + exact address/type capture; fallback from the generic
  `self.unmapped` entry when only that hook fired.
* Data vs prefetch decision: captured READ/WRITE → `_deliver_data_abort`; fetch or
  unknown user fault without captured access → `_deliver_prefetch_abort`.
* `fault_classification_trace` with raw Unicorn message for every fault.
* Two unit tests for the capture hooks.

## 3. Next step

1. **Explain the `UC_ERR_EXCEPTION` at `0x04031AF0`:** verify the instruction bytes the
   emulator sees at that PC (`uc.mem_read(0x04031AF0, 4)` at the fault) and the CPU state
   (T bit, IT block) — if the runtime bytes differ from the ld.so file page, the page
   content is wrong (cramfs/demand-page); if the bytes match, Unicorn's Thumb-2 decoder
   rejects this specific instruction and the emulator needs a decode/exec fallback.
2. Once `0x04031AF0` executes, enable `enable_svc_dispatch=True` (E0438 SWI +
   intno 3/4 re-dispatch), verify `futex_init` and `svc_hits`, and continue to BusyBox
   `_start` (`0x0000C439`) and the live `/bin/ash` prompt over `ttyAM0`.
