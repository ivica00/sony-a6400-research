# E0396 — Run B20 early-ring: GET_DESCRIPTOR and GET_CUR recorded together; flags match, status still stalls 5.01 s; battery pull again

Date: 2026-11-12. Physical Run B20 with `e0396-diff-ring`
`fe203832a8b3927f2e3b4ab387fe24a29165c974461a89540eae5da19cf1bb05` (80,356 B,
audit 117/8/0, suite 1312 OK). ETW started before PC-Remote switch (168,886,272 B).
Battery pull was needed at the final MSC switch.

## 1. Early-ring rows: GET_DESCRIPTOR vs GET_CUR

The early install (`0x6051b17c -> gc+4`) did capture standard descriptor queues
(`lr=602b9fdc`), GET_CUR (`lr=5f5644d0`), and SET_CUR (`lr=5f564918`):

```
RR 23 h=2 t=128.859661501 req=68a84da0 ... lpos=218 cnt=4 st=01 nx=2 fl=8d act=4 b0=04090304 b1=80000103 len=4 flg=02 lr=602b9fdc
RR 24 h=3 t=128.861025501 req=68a84da0 ... lpos=21c cnt=4 st=02 nx=3 fl=8d act=4 ... len=4 flg=02
RR 25 h=2 t=128.863683001 req=68a84da0 ... lpos=228 cnt=4 st=01 nx=2 fl=8d act=4 ... len=20 flg=02 lr=602b9fdc
RR 26 h=3 t=128.864641001 req=68a84da0 ... lpos=22c cnt=4 st=02 nx=3 fl=8d act=20 ... len=20 flg=02
RR 31 h=2 t=128.910994501 req=68a84da0 ... lpos=258 cnt=4 st=01 nx=2 fl=8d act=20 ... len=4 flg=02 lr=602b9fdc
RR 32 h=3 t=128.911645001 req=68a84da0 ... lpos=25c cnt=4 st=02 nx=3 fl=8d act=4 ... len=4 flg=02
RR 35 h=1 t=136.004948501 bm=a1 rq=81 v=0100 i=0002 l=001a lpos=290 cnt=4 st=01 nx=2 fl=8d
RR 36 h=2 t=136.004969001 req=68a844a0 ... lpos=290 cnt=4 st=01 nx=2 fl=8d len=26 flg=02 lr=5f5644d0
RR 37 h=4 t=136.004995001 bm=a1 rq=81 ... lpos=290 cnt=4 st=02 nx=1 fl=8d
RR 38 h=3 t=136.005833501 req=68a844a0 ... lpos=294 cnt=4 st=02 nx=3 fl=8d act=26 len=26 flg=02
RR 39 h=1 t=141.014028001 bm=21 rq=01 v=0100 i=0002 l=001a lpos=2a0 cnt=c st=01 nx=2 fl=89
RR 40 h=2 t=141.014054501 req=69567780 ... lpos=2a0 cnt=c st=01 nx=2 fl=89 len=26 flg=00 lr=5f564918
RR 41 h=4 t=141.014069001 bm=21 rq=01 ... lpos=2a0 cnt=c st=02 nx=1 fl=8b
RR 42 h=3 t=141.014096001 req=69567780 ... lpos=2a8 cnt=4 st=02 nx=3 fl=89 act=0 len=26 flg=00
```

Observations:
- GET_DESCRIPTOR transfers queue and complete in ~1.4 ms (`act=4/20/10`), with
  `flg=02` and `lr=602b9fdc`.
- GET_CUR has the **same** `flg=02`, `lpos` before/after 0x290→0x294, `cnt=4`, and
  completes data at 136.005833 with `act=26`; then SET_CUR starts **5.009 s later**
  (141.014028), `flg=00`, and completes `act=0`.
- The event/TRB fields (`ev`, `ctl`, `sz`) are still zero in the ring; the corrected
  readouts did not materialize at these hook points (the ring is recording before the
  event/TRB contents are visible), so the event-word comparison is still missing.

The `req+0x1a` flag is **identical (`02`) for GET_DESCRIPTOR and GET_CUR**, confirming
the e0395 flag fix cannot be the differential. The remaining difference is in the
**status stage after the data completion**, not the queued request flags or lengths.

## 2. ETL and result

ETW started before PC-Remote switch: 168,886,272 B. ffmpeg still fails
`Could not RenderStream to connect pins`; no frame. The full B20 ETL was not decoded in
this run.

## 3. Teardown

Battery pull was again required at the final MSC switch. The B17 sequence (MSC first,
then `rmmod`) was attempted, but the switch did not complete while the module still held
the UVC configuration; the debugger is unreachable in PC Remote, so `rmmod` could not be
run before the switch. The ring had dumped at STOP. This is a teardown-order limitation,
not a fix for the status stall.

## 4. Verdict

The early ring now sees both GET_DESCRIPTOR and GET_CUR, and they have the **same
request flags** and fast data completion. The only remaining divergence is the
**status OUT stage**, which stalls 5.01 s only for the class GET_CUR. Flag fixes and
standard-vs-class request-field differences are exhausted; the next probe must capture
the status NRDY/XferComplete/TRB transitions themselves (ring records at `0x29c`/`0x2a0`
or `do_control_status`), not just queue/class/completion.
