# E0335 — Local-queue SETCONFIG post reaches the USB FSM: event 0x13 observed

Date: 2026-11-11. Emulator-only, opt-in; no camera access, no camera write, no
USB mode change, no GitHub push.

## 1. Result

The first **SETCONFIG → FSM event 0x13** dispatch is observed in the emulator:

- E0332/E0334 established that `0x00CA8192` is a process-local OSAL queue and
  that the inbound ObjMsg must be delivered through the libosal local-queue
  object, not the kernel UIPC queue and not the adjustment callback lane.
- A pure planner (`src/a6400/execution/local_queue_post.py`, 45 tests) decodes
  the original `osal_snd_msg`/dispatch path (0x3C34 / 0x3848 / 0x32B0 / 0x5100):
  priority-ordered head insertion, `head = payload - 0xC`, one-shot WAIT_CB record
  dispatch (out-slot write, futex word = 1, `FUTEX_WAKE_PRIVATE`).
- Real-checkpoint validation (e0673): queue object **0x504305E0** (lock 0,
  flags 0, head 0, stale tail 0x50430720), one WAIT_CB record **0x10FFED28**
  (flags 0x04, dispatcher 0x500332B1), out-slot 0x10FFED74, futex word
  **0x10FFED3C** (matches E0310's decoded wakeup; note these addresses differ
  from the older 308.6M checkpoint and must be read dynamically).

## 2. e0686 experiment

Opt-in CLI: `--uipc-local-post-setconfig-object 0x504305E0
--uipc-local-post-waiter 0x10FFED28 --trace-usbcontrol-dispatch`.
The probe builds the labelled ObjMsg image + envelope in the UIPC pool, applies
the planner's ordered writes, then performs the single futex wake
(`futex_woken=1`).

Observed dispatch trace on TID 1018 (UsbControl), all at ~557,155,2xx:

| Function | Args/returns |
| --- | --- |
| `UsbControl::ProcessMsg` | msg=0x503B3C4C; ObjMsg category **0x6103**, messageId **0x0A4001** |
| `MWF::ObjMsg::GetMessageId` | returns **0x0A4001** |
| `UsbControl::MsgId2EventId` | message 0x0A4001 → **event_id 0x13 (19)** |
| `UFW::Fsm::DispatchEvent` | this=0x2E2A4, **event_id 0x13 (19)**, msg=0x503B3C4C |

Run stopped at `syscall_boundary` 557,668,206 with the next fail-closed
assertion:

```
im.elf: ufw/MsgUtil/MsgUtil.cpp:64:
static int32_t UFW::MsgUtil::GetInt32(MWF::ObjMsg*, uint32_t):
Assertion `0' failed
```

## 3. Interpretation

The transport, queue semantics and dispatch chain now work end to end in the
emulator: the original code consumes the evidence-derived ObjMsg, maps
`MessageId 0x0A4001` to **FSM event 0x13**, and calls the FSM dispatcher. The
event handler then reads the SETCONFIG parameter via
`UFW::MsgUtil::GetInt32(msg, param_id)` and asserts because our ObjMsg body's
**ParamMap is zeroed** (E0325 boundary): the required `Param 0x1006 = int32 0`
object is absent.

New boundary: **`mwf_param_object_unmodelled`** — a valid ParamMap entry/Param
object for `0x1006` (int32, value 0) is required before the event handler can
proceed. This is a fail-closed stop, not a mode transition: no UVC/PTP function
or FSM transition beyond event 0x13 is claimed.

## 4. Next

1. Construct the ObjMsg body ParamMap with the evidence-derived Param for
   `0x1006` (int32 value 0): `ParamMap node {+0 id, +4 param*}`,
   `ParamStd<int, Type=7> {+0 value, +4 vtable}` (E0325/E0326). The vtable must
   be a real libMWF Param vtable resolved from the resumed module, or the
   handler's type check must be decoded first.
2. Re-run e0686 with the parameter present; observe whether event 0x13's action
   completes and which observable (FSM state/mode/otgcore config) follows.
3. Keep the opt-in default off; addresses for the local queue object/waiter are
   evidence-supplied per checkpoint, never hardcoded.

## 5. Reproduce

- Runner: `artifacts/analysis/e0686-run-live-localpost.py`
- Report: `artifacts/execution/e0686-live-localpost.json`
- Checkpoint: `artifacts/checkpoints/boot-e0686-live-localpost.ckpt`
- Code: `src/a6400/execution/local_queue_post.py`,
  `InterpreterProbe.inject_local_queue_objmsg`,
  `--uipc-local-post-setconfig-object/--uipc-local-post-waiter`,
  `--trace-usbcontrol-dispatch`.
- Full suite at this point: **1053 tests OK**.
