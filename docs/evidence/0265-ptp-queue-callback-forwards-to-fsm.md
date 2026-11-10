# E0265 — The PTP queue callback is OsalSyncRcvMsgCbUsb, which forwards to the async FSM

Date: 2026-11-09. Offline only.

## Resolution

The `osal_reg_sync_msg_queue_cb` call at `libInfraRemote` `0x9d74` registers queue `[this+0x1c]` (the member also passed to `PTPT_register_callback`) with context `&this+0x10`, the object, and a callback loaded from a GOT slot (`0x19924` at `r5=0x1945c`). The `.rel.dyn` entry for that slot resolves to:

`_ZN14InfraRemoteUsb19OsalSyncRcvMsgCbUsbEPvS0_` — `InfraRemoteUsb::OsalSyncRcvMsgCbUsb`.

## Behavior

`OsalSyncRcvMsgCbUsb` (0xaa60) builds an `MWF::ObjMsg` (`MWF::ObjMsg::ObjMsg(uint,uint)` at 0x9320) and tail-calls `InfraRemoteUsb::SndASyncMsgToMe(msg, ...)` (0x8c74). It does not process the liveview request inline; it re-posts it into the object's **asynchronous message stream / FSM dispatcher**.

## Interpretation

The liveview request path in the app is:

`libInfraPtpControl` handler (0x369c) → OSAL queue `[this+0x1c]` → `OsalSyncRcvMsgCbUsb` → `MWF::ObjMsg` → `SndASyncMsgToMe` → UFW FSM/async dispatcher.

The gating therefore sits in the **FSM state/message handler**, not in the queue callback. Under the composite configuration the async message may be dropped or handled in a state that does not produce a liveview frame.

## Next

Disassemble `SndASyncMsgToMe` and the UFW FSM event dispatcher in `InfraRemoteUsb`, find the handler for the forwarded message type and the state conditions around `LiveView`, then compare that condition with the composite-session state.
