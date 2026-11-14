# E0171 — Original Callback Unregistration: Wait, Interrupt, and Self-Call

Date: 2026-11-08. Offline continuation of E0170. No physical camera access, module loading, or production module changes.

## Executed Original ARM Code

`tools/research/probe_uvc_ptp_kernel_unregister.py` loads the original allocatable ELF sections of a6400 `osal_uipc.ko` (SHA-256 `3743275bc964a2804b80cde4f589f60876b795fbeeccd3cbf2c18a0da2dc8567`) and applies its ABS32/CALL relocations. Unknown relocations in those sections are rejected. It does not modify function bodies or execute module init.

The original unregister helper at `.text+0x2f3c`, wait helper at `.text+0x27a0`, wake helper at `.text+0x28e0`, and `free_cb` at `.text+0x2b24` were executed. Final `free_fblock`, lock/unlock, and `wake_up_process` are explicit service replacements. `schedule` is a stop boundary, not a simulated scheduler.

Queue, callback, current task/TID, callback TID, counters, and signal flags are explicit fixture data. Guards restrict execution to the listed original bodies and writes to fixture/original writable sections.

## Different Unregistration Contracts

| Case | Original Behavior Confirmed in Test |
|---|---|
| Callback not active, count=0 | Sets retire bit, does not wait, calls original `free_cb`, and clears the registered slot. |
| Active callback on another thread | Sets retire bit, writes waiter onto stack, releases guards, and reaches `schedule` before freeing. Registered slot remains preserved. |
| Active callback on the same thread/TID | Wait helper returns 0 without waiting. Unregister calls `free_cb` and clears slot even though fixture active count remains 1. |

Original `free_cb` decrements the global counter via an actual `LDREX/STREX` sequence and passes the callback to `free_fblock`. In the test, `3→2` was verified for the inactive and self cases. Final allocator behavior was not executed; it is not claimed that a use-after-free physically occurred. However, a successful return by itself is clearly not universal proof that the callback is no longer running.

## Completion of Another Thread

After stopping at `schedule`, the test explicitly sets `count=0` as an **external completion fixture change**, not as proof of executing `finish_callback`. On a second stack, the original wake helper executes: it checks `count`, removes the corresponding waiter, clears its callback pointer, and calls `wake_up_process` for the waiting task.

Then the saved CPU context is restored immediately after `schedule`. The original wait/unregister code continues, returns 0, calls `free_cb`, and clears the slot. The final free comes only after the original wake path. The waiter's stack and local registers were not replaced by a host approximation.

The wake helper with `count=1` does not remove the waiter and does not call `wake_up_process`. That was verified separately.

## Interrupted Wait

With an explicit signal-pending fixture after `schedule`, the wait helper itself removes its stack waiter, clears the retire bit, and returns `-1021` (`0xfffffc03`). Unregister does not free the callback and does not clear the active registered slot. The native global allocation counter remains 3. The caller must retain resources and execute the retry contract; it must not treat that return as completed cleanup.

## Consequence for the Module

We must not consider OSAL callback registrations finished simply because unregister returned success from its own callback context. A future control path should perform final removal and freeing from a separate context, check active calls, and retain resources after an interrupted wait. This is the OSAL contract; it does not replace a separate check of gadgetcore/EP0 callbacks of E0164 nor by itself solve coordination of all USB changes.

## Results and Next Boundary

**26 checks pass**. Manifest: `artifacts/analysis/uvc-ptp-unregister-e0171/manifest.json`; log: `artifacts/uvc-ptp-unregister-e0171.log`. The probe also passed Python syntax checking.

The original kernel `wait_cb` acknowledgment and `finish_callback`, real locks, scheduling, and the final allocator have not yet been executed. Next, per-worker acknowledgment after the user callback should be connected with the original `finish_callback` and wake path. The E0164 module remains unloaded and `physical_test_ready:false`; production code was not modified, so 605 tests from E0164 remain the last full regression.
