# E0379 — Run B14-roprobe: `dep0->request_list` is ALREADY non-empty at GET/SET queue (stale request 609d0240, len 26, status -115); SET bounce TRB stays HWO=1

Date: 2026-11-12. Physical, read-only Run B14-roprobe with module `465d6a4e…`
(GCRO probe, 86,476 B, audit 117/8/0, exact-object Unicorn overall_pass=true), daemon
`99047575…`. Clean receipt, native 054C:0CAA/MSC, **no battery pull**, no reboot
(42 modules, `/tmp_bt` baseline after cleanup).

## 1. GCRO evidence (A6400K.LOG)

GET_CUR (`CLASS entry rt=a1 ...` at 140.672):
```
GCRO CLASS pre ctrl=ffdfe000 cr0=010081a1 cr1=001a0002 dma=089fe000
  trb=ffdfd000 ta=089ff000 bpl=089fe000 sz=00000000 ctl=00000c22
  bv=ffdfc000 ba=08a26000 dep0=68a1c9c0/00000001 dep1=68a1c3c0/00000001
  e0=68a1c9e4 e1=68a1c3e4 ev=689fc810 lpos=0 cnt=0 flg=6970a7a0 gcnt=0
  state=1 next=2 fl=8d
GCRO queue ... bpl=0986539c sz=0000001a ctl=00000c53
  dep0=68a1c9c0/00000001 dep1=68a1c3c0/00000011 e0=609d0274 e1=68a1c3e4 state=2 next=1 fl=8d
GCRO queue dep0_head req=609d0240 buf=6986539c len=26 actual=0 status=-115
GCRO CLASS post ... sz=00000000 ctl=00000c52 e0=609d0274 ... state=2 next=1 fl=8d
GCRO CLASS post dep0_head req=609d0240 buf=6986539c len=26 actual=0 status=-115
EP0 complete ep=68a1c9c0 req=609d0240 status=0 actual=26 state=8d next=3 event=2
GCRO complete ... sz=00000000 ctl=00000c52 e0=68a1c9e4 ... state=2 next=3 fl=8d
```
SET_CUR (`CLASS entry rt=21 ...` at 145.683):
```
GCRO CLASS pre ctrl=ffdfe000 cr0=01000121 cr1=001a0002 ...
  dep0=68a1c9c0/00000001 e0=68a1c9e4 ... state=1 next=2 fl=89
GCRO queue ... bpl=08a26000 sz=00000040 ctl=00000c53
  dep0=68a1c9c0/00000011 dep1=68a1c3c0/00000001 e0=609d0274 ... state=2 next=1 fl=8b
GCRO queue dep0_head req=609d0240 buf=6986539c len=26 actual=0 status=-115
GCRO CLASS post ... e0=609d0274 ... state=2 next=1 fl=8b
GCRO CLASS post dep0_head req=609d0240 buf=6986539c len=26 actual=0 status=-115
EP0 complete ep=68a1c9c0 req=609d0240 status=0 actual=0 state=89 next=3 event=2
GCRO complete ... bpl=08a26000 sz=00000040 ctl=00000c53
  dep0=68a1c9c0/00000001 e0=68a1c9e4 ... state=2 next=3 fl=89
```

## 2. Interpretation

- `ctrl` argument is correct: GET `bmRequestType=0xa1, bRequest=0x81, wValue=0x0100,
  wIndex=0x0002, wLength=0x001a`; SET `0x21,0x01,0x0100,0x0002,0x001a`
  (`cr0/cr1` little-endian). `[dwc+0]` read 0 in GCRO (ctrl NULL), so `[dwc+0]` is not
  the `ctrl_req` CPU pointer in this kernel; the class ctrl pointer is `ffdfe000`
  (DMA `089fe000`, same buffer the setup TRB used: pre-TRB `bpl=089fe000`).
- **`dep0->request_list` is NOT empty at GET/SET queue:**
  `e0 = 609d0274 != dep0+0x24`, head request `609d0240`, `buf=6986539c`,
  `len=26`, `actual=0`, `status=-115` (EINPROGRESS from `__dwc3_gadget_ep0_queue`).
  The SAME request object (`609d0240`, len 26) is present at both GET and SET queue
  and is the one later given back (`EP0 complete ... req=609d0240`).
- GET queue: TRB `bpl=0986539c, size=0x1a, ctrl=0x53` (HWO=1) → completes with
  `size=0, ctrl=0x52` (HWO=0), `actual=26`.
- SET queue: TRB `bpl=08a26000, size=0x40, ctrl=0x53` (HWO=1), dep0 BUSY=0x11,
  list still `e0=609d0274`; completion at 0x2ac gives `req=609d0240 actual=0` and the
  TRB is **unchanged** (`size=0x40, ctrl=0x53` HWO=1) → our SET data TRB was never
  consumed; the completed request was the stale head request.
- So the SET failure is not a missing ctrl_req; it is a **stale/duplicate EP0 request
  already on `dep0->request_list` before the class data queue**. `__dwc3_gadget_ep0_queue`
  appended the new request to the tail and the head stayed in place; the head's
  completion at 0x2ac was then processed against the new bounce TRB, producing
  `actual=0` and `HWO=1`.
- `core_cb_start` START trace: `START entry iface=2 count=1` at 121.640 and 606.310
  (and reference START entry at 132.75), but **no START callback between GET complete
  (140.68) and SET pre (145.68)** in this run. The stale request was therefore left by
  an earlier standard/start path (most plausibly the `0x1318` `core_cb_start` queue plus
  the `0x9fd8` delegated queue from SET_CONFIGURATION/SET_INTERFACE), or by a queue that
  never completed — not by a START during the 5 s window.
- Event-ring snapshot in this probe read `ev=689fc810 lpos=0 cnt=0 gcnt=0` at all
  points (the buffer pointer/lpos fields need re-validation for this module build); the
  earlier `e0372` probe already established the ring words. The request-list evidence is
  independent and decisive.

## 3. Minimal code change (proposed, not yet applied)

The stale head request must not be present when the class data queue runs. The concrete
candidate is to prevent the standard start path from leaving a duplicate EP0 request:
- in the bridge's EP0 queue wrapper, before forwarding a **class data queue**, check
  `dep0->request_list`; if non-empty with a request whose `status == -115` and
  `len > 0`, do not append another request (return 0 with a log) or complete/drain the
  stale head first;
- alternatively suppress the duplicate `0x9fd8` delegated queue after `core_cb_start`
  `0x1318` success for SET_CONFIGURATION/SET_INTERFACE (the likely origin of the stale
  request), but this needs a targeted test because the delegated status is required for
  enumeration.

Next build: `e0379-gcguard` with a read-only first phase that logs the stale head at
every queue, then an opt-in queue guard only for class data requests; verify in Unicorn
and run one bounded probe.

## 4. State

Receipt clean (`stop_verified=1`, `teardown_verified=1`); camera healthy in MSC (42
modules, no `usbg_video`, `/tmp_bt` baseline). Full suite **1312 tests OK**. ETL
676,372,480 B retained under `artifacts/analysis/e0378-runb14roprobe/`.
