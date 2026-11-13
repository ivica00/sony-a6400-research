# E0440 — Live SVC-stack delivery, `thread_info->task` validation and the unfinished verification

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0439.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **Root-cause fix implemented [C].** `_deliver_user_exception` no longer overwrites the
   SVC stack pointer with the stale `mode_sp['svc']` capture. After switching to SVC mode
   it uses the **live banked `SP_svc`** (Unicorn banks SP, so this is exactly the kernel
   stack the task returned to user on), validates
   `thread_info = SP & ~0x1FFF`, reads `thread_info->task` (translated through
   `_kernel_phys`), and only falls back to the captured value if `task == 0`.
   Every delivery is logged in `stack_delivery_trace` with `sp`/`thread_info`/`task`.
2. **`ret_to_user` refresh added [C].** The existing `ret_to_user` (`0x6010DF34`) hook
   (which already flushes the TLB) now also stores the live `SP` into
   `mode_sp['svc']`, reads `thread_info->task`, increments
   `svc_stack_refreshes`, and reports `last_thread_info` / `last_thread_task`.
3. **Verification run did NOT complete.** A 400M-instruction run with
   `--sony-override --cmdline-extra 'init=/bin/ash console=ttyAM0,115200n8'
   --trace-user-mode` was still running after ~30 minutes and was cancelled by the user,
   so **no claim** is made about the `0x04031AF0` page, `svc_hits`, BusyBox `_start` or
   the shell. The report artifact for it is therefore absent by design
   (`artifacts/analysis/e0440/nflasha1-boot-report.json` was never written).
4. **Suite: 1510 tests OK (30.6 s)** after the change — the machine still passes all
   existing tests; the new hook logic is exercised only in live runs.

## 1. What changed in `unicorn_machine.py`

* `mode_sp['svc']` is refreshed on **every** `ret_to_user` and
  `svc_stack_refreshes`/`last_thread_info`/`last_thread_task` are reported.
* `_deliver_user_exception`:
  * removed the `if self.mode_sp.get('svc') is None: return False` gate;
  * removed `reg_write(SP, mode_sp['svc'])` — the live SVC bank is kept;
  * computes `thread_info`/`task` from the live SP (with `_kernel_phys` translation);
  * falls back to the captured value only when `task == 0`;
  * logs `{pc, sp, thread_info, task}` in `stack_delivery_trace`.
* Report fields: `svc_stack_refreshes`, `last_thread_info`, `last_thread_task`,
  `stack_delivery_trace`.

## 2. Why the verification is incomplete

The run produced no report within the time budget, which is itself evidence that the new
delivery path changes execution (previous E0438 run finished a 320M/400M image in a few
minutes with 16 frames and the `do_page_fault+0x34` stop). Possible causes to check first:

* the validation read (`mem_read` of `thread_info->task`) is cheap, so a stall more likely
  means **execution now continues into a new loop** (e.g., repeated fault → delivery →
  return) or into a long kernel path rather than an emulator hang;
* the fallback branch may re-enter delivery when `task == 0` and the captured value is
  also invalid;
* Unicorn may be re-translating on every delivery because of the TLB flush on delivery.

## 3. Next step

1. Re-run with a shorter budget (e.g. 320M) and an instruction-limit stop, then inspect
   `stack_delivery_trace`, `svc_stack_refreshes`, `last_thread_task`, `do_page_fault_frames`
   and `user_mode_entries`; if the trace shows `task != 0` and `0x04031AF0` is passed,
   capture the BusyBox/ash frames.
2. If the run loops on the same fault, add a delivery guard (same PC + same VA budget)
   and log the `task`/`thread_info` at the loop point.
3. Only after that enable `enable_svc_dispatch=True` (E0438 SWI + intno 3/4 re-dispatch)
   and verify `futex_init`, `svc_hits`, then the live `/bin/ash` prompt over `ttyAM0`.
