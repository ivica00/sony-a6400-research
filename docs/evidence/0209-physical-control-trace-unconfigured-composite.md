# E0209 — Physical control trace: composite remains unconfigured

Date: 2026-11-09. User switched MSC → PC Remote → MSC. Camera filesystem writes: `/tmp_bt` only.

## Result

The 90-second session completed and cleanup succeeded automatically. Windows again bound `usbccgp` to the composite parent, with Code 10 and ProblemStatus 3221225473 (`0xc0000001`). No PTP MI_00 or UVC MI_01 children became ready.

The new camera-side telemetry observed `config=0` throughout the hold. Flags changed from 6 to 7 at second 2; mode remained 0, speed 1. Existing descriptor callbacks logged successful device/configuration/string responses, including the complete 173-byte configuration. Windows repeatedly requested device/configuration descriptors. No `[a6400_native_ioctl]` records appeared during the traced interval.

This narrows the investigation to enumeration/configuration selection. It does **not** establish why Windows rejected startup, or prove that SET_CONFIGURATION was never received: this diagnostic traces existing descriptor paths and periodically samples configuration, rather than tracing every setup request. Absence of native ioctl records is limited to this session and the installed entry path.

## Physical lifecycle

- PC Remote detected at 41 seconds.
- Publication: 181 attached/resumed, result 0, 1358 ms; four-core synchronization completed.
- INIT returned 0. Printed errno 22 is stale after a successful return and is not an INIT failure.
- STOP succeeded after 90 seconds.
- Retirement: 181 attached/resumed, result 0, 1207 ms; original opcode `0xe1a0c00d` restored.
- Runner complete/result 0; TracerPid 0; rmmod 0; original module list restored byte-for-byte; own temporary RAM files removed; debugger responsive.

Module: 71904 bytes, SHA-256 `39cba6a840896f09f7de99031b7f530d9184dd40d0e7e6042eb6c0ad60db882a`.
Runner: 15948 bytes, SHA-256 `5c55a0854f9d7bc08f6f99d9b77158e0cf0c91191304840e2e1500027e51156e`.

Evidence: `artifacts/hardware/uvc-ptp-control-trace-e0209/manifest.json`, `session.log`, `kernel-log-after-session.txt`, `composite-hub-descriptors.json`, `status-after.txt`, and `modules-after.txt`.

## Implementation and validation

Optional `--trace-control` build records bounded existing descriptor/native-entry calls without changing dispatch results. Read-only ioctl `0x8010f029` exposes flags/config/mode/speed from the validated live gadget context. Runner logs state changes. No additional kernel entry hook was introduced. Existing video START/submission remains disabled.

Compiled ARM module audit: 118 checks pass, including telemetry idle/live/invalid-context cases and native wrapper result preservation. Project suite: 612 tests pass in 18.036 seconds. Offline recorders are not physical hardware or concurrency proofs.

Host controller now verifies the runner has opened its device and reached the mode-wait marker before requesting the manual switch. It drops staging references before reconnect and reuses the first successful reconnect context; this physical cycle verified automatic cleanup, unlike E0208's double-open failure.

Source inspection also found that MOD control serialization and the actual native entry wrapper use separate guard objects. Existing tests must not be presented as proof of shared exclusion across both objects. No speculative gate behavior change was made; no native ioctl was observed during this session.

## Next

Validate the exact returned descriptors and original configuration-selection path, then add narrowly bounded setup-result visibility if needed. Do not force child drivers while the parent fails startup. Sensor feeder integration and simultaneous camera-control proof remain outstanding; the legacy feeder is still incompatible with the shared session ownership and DMA source rules described in E0208.
