# E0392 — Run B18 `e0391-ramring`: zero-printk RAM ring shows GET data completes in <1 ms, but the host still waits 5.01 s before SET_CUR; no START/core queue; full ETW captured before enumeration

Date: 2026-11-12. Physical Run B18 with `e0391-ramring` module
`a5adbffc8131ed596f1e2bfa3de429a897b0161f39dca99114d3ad19b76e83f3`
(79,844 B, audit 117/8/0, suite 1312 OK). ETW was started **before** the PC-Remote
switch; capture 143,269,888 B. Battery pull was needed at the final MSC switch; the
ring had already been dumped at the first STOP.

## 1. Full RAM-ring dump (A6400K.LOG, 134.295)

```
RAMRING n=9 dropped=0 start=1 class=2 get=1 set=1 queue=2 complete=2
RR 0 h=0 t=120.879457001 ep=00000000 req=00000001 ... res=1756020092
RR 1 h=1 t=128.120845501 ep=68a1c9c0 req=00000000 bm=a1 rq=81 v=0100 i=0002 l=001a lpos=290 cnt=4 ev=0 st=01 nx=2 fl=8d ctl=0 sz=0 act=0 sts=0
RR 2 h=2 t=128.120900501 ep=68a1c9c0 req=69567720 bm=00 rq=00 ... lpos=290 cnt=4 st=01 nx=2 fl=8d
RR 3 h=4 t=128.120960501 ep=68a1c9c0 bm=a1 rq=81 ... lpos=290 cnt=4 st=02 nx=1 fl=8d res=0
RR 4 h=3 t=128.121791501 ep=68a1c9c0 req=69567720 ... lpos=294 cnt=4 st=02 nx=3 fl=8d act=26 sts=0
RR 5 h=1 t=133.131973001 ep=68a1c9c0 bm=21 rq=01 v=0100 i=0002 l=001a lpos=2a0 cnt=c st=01 nx=2 fl=89
RR 6 h=2 t=133.131989501 ep=68a1c9c0 req=69567720 ... lpos=2a0 cnt=c st=01 nx=2 fl=89
RR 7 h=4 t=133.132004001 ep=68a1c9c0 bm=21 rq=01 ... lpos=2a0 cnt=c st=02 nx=1 fl=8b
RR 8 h=3 t=133.132030001 ep=68a1c9c0 req=69567720 ... lpos=2a8 cnt=4 st=02 nx=3 fl=89 act=0 sts=0
```

Key facts:
- **START** (`RR0`) recorded only one hook; there is no EP0 queue record from START.
- **GET_CUR** (`RR1..RR4`): class at 128.120845, queue at 128.120900, class exit at
  128.120960, completion at **128.121791** with **actual=26** — the data phase
  completes ~0.95 ms after class entry. `lpos` moves 0x290→0x294, state 1→2→2, next
  2→1→3.
- **SET_CUR** class starts at **133.131973**, i.e. **5.011128 s after the GET
  completion**, with `lpos=0x2a0 cnt=0xc`, state 1 next 2 fl 0x89. Queue and class
  exit follow within ~0.03 ms; completion at 133.132030 returns **actual=0** with the
  bounce TRB still pending (same stale/queued ep0 completion path as B12–B16).
- Therefore the **5 s wait is after the GET data phase and before SET_CUR**, i.e. the
  host is still waiting for the GET status stage; the zero-printk build did not change
  it. The status XferComplete is not captured by the ring (not hooked), but the
  host/SET timing proves the status stage remains the wedging point.
- No START/core_cb_start queue exists in the ring; the standard delegated queue
  (`lr=602b9fdc`) is not a class/START queue and is not recorded here.

## 2. Full-enumeration ETW

The ETW session was started while the camera was still in MSC, before the PC-Remote
switch; the resulting `usb-capture.etl` is 143,269,888 B. Both ffmpeg attempts still
failed:
- default `ffmpeg -f dshow -i video="ILCE-6400"`: `Could not RenderStream`;
- explicit `-video_size 1280x720 -framerate 30`: same `Could not RenderStream`.
No frame was produced.

The ETL was retained for full URB timeline extraction; the XML conversion had not
completed within this run, so the ring is the authoritative device-side evidence here.

## 3. Verdict

- Zero hot-path printk did **not** remove the 5 s wait. GET data completes in <1 ms;
  the host still waits 5.011 s before SET_CUR. The wedge is the GET status stage, not
  printk and not a START/core_cb_start double queue.
- No START queue is present in the RAM ring; the previous `core_cb_start 0x1318`
  attribution remains disproven (0x1318 is the GET helper queue).
- SET completes with actual=0 on the stale/queued ep0 completion while the bounce TRB
  is still HWO=1, as in B12–B16.
- Clean rmmod/MSC did not happen: battery pull was required at the final switch
  (daemon receipt stop_verified=0/teardown_verified=0); camera is healthy in MSC,
  42 modules after reboot.
- Next: decode the full-enumeration B18 ETL for the initial GET_CUR/SET_CUR URB
  durations and status completion; then target the status stage (why the host does not
  ACK it until 5.01 s) rather than printk/queue double-queue.
