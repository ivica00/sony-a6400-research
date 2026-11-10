# E0263 — InfraRemoteUsb registers its context/queue with the PTP control library

Date: 2026-11-09. Offline only.

## Call chain

- `libInfraRemote` has a single `PTPT_register_callback@plt` call site at `0x9da6`, inside the `InfraRemoteUsb` constructor (`_ZN14InfraRemoteUsbC1Ev`). It passes `r0 = [this+0x1c]` (member at offset 28) as the only argument.
- `PTPT_register_callback` (libInfraPtpControl, `0x2d2c`) is a thin wrapper: `push; add r7,sp; ldmia; b.w PTPT_register_callback_usb@plt`. The generic registration therefore forwards the same argument to the USB variant, which stores it at the library global `0xf450`; the liveview handler (`0x369c`) uses that value as the queue for its 8-byte message.
- In the same constructor, at `0x9d2a`, `[this+0x18]` is registered with `osal_reg_sync_msg_queue_cb([this+0x18], &this+0xc, this)` — a separate sync queue whose callback context is the object.

## Interpretation

`InfraRemoteUsb` owns at least two queue/context members: `[this+0x18]` (sync queue callback registered with the object) and `[this+0x1c]` (registered with PTP control and used for liveview messages). The PTP response/liveview consumer is therefore in the remote stack's queue/FSM threads; `libInfraRemote` has `osal_rcv_msg_tmo` call sites at `0x9f6c`, `0xa082` and `0xa0c8` in the UFW FSM/dispatcher area.

## Next

Disassemble the receive loops at `0x9f6c`/`0xa082`/`0xa0c8` and the message dispatcher, and identify where the 8-byte PTP/liveview message is handled (`LiveView`/`GetObject` path). That should show which app state or condition prevents frame production under the composite configuration.
