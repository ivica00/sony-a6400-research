# E0362 — Run B7: OUT DMA wrapper works (`mapped=1`, dma valid, armed) but both EP0 transfers still time out; completion thunk built for Run B8

Date: 2026-11-11. **Physical, user-authorized Run B7.** Module `79b16377…` (EP0 queue
OUT-DMA wrapper) + daemon `99047575…` (`--dmesg-sd --sd-log --sd-mount`). One ffmpeg
attempt. **Clean teardown, native 054C:0CAA and Mass Storage without a battery pull.**
ETL 510,238,720 B kept.

## Run B7 result

Wrapper evidence (this boot):
```
[234.990] CLASS entry rt=a1 req=81 val=0100 idx=0002 len=001a       (GET_CUR PROBE)
[234.990471] EP0 queue dir=IN  req=608a8740 buf=689801dc dma=00000000 len=26 mapped=0
[234.990641] EP0 queue exit ret=0 dma=089801dc state=8d next=00000001 event=00000002
[234.991] CLASS ep0-post … eps1=…/00000011 pending req=608a8740 dma=089801dc status=ffffff8d
[239.991756] CLASS entry rt=21 req=01 val=0100 idx=0002 len=001a      (SET_CUR PROBE, +5.001 s)
[239.992617] EP0 queue dir=OUT req=608a8740 buf=689801dc dma=089801dc len=26 mapped=1
[239.992777] EP0 queue exit ret=0 dma=089801dc state=8b next=00000001 event=00000002
[239.993] CLASS ep0-post … eps0=…/00000011 pending req=608a8740 dma=089801dc status=ffffff8d
[372.532963] STOP-pre … state=99 next=00000003 event=00000002, request list empty
```
- The **OUT-DMA wrapper worked exactly as designed**: the SET_CUR request reaches the
  original UDC queue with `dma=089801dc` (`mapped=1`), `ret=0`, `next=1`, `eps0` BUSY.
- GET is still mapped by the UDC itself (`dma=089801dc`, `next=1`, `eps1` BUSY).
- **No `SET_CUR COMMIT` (`val=0200`) and no `SET_INTERFACE` followed**: both transfers
  still time out at the host (5.001 s + 5.0 s), and ffmpeg fails with
  `Could not RenderStream to connect pins`. Since both requests now have a valid DMA and
  are armed, the failure is **after arming** (TRB/command/completion), not the DMA gap.
- **STOP-pre:** `state=99, next=3, event=2`, request list empty → the armed requests are
  released only when the next SETUP/teardown aborts them, not while the host waits.

## Disassembly of the armed branch (E0358 addresses, live state)

Live pre-state for both transfers: `dwc+0x2d8` has **bit0 set** (`0x8d` GET, `0x89` SET),
`dep_flags` bit5 clear, `event=1`; the queue therefore takes the **"setup/data state
(bit0) → arms transfer"** branch of `__dwc3_gadget_ep0_queue 0x602b26ec`, which calls
`__dwc3_ep0_do_control_data 0x602b25c8` → `dwc3_ep0_start_trans 0x602b2424`
(the GET IN path issues the data-stage TRB with the mapped `req->dma`; the SET OUT path
now uses the same mapped buffer thanks to the wrapper). Per the E0358 disassembly,
`__dwc3_gadget_ep0_queue` **sets `req->status = -115` and ignores failures of those calls
(warn-only)**, then returns 0 — consistent with `next=1`/BUSY even when the TRB/command
never actually starts or completes. `__dwc3_gadget_ep0_queue` is reached from
`dwc3_gadget_ep0_queue 0x602b2ad0`; the state-machine writes `next`/`event` and the
endpoint BUSY flags before/around `start_trans`, so the software state is not proof that
the DEPCMD (`DEPSTRTXFER` for the data stage) was accepted by the controller.

## Offline work: completion thunk (Run B8 candidate)

Implemented in `uvc_callback_bridge.c`: the queue wrapper now replaces
`req->complete` (offset 28) with a thunk that logs
`EP0 complete req=… status=… actual=… state=… next=… event=…` and then calls the original
`uvc_ep0_comp` (`0x5f564a74`). This will prove whether completion fires:
- **immediately** (status 0 / cleared `-EINPROGRESS`) → the UDC transferred the packet
  and the host-side timeout is a protocol/status issue;
- **only at the next SETUP/teardown** (status `-104`/`-108`) → the armed TRB/command never
  ran; then the `__dwc3_ep0_do_control_data`/`start_trans` return codes (ignored today)
  are the fix point.
Also widened the read-only pointer guard to accept module addresses (`0x5f……`) so the
snapshot prints `queue=<wrapper>` correctly.

Module: `artifacts/native/uvc-transport-e0362-compthunk/usbg_video_a6400_shared_candidate.ko`,
**81,508 B**, SHA-256 `9933cb1f422267d7a8ddf618785f09d9b6c39ae964c690433e7ad561f8e1122c`,
transport audit `offline_module_audit_passed` (**117/8/0**).

## Verification / state

Full suite **1312 tests OK**; camera ended healthy in MSC (42 modules, no `usbg_video`,
`/tmp_bt` baseline), no battery pull; no host flash/SD writes (read-only SD mount);
receipts/ETL under `artifacts/analysis/e0362-runb7/`.

## Next: Run B8 (needs go-ahead)

Module `9933cb1f…` + daemon `99047575…`, same sequence; read the `EP0 complete` lines:
immediate vs abort-time completion decides between (a) host/status protocol fix and
(b) start_trans/DEPCMD failure. If completion is immediate with status 0 but the host
still times out, the next step is the 26-byte GET reply content/length and the
SET_CUR data path; if it is abort-time, instrument the `start_trans`/command return and
map the DEPCMD error to a fix (likely making the queue honour the failure and retry/arm
the data stage from the correct EP0 state).
