# E0312 — blocking GPES wait deadlock, teardown-only writer, and the remaining GRM boundaries

Date: 2026-11-10. Offline cycle (Lead + four teammates). No camera/USB I/O, no
fabricated messages or host-called guest code. **No GUI frame, no full
breakthrough.**

## 1. Model corrections implemented and tested

* **`0xC004820D` now blocks** (decoded mode): the kernel
  `wait_for_completion_interruptible_timeout` semantics are modelled as
  `blocked_gles_wait`; the interpreter rewinds the ioctl and parks the caller.
  `0xC004820E` uses a per-tid ctx map (key 0 completes the caller; unknown
  nonzero key writes the `0x1FFFFFFF` failure sentinel and completes nothing);
  `ctx_by_key` registration remains a boundary.
* **`--nanosleep-policy block` threshold**: only sleeps >= 100 ms park
  (`nanosleep_no_virtual_deadline`); short polling sleeps (e.g. the RM
  executor's 1 ms retry) stay immediate with `reason='short_sleep_immediate'`,
  otherwise the emulator parks the thread that must make progress.
* **Runner robustness**: a `--load-checkpoint` path that does not exist now
  fails loudly. Two "continuation" experiments (e0359/e0365) had silently
  cold-booted because the checkpoint path was rewritten to a non-existent file;
  they are discarded as false starts.
* Full suite **877 tests OK** (18.1-18.8 s).

## 2. e0369: the GPES wait reaches a system-wide blocked state

Continuation from `boot-e0350-grm-decoded.ckpt` (488,299,004) with decoded
semantics + threshold sleep policy: status **`blocked_gles_wait`** at
488,300,643. TID1054 is parked in the hw-log completion wait
(`libObj+0x72BAF0`, LR `+0x72BB19`); TID1011 (RM executor) is `blocked_futex`;
TID1009/1010 blocked in libObj lazy-init cond waits; TID1007 parked
(`blocked_sleep`); main at `osal_wait_thread_exit`. No runnable thread remains,
so the hw-log completion cannot be produced by the modelled system.

Trace evidence (`arts/analysis/e0362-*`): with TID1054 parked, TID1011 reaches
the **normal** `0x72c250` return path (`0x72c58c` HIT, tid 1011) and runs
`0x72c590`; the RM count word `[0x553fa314]=0`, slot `libObj+0x13f0868=0`, and
no later 0x820E/0x820F occurs. The wait therefore depends on a boot-time
completion source that the modelled system does not have.

## 3. The identified writer is teardown-only

Task-41/44 corrected the earlier hope that `0x72BE20` (sets the
`libObj+0x13f0868` guard and issues `0x820E(0)`) is a boot step:

* `0x72BE20` is reached only through `0x7337E0` (RM teardown/exit), which
  requires `[global+4]==1` and pending fields cleared, then
  `0x733866 → 0x7318C0 → 0x72A650 → 0x72BE20`.
* The RM dispatcher slot at libObj file `0x13492E4` is a **load-time**
  `.data.rel.ro` method table (15 `R_ARM_RELATIVE` relocations, no runtime
  registrar); the dispatcher `0x72A5C4` (step 0..7, 6=request/7=finish) is
  invoked as a callback whose consumer/step writer is **not statically
  located** → boundary `rm_dispatcher_consumer_unidentified`.
* Retained runs keep RM alive (no `[global+4]` teardown signature) →
  `rm_hw_log_start_not_reached`.

So the remaining boot-time completion must be either a genuine GPES
hardware/IRQ completion (kernel `sugilite_interrupt` / fast ctx flag) or an
unobserved peer signal; a fabricating model (host-writing the guard, calling
`0x72BE20`/dispatcher, or synthesising a signal) is not allowed.

## 4. Boundaries (current)

| boundary | meaning |
| --- | --- |
| `gles_kick_completion_unmodelled` | boot-time GPES engine/IRQ completion is not modelled; no runnable producer remains |
| `gles_wait_signal_keymap_unmodelled` | nonzero signal-key registration/matching not decoded (ctx_by_key) |
| `rm_dispatcher_consumer_unidentified` | RM method-table consumer / step writer not located |
| `rm_hw_log_start_not_reached` | hw-log start writer is teardown-only and unreached in replay |
| `libobj_slot_0x13f0868_writer` | resolved as teardown-only writer; boot path absent |
| `usb_vbus_changed_mwf_0x0a4000_producer_not_derivable` | USB VBUS relay producer absent from image (E0311) |
| `mwf_monitor_input_poll` | monitor input producer absent; sleep policy parks it |

## 5. Next in flight

* task-45: decode the legitimate boot-time completion source of the GPES wait
  (kernel IRQ/ctx fast flag vs user signal) — decides model vs boundary.
* task-43: the `0x7338xx` gate/`0x733890` creation-caller chain — whether any
  boot path joins the dispatcher/teardown chain.
* task-42: traces at `0x72c4d0/0x72c58c/0x72e510/0x72be20` to classify the
  `0x72c250` ret-1 condition and RM work/queue state.
* task-40: analysis of e0369 with the blocking-wait model.

No UVC/PTP function, no camera access, no GUI frame; tests 877 OK.
