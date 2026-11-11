# E0331 — USB lane channel correction: local queue vs kernel sync-callback queues

Date: 2026-11-11. Live-checkpoint inspection + two labelled emulator experiments.
No camera access, no camera write, no USB mode change.

## 1. Correction: 0x00CA8192 is a **process-local** OSAL queue

`libosal_uipc` dispatches by id bit 15: ids with bit 15 set (e.g.
**0x00CA8192**, `0x8192 & 0x8000 = 0x8000`) are serviced by the **user-space
queue object** path (E0329/E0330); kernel does not write to them. Messages on
that queue are produced by in-process senders only (e.g. E0311's
`MsgSender::SendEvt` target after a `/dev/usb/event` record).

Consequence: the E0328 approach — injecting a kernel-style message directly
into 0x00CA8192 through the emulated UIPC device — cannot be consumed by the
original `RcvMsg`, because the original code never reaches a kernel receive for
that id. This explains the E0328 assertion without any additional bug.

## 2. Registered kernel-sync callback queues in the live state

In `boot-e0673-live-full2e.ckpt` the UIPC callback table contains the
kernel-sync registrations:

| handle | queue | callback | user_data | flags |
| --- | --- | --- | --- | --- |
| 4109 | **0x00CA0288** (13238920) | 1447342303 | 1447422616 | **1** |
| 4110 | **0x00CA01A4** (13238692) | 1447373447 | 188848 | **1** |

`flags=1` marks sync registrations: per E0303 they are **never consumed by the
async `WAIT_CB` path**, so the async proxy threads (1001–1004) do not deliver
them. The kernel→user notification for these queues must use the sync wrapper
(`osal_snd_sync_msg` / `snd_sync_direct`, sync queue 0x009C015B family) or an
equivalent same-process callback invocation.

## 3. Labelled experiments this round

- **e0681** (queue 0x00CA8192 + manual futex wake): `RcvMsg` assertion,
  `syscall_boundary` 557,668,465 (E0328).
- **e0682** (queue 0x00CA0288, no wake): envelope queued
  (`queue pending [1346059500]`), `woken=[]`; the four UIPC proxies stayed
  `blocked_uipc` on wait index -1; UsbControl still `blocked_futex`; run to
  628,993,333 with `boundary = null`. The sync registration is not consumed by
  the async path, exactly as the flags indicate.

No FSM event 0x13 / mode transition is claimed.

## 4. Boundary and next step

Boundary: **`uipc_sync_callback_delivery_unmodelled`** — the emulator lacks the
kernel→user sync callback delivery path for flags=1 registrations.

Next:
1. Decode `GuestUipc.handle_wait_cb`/`handle_snd_sync_msg` and
   `libosal_uipc` sync wrappers (0x3B?? / `snd_sync_direct`) to learn how a
   flags=1 registration is invoked (message content ABI, callback arguments,
   completion/ownership).
2. Model it as an opt-in contract: kernel-side send to 0x00CA0288 →
   synchronous callback invocation with the decoded packet.
3. Re-deliver the SETCONFIG ObjMsg through that path and observe
   `ProcessMsg → DispatchEvent → event 0x13`.

Bounds unchanged: no camera write/module load/USB mode change; suite unchanged
at **952 tests OK**. Runs retained: `e0682-live-synccb.json`,
`boot-e0682-live-synccb.ckpt`.
