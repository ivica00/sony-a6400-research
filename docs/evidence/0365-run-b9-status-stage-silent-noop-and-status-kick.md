# E0365 — Run B9: data stage succeeds (`status=0`), status ZLP never starts; SET_CUR payload ignored; status-kick fix built for Run B10

Date: 2026-11-11. **Physical, user-authorized Run B9** with the corrected two-argument
completion thunk `aec24ce5…` + daemon `99047575…` (`--dmesg-sd --sd-log --sd-mount`).
One ffmpeg attempt. **Clean teardown, native 054C:0CAA/MSC without a battery pull; no
crash.** ETL 547,241,984 B kept.

## 1. Exact `EP0 complete` values (this boot)

```
[115.482] CLASS entry rt=a1 req=81 val=0100 idx=0002 len=001a
[115.482982] EP0 queue dir=IN req=68a84680 buf=68a9e9bc dma=00000000 len=26 mapped=0
[115.483165] EP0 queue exit ret=0 dma=08a9e9bc state=8d next=00000001 event=00000002
[115.483845] CLASS ep0-post pending req=68a84680 dma=08a9e9bc status=ffffff8d
[115.484182] EP0 complete ep=68a1c9c0 req=68a84680 status=0 actual=26
             state=8d next=00000003 event=00000002 dep0=00000001 dep1=00000001
[120.492] CLASS entry rt=21 req=01 val=0100 idx=0002 len=001a     (SET_CUR PROBE, +5.001 s)
[120.493102] EP0 queue dir=OUT req=695678a0 buf=68a9e9bc dma=08a9e9bc len=26 mapped=1
[120.493263] EP0 queue exit ret=0 dma=08a9e9bc state=8b next=00000001 event=00000002
[120.493851] CLASS ep0-post pending req=695678a0 dma=08a9e9bc status=ffffff8d
[120.494227] EP0 complete ep=68a1c9c0 req=695678a0 status=0 actual=0
             state=89 next=00000003 event=00000002 dep0=00000001 dep1=00000001
```

- GET_CUR: **`status=0, actual=26`**, ~1.02 ms after queue exit; SET_CUR: **`status=0,
  actual=0`**, ~0.96 ms. The thunk signature is correct (`ep,req`), request freed by
  `uvc_ep0_comp` (`free_request(ep,req)`), no crash.
- Both completions show `next=3` (status pending), `event=2`, and **dep0=dep1=1 (no
  DWC3_EP_BUSY `0x10`)** at completion time.
- `SET_CUR actual=0` (host sent 26 bytes, none counted) is consistent with section 3.

## 2. Why the status ZLP never completes (disassembly)

`dwc3_ep0_interrupt @ 0x602b2c68`:
- XferComplete gives the request back and returns (`602b3338 mov r0,[fp,-0x40];
  602b333c mov r1,r5; 602b3340 mov r2,sb; 602b3344 bl dwc3_gadget_giveback`) — **no
  status start from the completion path**.
- XferNotReady(Status) at `0x602b3448`: `ldr r3,[r0,#0x2dc]; cmp r3,#3; bne exit`;
  `str r3,[r0,#0x2e0]`; `ldrb r3,[r0,#0x2d8]; and r3,#0x20` (DEFERRED_STATUS);
  `cmp 0; beq 0x602b34a4`. Our completion states `0x8d`/`0x89` have bit5 clear, so the
  immediate `__dwc3_ep0_do_control_status` path is the intended one.
- `__dwc3_ep0_do_control_status @ 0x602b253c`:
  `602b2578 ldr r0,[r5,#0x48]` (dep->dwc), `602b257c ldrb r1,[r5,#0x54]` (ep number),
  `602b2584 tst r3,#1; moveq r2,#0x30; movne r2,#0x40` (status TRB ctrl from
  `dwc+0x2d8` bit0), `602b2590 tst r1,#1; movne r3,#0; ldrheq r3,[r5,#0x14]`
  (length: 0 for the IN-status/odd-ep case), `602b25a0 ldr r2,[r0,#0x10]` →
  **status data buffer = `dwc->ctrl_req_addr` (dwc+0x10)**, then
  `602b25a4 bl dwc3_ep0_start_trans`. Return non-zero → only `warn_slowpath_null`
  (`602b25b8`), i.e. ignored.
- `dwc3_ep0_start_trans @ 0x602b2424`:
  `602b2440 ldr r4,[r6,#0x4c]; ands r4,#0x10; movne r0,#0; bne exit` → **if
  `dep->flags & DWC3_EP_BUSY` the function returns 0 with NO TRB and NO command**;
  otherwise builds the status TRB (`ctrl | 0xC00 | 3`), length, and issues
  `dwc3_send_gadget_ep_cmd` type 6 (`DEPSTRTXFER`); on success sets dep BUSY and
  `dwc+0x2dc=1`; on command error returns negative.
- Direction flip: GET_CUR data is IN on eps1 → status ZLP OUT on **eps0**
  (`dwc+0xd0`); SET_CUR data is OUT on eps0 → status ZLP IN on **eps1** (`dwc+0xd4`).
  `do_control_status` selects the TRB control (`0x30`/`0x40`) from `dwc+0x2d8` bit0 and
  always uses the zero-length `ctrl_req` buffer at `dwc+0x10`.

**Conclusion:** the data stage completes in ~1 ms and sets `next=3`; the control status
stage is expected to start on XferNotReady but silently does not (start_trans’s BUSY
early-return / ignored DEPCMD). `dep` flags were clean at completion, so the BUSY state
must appear at the status event (endpoint reused between data/status) or the DEPCMD is
rejected — Run B10 will log which via the status kick and dep flags.

**Unicorn status-stage step** (`artifacts/analysis/e0365-runb9/status-stage-unicorn.json`):
stepping the real `__dwc3_ep0_do_control_status` code with a synthetic dwc/dep shows the
TRB control written as `0xC43` (0x40 | 0xC00 | 3) and, when `dep->flags=0x10` (BUSY), the
call returns with **no command and no TRB** (`cmd_calls=0`, `dwc+0x2dc=0`) — the silent
no-op branch. (The idle-path step is partial: the command stub returns, but a later
fetch is unmapped in the synthetic fixture; the TRB-control write is captured.)

## 3. Does `usbg_video` consume the 26 OUT bytes of `SET_CUR`?

No. The SET path (`core_cb_class 0x183c..0x190c`) does:
`bl usbg_video_get_ep0_buffer` → `stm r6,{r0,r8}` (buf, length=wLength),
`str r3,[r6,#8]` with r3=0 (**dma=0**), `complete=uvc_ep0_comp`, `context=0`, then
`ep->ops->queue` — **it never reads or parses the buffer**. `uvc_ep0_comp (0x1a74)`
only calls `free_request(ep,req)`. There is no secondary callback or worker. The 26
SET_CUR payload bytes are therefore **ignored** by `usbg_video` (fixed defaults in the
reference); `actual=0` confirms the OUT data was not copied into the request. The host
only needs the control status; the payload is not the blocker.

## 4. Fix implemented (Run B10 candidate)

Completion thunk now optionally **kicks the status stage explicitly** after a successful
data completion: if `req->status==0`, `next==3`, no kick yet, it calls the a6400
`__dwc3_ep0_do_control_status` at `0x602b253c` with
`(dwc, opposite-direction dep)` — GET (IN data) → eps0 OUT, SET (OUT data) → eps1 IN —
and logs `EP0 status kick dep=… state=… next=…`; the guard is reset per CLASS entry so
it runs once per transfer. Risk: if the UDC later delivers XferNotReady(Status) too, the
status TRB could be issued twice; the guard limits it to the completion path, and Run B10
must confirm no double completion.
Module: `artifacts/native/uvc-transport-e0367-statuskick/usbg_video_a6400_shared_candidate.ko`,
**82,096 B**, SHA-256 `694cb379392b721dd8724d2b808396ca64dba59be47482a8a84fe9d3c206901b`,
transport audit **117/8/0**.

## 5. Verification / state

Full suite **1312 tests OK**; camera ended healthy in MSC (42 modules, no `usbg_video`,
`/tmp_bt` baseline), no battery pull; no host flash/SD writes (read-only SD mount);
ETL/receipts under `artifacts/analysis/e0365-runb9/`.

## Next: Run B10 (needs go-ahead)

Module `694cb379…` + daemon `99047575…`, same sequence. Expected: the `EP0 status kick`
line after each data completion; if the status ZLP now completes, the host should send
`SET_CUR COMMIT` (`val=0200`); if not, the log will show whether the kick’s
`start_trans` silently returned early (BUSY at the status dep) and we can patch the
status-stage state (e.g. clear the stale BUSY before the kick) with the same Unicorn
harness.
