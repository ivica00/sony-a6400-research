# E0262 — libInfraRemote imports the generic PTP callback registration

Date: 2026-11-09. Offline only (no camera access in this step).

## Static findings

- `libInfraRemote.so` has `PTPT_register_callback` and `LiveView` in `.dynstr`; it **imports** the generic `PTPT_register_callback` (undefined dynsym). It does **not** import `PTPT_register_callback_usb`, and it has no `dlsym`/`dlopen`.
- `libInfraPtpControl.so` defines both the generic `PTPT_register_callback` and the USB variant; `PTPT_fin` dispatches by a transport state (`1`/`3` → `PTPT_fin_usb`, `2` → `PTPT_fin_ip`), so the transport is selected at runtime.
- `PTPT_open_usb` stores context fields and, after registration bookkeeping, invokes a callback pointer held in its context (`ldr r3,[r4,#0x34]; blx r3`) with a status argument. No queue creation appears in the visible `open_usb` tail; the USB-specific registration is internal.

## Interpretation

The application-side remote stack (`libInfraRemote`) registers a **generic** PTP callback; the USB-specific registration and the liveview queue are set inside `libInfraPtpControl` when the PC Remote transport is opened. The liveview consumer therefore belongs to the remote/PC Remote stack registered through that generic callback, not to a separate statically imported symbol. This is consistent with the queue global being 0 in Mass Storage: the transport is not opened there.

## Next

Disassemble the `libInfraRemote` call to `PTPT_register_callback` (PLT) and the callback body it registers, then follow the remote stack's queue receive path (`osal_rcv_msg_tmo`) to the `LiveView` handling. That should identify the app-side consumer and what mode/condition keeps it from serving the queued liveview request under the composite configuration.
