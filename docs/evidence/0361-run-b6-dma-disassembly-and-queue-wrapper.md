# E0361 — Run B6 + disassembly: both paths zero `dma`, UDC maps only IN; requests only released on abort; EP0 queue DMA wrapper built for Run B7

Date: 2026-11-11. **Physical, user-authorized Run B6** (module `c7050ada…`, daemon
`99047575…`, `--dmesg-sd --sd-log --sd-mount`) plus offline disassembly of the reference
object. One ffmpeg attempt. **Clean teardown again, native 054C:0CAA/MSC without a
battery pull**; ETL 574,717,952 B kept.

## 1. Disassembly (reference.rebound.o, module base 0x5f563000)

- **GET_CUR helper** (`.text 0x12cc..0x1318`, called from the 0x16a4 PROBE/COMMIT branch):
  `memcpy` reply → sets `req->buf = ep0_buffer`, `req->length = wLength`, then
  `0x12fc: mov r6,#0; str r6,[r4,#8]` → **explicitly sets `req->dma = 0`**, sets
  `req->complete = uvc_ep0_comp` (`0x1a74`), `context = 0`, queues via
  `ep->ops->queue` (`[[ep+8]+0x10]`).
- **SET_CUR path** (`.text 0x183c..0x1970`): alloc request, `0x18e8 stm r6,{r0,r8}`
  (buf=ep0_buffer, length=wLength), `0x18ec: str r3,[r6,#8]` with `r3=0` → **also
  explicitly sets `req->dma = 0`**, complete=0x1a74, context=0, queues via the same slot.
- **Completion `uvc_ep0_comp` (0x1a74)**: if `r1==0` it builds an 8-byte message on the
  stack and calls the local log helper `0x958`; otherwise it calls
  `[[r0+8]+0xC]`. It performs **no unmap/free and does not clear `dma`**.
- Conclusion: both request-prep paths deliberately leave `dma=0`; the difference seen in
  Run B5 (`GET dma=0x08944d7c` vs `SET dma=0`) is that the **UDC `dwc3_gadget_ep0_queue`
  maps the IN request** (as part of arming the data phase) but leaves an **OUT** request
  unmapped. gadgetcore never wraps `ep0`, so nothing else maps the OUT buffer → the
  SET_CUR data phase has no DMA target.

## 2. Run B6 (shows the requests are released only on abort/teardown)

This boot: GET_CUR `148.612` (translated), SET_CUR PROBE `153.623` (**+5.011 s**),
STOP-pre `288.204`. Values identical in structure to B5:

- GET post: `eps1=…/00000011`, `next=1 event=2`, pending `req=608a8560 buf=68a9e6bc
  len=1a dma=08a9e6bc complete=5f564a74 status=-115`.
- SET post: `eps0=…/00000011`, `next=1 event=2`, pending `req=609d0b40 buf=68a9e6bc
  len=1a dma=00000000 complete=5f564a74 status=-115`.
- **STOP-pre residual (new):** `state=89 next=00000003 event=00000002`, `eps0=…/1`,
  `eps1=…/1`, **no pending request line** → the request list is empty. Both armed
  requests were given back before/at teardown (the GET one when the next SETUP arrived,
  the SET one when the host aborted), i.e. neither completed while the host waited.
  This matches the 5 s + 5 s timeout pattern and rules out a permanently stuck request
  list; the armed TRBs were never serviced in time.

## 3. Fix implemented: EP0 queue wrapper maps control-OUT DMA

`tools/native_camera/uvc_callback_bridge.c` now installs a **shadow `ep0->ops` table**
(first CLASS entry) whose queue slot is a wrapper around the original UDC queue:
- records the CLASS direction (`bmRequestType` bit7) and logs
  `EP0 queue dir=OUT/IN req/buf/dma/len mapped=…` before and
  `EP0 queue exit ret=… dma=… state/next/event` after the call;
- for an **OUT** request with `dma==0` and a direct-mapped buffer, stores
  `req->dma = buf - 0x60000000` (the same relation the IN mapping produced in B5/B6:
  `0x68a9e6bc → 0x08a9e6bc`) before forwarding to the original queue;
- restores `ep->ops` at STOP; no other ops are changed (table copied from the live
  `0x603dfb4c`). Module:
  `artifacts/native/uvc-transport-e0361-qwrap/usbg_video_a6400_shared_candidate.ko`,
  **80,828 B**, SHA-256 `79b16377bc5028680c311a87b79c25f3f875284c0459b3bc17ccb68896e0d7d7`,
  transport audit `offline_module_audit_passed` (**117 checks / 8 skips / 0 failures**).

Unicorn: the E0358 harness still passes for the real UDC queue model
(`data-state-arms-transfer` proves the mapped request arms with `next=1`/BUSY and
`usb_gadget_map_request`+start command; silent paths remain silent); the wrapper supplies
exactly that mapping for OUT, which the raw UDC queue does not do. (The wrapper C itself
is exercised by Run B7, not by the vmlinux-byte harness.)

## 4. Expected in Run B7

`A6400K.LOG` should show, for SET_CUR PROBE:
`EP0 queue dir=OUT req=… buf=… dma=0 len=26 mapped=1` → `dma=08…`
then `EP0 queue exit ret=0 … next=1 event=2`, followed by a **SET_CUR COMMIT**
(`rt=21 req=01 val=0200 len=1a`). GET_CUR may still show its 5 s timeout (usbvideo
tolerates the probe GET and proceeds with defaults — that is how B5/B6 reached SET_CUR
at all); if COMMIT succeeds and `SET_INTERFACE` follows, RenderStream should connect and
the next blocker would be frames (no host liveview consumer / producer wake, unchanged).
The wrapper log also records whether the original queue returns non-zero or the armed
state differs.

## 5. Verification / state

Full suite **1312 tests OK**; module audit 117/8/0; camera ended healthy in MSC with
42 modules, no `usbg_video`, `/tmp_bt` baseline, no battery pull; no host flash/SD
writes (read-only SD mount only); ETL/receipts under `artifacts/analysis/e0361-runb6/`.
