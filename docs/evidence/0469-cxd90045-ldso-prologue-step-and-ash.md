# E0469 — `ld-2.11.2.so` `_start` prologue interpreted: execution advances into the callee

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0468.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The prologue is now executed faithfully, not faulted [C].** A bounded Capstone-based
   Thumb interpreter `_emulate_thumb_prologue(pc, cpsr)` handles exactly the `_start`
   sequence at `0x0402E790`..`0x0402E79A`:
   `ldr.w sl,[pc,#0x68]` (literal at `0x0402E7FC`),
   `ldr.w r4,[pc,#0x68]` (literal at `0x0402E800`),
   `mov r0, sp`, and `bl 0x04031AA8` (setting `LR = 0x0402E79F`).
   It is invoked when the pending user resume targets `0x0402E791`, and the run then
   continues at the callee instead of raising `UC_ERR_INSN_INVALID` at `0x0402E798`.
2. **Live trace proves the manual execution [C]:**
   `user_entry_trace` = `0x0402E790` (`ldr`), `0x0402E794` (`ldr`), `0x0402E798` (`mov`),
   `0x0402E79A` (`bl`), all with `cpsr 0x30`, `thumb True`, tag `manual`; `kuser_hits = 4`.
3. **New blocker, same TCG root cause one level deeper [C]:** execution reaches the
   callee `0x04031AA8` (prefetch fault delivered for the freshly demand-paged page), then
   `0x04031AAC` raises **`UC_ERR_INSN_INVALID`** and the run stops at `PC = 0x04031AB0`
   (`svc_hits = 0`, `serial 0 B`, no shell). The interpreter therefore needs to generalise:
   the first instructions of *any* newly entered user Thumb page must be stepped manually
   (or via the INSN_INVALID fallback), not just the ld.so entry.
4. **Unit-tested interpreter [C]:** the test builds the four prologue instructions plus the
   two literal words and asserts `PC -> 0x04031AA8`, `LR = 0x0402E79F` and the trace order
   `ldr, ldr, mov, bl`; `test_virtual_tlb` is 31 tests OK.

## 1. Evidence

| item | value |
| --- | --- |
| prologue disasm (`ld-2.11.2.so` file offset `0x790`) | `dff868a0` `dff86840` `6846` `03f085f9` [C] |
| literals | `0x0402E7FC` (sl), `0x0402E800` (r4) [C] |
| interpreter result | `PC 0x04031AA8`, `LR 0x0402E79F`, trace `ldr,ldr,mov,bl` [C] |
| live manual trace | 4 entries `manual` at `0x790/0x794/0x798/0x79A`, cpsr `0x30` [C] |
| next fault | `0x04031AAC` `UC_ERR_INSN_INVALID`, stop `PC 0x04031AB0` [C] |
| shell | none (`serial 0 B`, `svc_hits 0`) |
| tests | `test_virtual_tlb` 31 OK [C] |

## 2. Implemented

* `_user_pa()` / `_read_user32()` / `_read_user_bytes()` — user-VA physical reads through
  `_walk_user_va()` (whose `pa` field is a hex string, now parsed).
* `_emulate_thumb_prologue()` — Capstone-driven bounded interpreter for `ldr.w` literal,
  `mov reg,reg`, and `bl`; returns `(new_pc, cpsr, trace)` at the branch.
* Run-loop hook: on the pending user resume to `0x0402E791`, emulate the prologue, record
  the trace entries (tag `manual`), set registers and continue at the callee.
* Unit test for the interpreter.

## 3. Next step

1. **Generalise the interpreter to a per-page entry stepper:** when `UC_ERR_INSN_INVALID`
   fires in user Thumb mode, emulate the offending instruction(s) with Capstone and resume
   (bounded to 2–4 instructions per attempt), so every freshly demand-paged page gets over
   the TCG ARM/TB initialisation gap (`0x04031AAC`, then `0x0402F666`, `0x04031AF0`).
2. Alternatively single-step each user entry with explicit `CPSR = 0x30` and odd PC before
   the bulk slice, which initialises the Thumb TB for that page.
3. Then verify `svc_hits` (ld.so/BusyBox syscalls) and capture the live `/bin/ash` prompt
   over `ttyAM0`.
