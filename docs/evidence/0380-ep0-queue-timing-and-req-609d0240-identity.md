# E0380 — Retraction: `GCRO queue req=609d0240` is our own freshly queued class request; `dep0->request_list` was EMPTY at pre; complete-data has no HWO check

Date: 2026-11-12. Offline only (B14 log + vmlinux + ETL summary). No camera.

## 1. Corrected GCRO pre vs queue (B14 log)

GET_CUR:
```
GCRO CLASS pre ... dep0=68a1c9c0/00000001 dep1=68a1c3c0/00000001
  e0=68a1c9e4 e1=68a1c3e4 ... state=1 next=2 fl=8d
GCRO queue ... bpl=0986539c sz=0000001a ctl=00000c53
  dep0=68a1c9c0/00000001 dep1=68a1c3c0/00000011 e0=609d0274 state=2 next=1 fl=8d
GCRO queue dep0_head req=609d0240 buf=6986539c len=26 actual=0 status=-115
EP0 complete ... req=609d0240 status=0 actual=26
GCRO complete ... e0=68a1c9e4 ...
```
SET_CUR:
```
GCRO CLASS pre ... e0=68a1c9e4 ... state=1 next=2 fl=89
GCRO queue ... bpl=08a26000 sz=00000040 ctl=00000c53
  dep0=68a1c9c0/00000011 ... e0=609d0274 state=2 next=1 fl=8b
GCRO queue dep0_head req=609d0240 buf=6986539c len=26 actual=0 status=-115
EP0 complete ... req=609d0240 status=0 actual=0
GCRO complete ... bpl=08a26000 sz=00000040 ctl=00000c53 ... e0=68a1c9e4
```
- `GCRO CLASS pre` runs before `ep0->ops->queue`; `e0 = 68a1c9e4 = dep0+0x24`
  (request_list EMPTY). `GCRO queue` runs **after** `ep0->ops->queue` returned; the
  TRB is already programmed (`bpl/sz/ctl`), `dep1` or `dep0` BUSY is set, and
  `e0=609d0274` is the **newly queued** request.
- `609d0274 - 609d0240 = 0x34` = the `dwc3_request.list` offset; `buf=6986539c`,
  `len=26` = our UVC class request. `status=-115` (EINPROGRESS) is set by
  `__dwc3_gadget_ep0_queue`.
- Therefore **E0379's “stale request at the head” conclusion is retracted**: the list
  was empty at pre, and `609d0240` is the active class request. Do not drop/drain it.

## 2. `dwc3_ep0_complete_data` (inline in `dwc3_ep0_interrupt`, 0x602b30a8..0x3344)

Key instructions (from E0366/E0372 listings):
```
30a8 ldr r3,[dwc+0xd0]          ; dep0
30c0 str r3,[dwc+0x2dc]         ; next_event = 3
30c8 ldr r5,[dep0+0x24]!        ; request_list head
30d8 ldrb r3,[r5,#0x50]         ; (NULL deref if empty)
30e8 ldr r2,[dwc+4]             ; ep0_trb
30ec..3104 read trb->size
3108 lsr r2,r3,#0x1c ; cmp #2 ; bne 3134   ; TRBSTS special case
3134 tst sl,#1 ...
3144..3178 (IN path) or 31f0.. (OUT bounce path) compute transferred
3330 cmp r5,#0 ; 3338 ldr r0,[fp,-0x40] ; 333c r1=r5 ; 3340 r2=sb
3344 bl dwc3_gadget_giveback
```
- It **does not test `ctrl & 1` (HWO)** before computing `transferred`; it reads
  `trb->size` and gives back the request.
- When called with the new bounce TRB still `size=0x40, ctrl=0x0c53 (HWO=1)`, it
  computes `transferred = 0` and gives back with `actual=0`, leaving the TRB untouched.
  That matches the SET observation exactly.

## 3. Two possible giveback sources at SET complete

1. **Complete-data path** (`0x30a8..0x3344`, ep0state==DATA dispatch): reads the bounce
   TRB, HWO=1, gives back `actual=0`.
2. **Status-complete path** (`0x334c..0x3364`, ep0state==3 dispatch): walks
   `dep0->request_list`, gives back the head request with the caller's leftover status
   (0), then sets `ep0state=1` and calls `out_start`.

`GCRO complete` logs inside `req->complete`, i.e. **before** `0x3370/0x3374`, so both
paths are compatible with the captured `state=2, next=3, TRB unchanged`. The B14 probe
did not log the caller LR, so the exact source is **not yet distinguished**. This is the
next probe's key field.

## 4. ETL status

The B14 ETL (676,372,480 B) was summarized with `tracerpt -summary`:
**3,319,504 events, 229 s, 0 lost**; providers include Microsoft-Windows-USB-USBHUB3.
The full per-URB control-transfer decode across the `GET_CUR → SET_CUR` window is **not
yet extracted**; it is the next offline step (dump USBHUB3/USBPORT/USBXHCI events to
CSV/XML and filter the device/control-transfer window). The ETL cannot be replaced by
the kernel printk timestamps for the 5.000 s gap.

## 5. Probe corrections for e0381

- `GCRO` event buffer: `[dwc+0xcc]` is the `ev_buffs[]` array pointer; use
  `ev = *([dwc+0xcc])` (double dereference), then `+0 buf/+4 len/+8 lpos/+0xc count`.
  Verify `dwc->regs` offset used for `GEVNTCOUNT0` against the `e0372` build (which
  successfully logged `lpos=0x298 cnt=0xc`).
- Log the **caller LR inside `EP0 complete`** (`__builtin_return_address(0)` in the
  completion thunk) to distinguish complete-data `0x3344` from status `0x3364`.
- Keep GCRO strictly read-only; no ops shadows, no `lr` filtering, no status kicks,
  no queue guard/drain based on E0379's retracted stale hypothesis.

## 6. Verdict

- `dep0` list empty at pre; `req=609d0240` is the active 26-byte class request.
- SET's completion gave back that request with `actual=0` while the bounce TRB still had
  `HWO=1`: either complete-data processed a stale event (likely the pre-existing
  `0x2ac` XferComplete ep0 from the batch) or the status-complete path gave it back.
- Both are testable with one read-only probe: correct ev pointer + completion LR +
  GEVNTCOUNT/lpos.
- Do not build `e0379-gcguard` around a stale-request hypothesis.
