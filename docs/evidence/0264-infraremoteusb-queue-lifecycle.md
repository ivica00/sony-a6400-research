# E0264 — InfraRemoteUsb queue lifecycle: sync registration, PTP member, destructor drain

Date: 2026-11-09. Offline only.

## Constructor (recap, E0263)

- `osal_reg_sync_msg_queue_cb([this+0x18], &this+0xc, this)` — the sync queue callback uses the object as context.
- `PTPT_register_callback([this+0x1c])` — the PTP/liveview member is a **different** member from the sync queue.

## Destructor (`InfraRemoteUsbD1Ev`, 0x9f18)

- `osal_unreg_msg_queue_cb([this+0x1c], [this+0x10])` — the PTP member is unregistered as a message queue with context `[this+0x10]`.
- `osal_dynamic_id(0x49, 0, [this+0x1c])` — dynamic-ID cleanup.
- A drain loop calls `osal_rcv_msg_tmo([queue], &msg, 0)` and frees each message, so `osal_rcv_msg_tmo` at `0x9f6c` is the **destructor drain**, not the live consumer.
- It then calls `PTPT_unregister_callback`, confirming the PTP registration lifetime matches the object.

## Other registrations

- `InfraRemoteUsb::setTimer` (around 0xa13c) calls `osal_reg_msg_queue_cb(queue, ..., callback)` with a callback literal; the nearby `OsalTimerCb` (0x9eea) builds an `MWF::ObjMsg` and sends it to itself. This is the timer path, not the PTP liveview consumer.
- The PTP queue callback itself is not a thread loop in the constructor: it is most likely delivered through the same OSAL queue-callback machinery, with the callback context `[this+0x10]`.

## Interpretation

`InfraRemoteUsb` owns a sync queue (`[this+0x18]`) and a PTP queue/context (`[this+0x1c]`) whose callback is registered with context `[this+0x10]`. The liveview message posted by `libInfraPtpControl` lands in that queue; the app's handling depends on the callback registered for it and the object's state. The remaining question is which callback/state serves `LiveView` under the composite configuration.

## Next

- Locate the registration that pairs `[this+0x1c]` with `[this+0x10]` and the callback body (search `osal_reg_sync_msg_queue_cb`/`osal_reg_msg_queue_cb` contexts, or the `[this+0x10]` initialization).
- Follow the `LiveView`/`GetObject` handling in `libInfraRemote`/`libInfraPtpExtCmd` and the state that gates it.
