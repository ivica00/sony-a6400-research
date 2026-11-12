# E0359 — Run B4: translated GET_CUR still timed out (probable no-transfer branch); CLEAN teardown, no battery pull; ep0 probe bug fixed

Date: 2026-11-11. **Physical, user-authorized Run B4.** Module `b21325d9…` (E0358),
daemon `99047575…` (`--sd-log --sd-mount --dmesg-sd`). One ffmpeg RenderStream attempt.
**The camera returned to native 054C:0CAA and Mass Storage without a battery pull**, and
the teardown was **clean** (`stop_verified=1, stop_attempts=1, teardown_verified=1`;
recovery path not needed).

## Run record

- Fresh boot (uptime 45 s at push), module `b21325d9…` and daemon `99047575…`
  readback-verified; daemon armed 150 s / 900 s wait; INIT, DMA (`phys=0x09840000`,
  262,144 B), REG_BUF/ENABLE rc 0; composite enumerated (`Camera ILCE-6400`,
  `WPD: MTP USB Device`, `USB Composite Device`, all OK); WPD snapshot again
  **0 VID-054C devices**; host ETW armed with USBPORT/USBHUB3/USBXHCI/**UCX**
  (464,306,176 B kept).
- One `ffmpeg -f dshow -i video="ILCE-6400"` attempt failed
  `Could not RenderStream to connect pins` after **10.2 s** (out-log 19:47:02.203,
  err-log 19:47:12.401).
- Daemon receipt: **`status=clean`, `exit_code=0`, `stop_verified=1`,
  `stop_attempts=1`, `teardown_verified=1`, `hook_retired=1`, 181-TID attest ok,
  `recovery.attempted=0`**, `get_jpeg_polls=4499` all empty, SD `trace_lines=137/0`.
- Host: native `054C:0CAA` returned; operator switched to Mass Storage normally —
  **no battery pull**. `[a6400_td] done phases=1ff failed=9 error=0 … reconnect=1`.

## Decisive kernel sequence (this boot; A6400K.LOG)

```
[129.323618] [a6400_sel] match wrapper=6897e560 raw=68a1c1c0 ep=0x84 flags=00000001 count=1
[129.690698] [a6400_uvc] reference START entry iface=2 count=1 / returned iface=2 count=1
[141.742183] [a6400_uvc] CLASS translated wire_iface=2 idx=0002 -> native idx=0001
[141.742337] [a6400_uvc] CLASS entry rt=a1 req=81 val=0100 idx=0002 len=001a
[141.742455] [a6400_uvc] CLASS ep0-pre  ep0=68a1c9c0 no-udc-ep
[141.742598] [a6400_uvc] CLASS ep0-post ep0=68a1c9c0 no-udc-ep
[141.742695] [a6400_uvc] CLASS exit result=0
[146.744334] [a6400_uvc] CLASS translated wire_iface=2 idx=0002 -> native idx=0001
[146.744486] [a6400_uvc] CLASS entry rt=21 req=01 val=0100 idx=0002 len=001a   (SET_CUR PROBE)
[146.744661] [a6400_uvc] CLASS ep0-pre  ep0=68a1c9c0 no-udc-ep
[146.744788] [a6400_uvc] CLASS ep0-post ep0=68a1c9c0 no-udc-ep
[146.744914] [a6400_uvc] CLASS exit result=0
[279.471767] [a6400_uvc] reference STOP entry iface=2 count=1 / returned
[279.473541] [a6400_td] done phases=1ff failed=9 error=0 ep=1 list=00000000 id=0 count=1 desc=1 root=68a844a0 retired=1 shadow=0 reconnect=1
```

Mapping anchor: boot wall ≈ 19:44:40.7 (hub stop/removal at 19:49:20.113 ↔ kernel
279.45). Therefore GET_CUR ≈ 19:47:02.4 (ffmpeg dshow open), SET_CUR(PROBE) ≈ 19:47:07.4
**exactly +5.002 s**, ffmpeg error at 19:47:12.4 — i.e. **+5.0 s after the SET_CUR**. The
only consistent reading is **two consecutive 5 s EP0 timeouts**: GET_CUR reply not
delivered; usbvideo then emitted SET_CUR(PROBE); its status also not delivered; the
second timeout aborted RenderStream. No COMMIT and no SET_INTERFACE followed.

## Case classification (A/B/C)

- **Not Case A:** a delivered GET_CUR reply would have been followed by SET_CUR within
  milliseconds, not 5.002 s, and then by COMMIT.
- **Not Case C (provable):** the `ep0-pre/post` snapshots contain only
  `no-udc-ep`, so no `next`/`eps1 BUSY` state was captured.
- **Most probable Case B** (no transfer armed) for both transfers: 5 s + 5 s timeout
  pattern, class results 0, no COMMIT. The snapshot could not confirm it because of the
  probe bug below.

## Probe bug found and fixed offline

`a6400_uvc_kernel_ptr()` accepted only `0x60000000..0x61000000`, but the live camera's
objects are at `0x68xxxxxx` (`ep0=68a1c9c0`), so every snapshot logged `no-udc-ep`.
Fixed to accept `0x60000000..0x70000000` (read-only diagnostic; no pointer
substitution). Rebuilt module:
`artifacts/native/uvc-transport-e0359-ep0fix/usbg_video_a6400_shared_candidate.ko`,
**79,000 B**, SHA-256 `53f655a613ac520f6f87dd13a671f3195cefafb431896dfa046aaef534484113`,
transport audit `offline_module_audit_passed` (**117/8/0**). This module is the candidate
for Run B5; it should finally print the UDC `state/next/event/dep_flags`, `eps0/eps1`
and queued-request fields for both GET_CUR and SET_CUR.

## What Run B4 already settled

- The bridge **CLASS translation is live** (`wire_iface=2 -> native idx=0001` logged for
  both GET_CUR and SET_CUR) and the host now proceeds from GET_CUR to SET_CUR(PROBE)
  (Run B3 never reached SET_CUR).
- **The battery-pull requirement is gone**: STOP verified clean and Mass Storage returned
  without recovery or a physical pull. The E0358 park-recovery path remains untested
  physically (it was not needed).
- RenderStream still fails at the EP0 data/status phase; with the probe fixed, Run B5
  must show the exact `dwc+0x2d8/0x2dc/0x2e0` + `dep_flags` for the no-transfer branch
  and/or `next/BUSY` + DMA for the armed case.

## Next (Run B5, on go-ahead)

Fresh boot → module `53f655a6…` + daemon `99047575…` (`--dmesg-sd --sd-log --sd-mount`);
WPD snapshot; one ffmpeg; read A6400K.LOG. Expected useful lines:
`CLASS ep0-pre/post ep0=… desc=… dep_flags=… ops=… queue=602b2ad0` and
`dwc=… state=… next=… event=… eps0=…/… eps1=…/…` plus queued-request details.
Decision: if `next != 1` and `eps1` bit 0x10 clear → identify the exact silent branch
from `state/event/dep_flags` and fix it offline + Unicorn; if `next == 1` and BUSY →
inspect `req->dma`/length/completion for the armed-but-not-completed case. If teardown
fails again, the daemon's degraded path writes `degraded_teardown`, retries STOP once and
returns to 0CAA without a battery pull.

## Verification

Full suite **1312 tests OK** (Lead final, `artifacts/analysis/e0359-runb4/suite.log`);
module audit 117/8/0; receipts/ETL retained under `artifacts/analysis/e0359-runb4/`.
Camera ended healthy in Mass Storage (no battery pull); no host flash/SD writes
(read-only SD mount only); no GitHub push.
