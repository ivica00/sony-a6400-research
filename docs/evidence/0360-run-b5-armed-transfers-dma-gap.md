# E0360 — Run B5: BOTH EP0 transfers armed (`next=1`, BUSY); GET armed with valid DMA but no completion; SET armed with **dma=0**; clean teardown again

Date: 2026-11-11. **Physical, user-authorized Run B5.** Module `53f655a6…` (fixed ep0
pointer guard), daemon `99047575…` (`--dmesg-sd --sd-log --sd-mount`). One ffmpeg
attempt. **Clean teardown, native 054C:0CAA and Mass Storage returned without a battery
pull.** This is the first run with the live UDC state captured for both transfers.

## Run record (this boot, A6400K.LOG)

```
[224.164892] CLASS translated wire_iface=2 idx=0002 -> native idx=0001
[224.165047] CLASS entry rt=a1 req=81 val=0100 idx=0002 len=001a            (GET_CUR PROBE)
[224.165172] CLASS ep0-pre  ep0=68a1c9c0 desc=604e4e24 dep_flags=00000001 ops=603dfb4c queue=602b2ad0
[224.165353] CLASS ep0-pre  dwc=689e5810 drv=00000003 ctrl=6051b4b4 dev=604db590 state=8d next=00000002 event=00000001 eps0=68a1c9c0/00000001 eps1=68a1c3c0/00000001
[224.165668] CLASS ep0-post ep0=68a1c9c0 desc=604e4e24 dep_flags=00000001 ops=603dfb4c queue=602b2ad0
[224.165863] CLASS ep0-post dwc=689e5810 drv=00000003 … state=8d next=00000001 event=00000002 eps0=…/00000001 eps1=…/00000011
[224.166120] CLASS ep0-post pending req=68a84620 buf=68944d7c len=0000001a dma=08944d7c complete=5f564a74 context=00000000 status=ffffff8d
[224.166353] CLASS exit result=0
[229.170058] CLASS translated wire_iface=2 idx=0002 -> native idx=0001
[229.170212] CLASS entry rt=21 req=01 val=0100 idx=0002 len=001a            (SET_CUR PROBE, +5.002 s)
[229.170337] CLASS ep0-pre  ep0=68a1c9c0 … state=89 next=00000002 event=00000001 eps0=…/00000001 eps1=…/00000001
[229.170825] CLASS ep0-post ep0=68a1c9c0 … dep_flags=00000011 state=8b next=00000001 event=00000002 eps0=…/00000011 eps1=…/00000001
[229.171262] CLASS ep0-post pending req=68a84620 buf=68944d7c len=0000001a dma=00000000 complete=5f564a74 context=00000000 status=ffffff8d
[229.171472] CLASS exit result=0
[360.137537] [a6400_td] done phases=1ff failed=9 error=0 ep=1 list=00000000 id=0 count=1 desc=1 root=609d0ba0 retired=1 shadow=0 reconnect=1
```

Host timing: ffmpeg out-log 19:59:42.135, error 19:59:52.327 (10.19 s); GET ≈ start,
SET ≈ +5.002 s, failure ≈ +5.0 s after SET → two 5 s EP0 timeouts, same cadence as
B4 but now with state. Receipt `status=clean`, `stop_verified=1`, `stop_attempts=1`,
`teardown_verified=1`, `recovery.attempted=0`; ETL 454,418,432 B kept.

## Dissection answers

1. **Did `core_cb_class` append a request?** **Yes, for both.** `ep0-post` for GET and
   SET reports the same pending request object `req=68a84620` with `buf=68944d7c`,
   `len=0x1a`, `complete=5f564a74`, `status=-115 (EINPROGRESS)` — the handler reached
   `__dwc3_gadget_ep0_queue`; the pre/post snapshots are not identical (`next` 2→1,
   `event` 1→2, endpoint BUSY flags changed).
2. **Which branch armed?** `dep_flags` bit5 is clear (`1`, later `0x11`) and
   `dwc+0x2d8` bit0 is set (`state=0x8d` GET, `0x89` SET), so the queue took the
   **"setup/data state → arms transfer"** branch (not the pending-data, deferred-status
   or fall-through paths). Post-state `next=1` matches the armed observable; GET arms
   EP0-IN (`eps1 flags=0x11` BUSY), SET arms EP0-OUT (`eps0 flags=0x11` BUSY).
3. **Why the 5 s timeouts?** Both TRBs are armed, but:
   - **GET (DATA_IN):** `dma=0x08944d7c` is a valid direct-map address of `buf`
     (`0x68944d7c − 0x60000000`), length 26, completion `5f564a74` — no DMA defect is
     visible, yet the host never received/completed the transfer within 5 s.
   - **SET (DATA_OUT):** the same request has **`dma=0`** — the OUT data phase has no DMA
     target, so it can never complete (this would block COMMIT even if GET worked).
   The first blocker is therefore GET's **post-arming completion** (armed IN TRB not
   completed/observed); SET's missing DMA is a second, definite defect. Which of
   "start_trans/command failed silently" vs "completion IRQ/callback not run" is true
   needs the residual state after the timeout — now instrumented (E0360 module).

## Offline work in this round

- Added **`STOP-pre` residual EP0 snapshot** (read-only), so the next run prints the
  request list/state/next/event/flags at teardown, i.e. after both 5 s timeouts:
  module `artifacts/native/uvc-transport-e0360-stopstate/usbg_video_a6400_shared_candidate.ko`,
  **79,248 B**, SHA-256 `c7050ada26f4f53022269c8bfbe0ae2b4529031aeb0c4e29b91b539d10995fc0`,
  audit **117/8/0**. Interpretation for Run B6: request still pending + BUSY →
  completion never fired (start_trans/IRQ path); list empty + status 0 → completion
  fired but the host rejected/missed the data (then GET reply length/content is the
  target); list empty + status non-zero → record the exact status.
- **No blind DMA fix was applied yet.** Mapping a missing `req->dma` in a queue wrapper
  is the obvious SET fix, but GET fails first with a valid DMA; fixing SET alone cannot
  let the probe sequence progress. The E0358 Unicorn harness already models both
  outcomes (armed: `next=1` + BUSY + map/start calls; silent no-transfer paths), and the
  Run B5 capture now pins the real one — the residual snapshot decides the next change.

## Limits

One snapshot pair per transfer; the 5 s timeout state after queue is not captured
(instrumented for the next run). The `complete=5f564a74` callback fires in UDC IRQ
context and is not logged; wrapping it is the next instrumentation if the residual
snapshot shows the request still pending.

## Next: Run B6 (needs go-ahead)

Module `c7050ada…` + daemon `99047575…`, same sequence/ETW; then read `STOP-pre`.
If pending/BUSY → instrument `req->complete` (wrap the request before queue via the
same read-only CLASS path) and/or add a delayed EP0 snapshot, then fix the start_trans/
completion path offline + Unicorn. If empty/status 0 → the armed IN data was accepted by
the UDC but the host rejected it: inspect the 26-byte reply (template + `dwFrameInterval`)
and the host-side probe expectations. In both cases SET's `dma=0` mapping fix is queued
next, and the clean-teardown/no-battery-pull behaviour should repeat.

## Verification

Full suite **1312 tests OK** (`artifacts/analysis/e0360-runb5/suite.log`); module audit
117/8/0; camera ended healthy in MSC with the module unloaded, no battery pull; no host
flash/SD writes (read-only SD mount only); ETL/receipts retained.
