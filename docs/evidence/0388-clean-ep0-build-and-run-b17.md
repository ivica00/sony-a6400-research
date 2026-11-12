# E0388 — `e0388-clean-ep0` build and Run B17: hot-path hooks removed, probe/descriptor aligned, MSC teardown without battery pull; ffmpeg still fails RenderStream

Date: 2026-11-12. Build + one bounded physical run. RAM-only; no flash/SD writes.

## 1. Guardrails implemented

- **Trace off by default:** `#ifndef A6400_UVC_TRACE / #define A6400_UVC_TRACE 0`;
  all CLASS/queue/complete `printk`, `GCRO`, `log_events`, `log_trb`, `tstamp`,
  class-LR and snapshot instrumentation is compiled out.
- **No EP0 ops shadow / queue wrapper / completion thunk in the default build.**
  The build has no `a6400_uvc_ep0_queue_wrap`/`a6400_uvc_ep0_complete_thunk`
  symbols. Bounce-path verification: `dwc3_ep0_do_control_data` arms
  `dwc->ep0_bounce` (`[dwc+0x18]`, ctrl `0x50`) for short OUT at
  `0x602b2688..0x602b2694`; `dwc3_ep0_complete_data` copies bounce→`req->buf` at
  `0x602b3208..0x602b3234` (`memcpy(r0=[req], r1=bounce, r2=remaining)`). For
  `len=26 < 64` the queue does not need `req->dma`, so the ops shadow/queue wrapper
  is unnecessary and was removed from the production path.
- **Probe/descriptor coherent:** 26-byte template now
  `dwMaxVideoFrameSize=0x001c2000=1,843,200`, `dwMaxPayloadTransferSize=0x0001fff4=131,060`
  (module native `max_payload`), interval 333333; VS frame descriptor
  `dwMaxVideoFrameBufferSize=0x001c2000`.
- **Teardown:** module unload calls `a6400_uvc_restore_descriptors` (pullup0,
  setup_disconnect, gcw_stop, driver demote, config-desc unhook); Run B17 stopped the
  daemon and `rmmod` before the MSC switch, not on a transient alt0.

## 2. Build/verification

- Module: **eda3f8d6c5eba0a008086b4040206f3b2cb7f618f90c0db7e412915724d4c11e**,
  76,760 B, static audit **117/8/0 passed** (`offline_module_audit_passed`).
- Unicorn: `a6400_uvc_ptp_translate_setup` exact-object test PASS — input
  `21 01 00 01 02 00 00 00` leaves the wire buffer unchanged and produces native
  wIndex `01`; no `ctrl_req` overwrite.
- Full suite **1312 tests OK**.

## 3. Run B17-clean-ep0

- Daemon 99047575 with the clean module, one ffmpeg attempt
  (`-f dshow -i video="ILCE-6400" -frames:v 60`): still
  `Could not RenderStream to connect pins`; no frame file.
- Camera-side log from this boot: `reference START entry iface=2` at **117.551** and
  `reference STOP` at **207.350**; no CLASS/GCRO lines (trace off, as intended).
  So the UVC streaming interface did start/stop, but DirectShow still fails before
  delivering frames.
- **Teardown succeeded without a battery pull:** daemon stopped, `rmmod` returned 0,
  module list back to 42, no `usbg_video`; camera switched to MSC 054C:0CAA.
  Receipt: `status=clean`, `stop_verified=1`, `teardown_verified=1`.
- Host ETL 6,250,496 B retained for control-URB timing decode
  (`artifacts/analysis/e0388-runb17cleanep0/usb-capture.etl`); the clean build emits
  no EP0 timing logs, so the GET/SET duration must come from the ETL.

## 4. Verdict / next

- The critical instrumentation delay is gone, and MSC teardown is fixed (no battery
  pull). The remaining `RenderStream` failure is **not** the EP0 hot-path printk issue;
  it is descriptor/endpoint/probe or the Bulk UVC endpoint's host acceptance.
- Next: decode the B17 ETL UCX control-URB durations to check whether GET_CUR/SET_CUR
  now complete in ms; then inspect VS endpoint (Bulk 0x84/512) and the probe payload
  against what usbvideo.sys accepts. No further code change is claimed.
