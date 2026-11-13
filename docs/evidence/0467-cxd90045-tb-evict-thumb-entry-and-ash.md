# E0467 — TB eviction + Thumb entry warm-up attempt: reverted, plain pending resume kept

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0466.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The requested mechanism was implemented [C].** When the run loop consumes
   `_pending_user_resume = (0x0402E791, 0x30)` it now, in the stopped state:
   `_set_pc_and_cpsr()`, `uc.ctl_remove_cache(page, page+0x1000)` for the
   `0x0402E000` entry page, `uc.ctl_flush_tb()`, then a 4-step `count=1` Thumb warm-up
   from `begin = 0x0402E791`, re-asserting `PC | 1` and `CPSR = 0x30` between steps.
2. **The warm-up made the run worse and was reverted [C].** Live result: stop at
   **`0x0402E794`** (`unicorn_error`, classification `data` at `0x0402E794`),
   `user_entry_trace = []`, `user_mode_entries = 0`, `user_restores = 1` — the
   single-instruction steps faulted instead of producing Thumb TBs. The `count=1` path
   therefore is **not** a usable warm-up here (each `emu_start` from the restored state
   re-entered with a fault at the first 4-byte-instruction boundary).
3. **The code was returned to the E0466 pending-resume behaviour [C]:** a clean
   re-run reproduces `user_entry_trace = 0x0402E790 / cpsr 0x30 / thumb True`,
   `user_restores = 2`, `user_mode_entries = 1`, `kuser_hits = 3`, then the known
   `UC_ERR_INSN_INVALID` at `0x0402E798` and stop `PC = 0x0402E79C`
   (`svc_hits = 0`, `serial 0 B`, no shell).
4. **Suite is green [C]:** 1557 tests, all OK (new test: `ctl_remove_cache` availability
   on the machine + pending-resume defaults).

## 1. Evidence

| variant | result |
| --- | --- |
| eviction + 4× `count=1` warm-up | stop `0x0402E794` (data), `trace []`, entries 0 [C] |
| plain pending resume (kept) | `0x0402E790`/`cpsr 0x30`/`thumb True`, entries 1, `kuser_hits 3`, stop `0x0402E79C` [C] |
| suite | **1557 tests OK** [C] |
| shell | none (`serial 0 B`, `svc_hits 0`) |

## 2. Implemented

* Eviction + warm-up block in the run loop (implemented, measured, **reverted**).
* Kept: pending-resume consumption with `_set_pc_and_cpsr`, `ctl_flush_tb()`,
  `emu_start(begin = 0x0402E791)`.
* Unit test: `ctl_remove_cache` is available on the machine and pending-resume defaults
  are `None`.

## 3. Next step

1. **Warm-up must not re-enter `emu_start` from the restored state**: instead, let the
   *kernel* path execute the final `movs pc, lr`-equivalent once, or patch the entry
   instruction in guest memory for one step (labelled aid), so TCG sees a normal control
   transfer into `0x0402E790` while `CPSR.T = 1`.
2. Alternative: after eviction, drive one **manual Thumb instruction** in Python
   (decode with capstone, apply its effect, advance PC by 2/4) for `0x0402E790`,
   `0x0402E794`, `0x0402E798` only — enough to let TCG create Thumb TBs for the rest.
3. Then verify `0x0402F666`/`0x04031AF0`, `svc_hits`, and capture the live `/bin/ash`
   prompt over `ttyAM0`.
