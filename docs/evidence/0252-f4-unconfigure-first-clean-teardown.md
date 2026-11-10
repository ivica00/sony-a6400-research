# E0252 — F4: unconfigure-first session enumerates both children and returns to MSC cleanly

Date: 2026-11-09. Physical session with the opt-in e0251 candidate. No streaming, no sensor frames, no SD write.

## Setup

- Module `artifacts/native/uvc-ptp-module-e0251/usbg_video_a6400_shared_candidate.ko`, SHA-256 `383ea3b880063461dc0bc92d0a1235f253b457562da3bb6711085746f65aae28` (72,712 B), built with `A6400_UVC_TEARDOWN_UNCONFIGURE_FIRST`; **118/118 offline audit passed**.
- Runner `uvc-ptp-runner-p4`, SHA-256 `a7c1b4ea397797044877976120b626a82f38cf7d0f6307f615c1b13d2c4af47e`, 16,048 B.
- Strict `--p4` policy: duration 60 s, MSC wait 120 s, no rmmod without a verified receipt.

## Session

- Preflight `ok=True`; `insmod`, `mknod`, runner launch all status 0.
- PC Remote detected at 36 s; runner settled 2 s, published the entry hook, `IOCTL_UVC_INIT` returned 0.
- Host saw the composite parent at ~36 s and **both children at ~40 s**: `MI_00` MTP USB Device and `MI_01` ILCE-6400 Camera, both Status OK. (`children_ready_simultaneously` remains false only because property reads return Access denied.)
- `USB_STATE` transitioned config 0 → 1; the session held 60 s.
- Teardown at ~103 s: children disappeared, the parent remained briefly as WPD, then the camera returned to Mass Storage.

## Teardown receipt

- `STEP 3: Composite session stopped; IDLE/unpinned/no hooks/no error verified.`
- `STEP 4: Entry hook retired, 0xe1a0c00d restored, 4-core sync complete, threads resumed.`
- `SESSION_RUNNER complete result=0`.
- Policy: `p4_receipt.ok=true` (init, stop_verified, retired, completed); `rmmod` succeeded; owned `/tmp_bt` files removed.
- Postflight: MSC, uptime 922.14 s (staging ~729 s, monotonic → **no reboot**), 42 modules, `usbg_video` absent, `TracerPid: 0`; `p4_after.ok=true` with module list restored.

## Interpretation

This is the first recorded clean teardown of a configured composite session: both PTP and UVC children enumerated and the camera returned to Mass Storage without a restart. The e0251 end-path order (original clear-configuration before native pullup) is the only teardown difference from the failed P4b session (E0248), so the unconfigure-first order is the leading explanation; a single session does not isolate the native stage, and the module's trace-control dmesg was not retained.

## Limits

One session; no PTP transaction, UVC streaming or sensor frame; no SD journal write. The host monitor's child-ready flag still depends on denied WMI properties, so the raw PnP presence is the observation. The exact native effect of unconfigure (interface-stop completion, DWC busy-bit clear) is inferred from the receipt/return, not directly instrumented.

## Next

With teardown demonstrated, the next bounded steps are: (1) a PTP transaction inside the session, (2) enabling video START/one-shot frame with the existing admission/parser contracts, (3) repeated teardown trials to check stability.
