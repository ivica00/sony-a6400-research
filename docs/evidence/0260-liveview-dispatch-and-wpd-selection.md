# E0260 — Offline REA: the liveview request is posted to an OSAL queue; WPD device selection added

Date: 2026-11-09. Offline only: no camera, no PC Remote, no module.

## Liveview dispatch in the original library

`libInfraPtpControl.so` (a6400 extraction) contains exactly one instance of the little-endian handle `0xFFFFC002`. At `.text` vaddr `0x377c` it is a literal used by the PTP command handler:

1. Read the PTP operation code at request+6; require `0x1009` (`GetObject`).
2. Read the object handle at request+12; compare with `0xFFFFC002`.
3. On a match: store `{request, ...}` in a global, set a flag, and branch to `0x369c`.
4. `0x369c` allocates an 8-byte message (`osal_valloc_msg_wait`), copies 8 bytes, and posts it with `osal_snd_msg` to a queue; returns 0 on success, `-1` on failure.
5. Any other handle falls through to a generic callback (`blx` of a registered function).

There is **no video-state/interface check** in this library for the liveview handle: the host command is accepted and forwarded as a message to the application's queue. The frame production/gating must therefore be on the **consumer side** (the app service that owns that OSAL queue).

## WPD device selection (offline)

- `ptp_liveview_client.connect(device_index=0)` now validates and selects a specific Sony WPD device and records the device count/handle.
- `run_ptp_liveview_probe.py` adds `--list-devices` and `--device-index`, plus the pure `select_device_index()` policy with tests (`tests/test_ptp_probe_selection.py`, 2 cases).
- This addresses the "multiple WPD nodes" hypothesis without another session: a future probe can enumerate and select each node explicitly.

## Leading hypothesis

The composite configuration (device class `0xEF/2/1`, three interfaces, IAD, UVC present — E0258) may prevent the camera app from entering the state in which its liveview consumer serves the queued `GetObject` request. The host handshake and the PTP library dispatch are working (control without the module delivers frames; the library accepts the handle), so the remaining gate is app-side mode detection/consumer state, not the probe, the PTP interface descriptors or the handshake.

## Next (not executed)

- REA the app-side owner of the queue used by `0x369c` and its PC Remote/liveview mode detection (what conditions register/consume that queue).
- Options for a future module/experiment: preserve the PC Remote device identity (class 0/single-function) while adding UVC via a second configuration, or trigger the app's PC Remote/liveview state explicitly.
- No PC Remote or module sessions until that analysis is complete; the camera stays in MSC.
