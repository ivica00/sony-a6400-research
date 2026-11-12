# E0398 — Run B21: GET_CUR status still stalls 5.011 s; disconnect hook fires but the synchronous restore hangs; no status-stage capture yet

Date: 2026-11-12. Physical Run B21 with `e0398-status-disconnect`
`705fd1558b45089e3b25b02334d9db67a5815e094b21494d709afade0e8b5b65` (80,760 B,
audit 117/8/0). ETW before PC-Remote switch: 158,793,728 B. Battery pull required.

## 1. RAM ring: GET_DESCRIPTOR vs GET_CUR

Early ring captured standard descriptor queues (`lr=602b9fdc`, `flg=02`, lengths
4/20/10) and class GET/SET:

```
RR 23 h=2 t=115.870... lpos=214 cnt=4 st=01 nx=2 fl=8d act=4  len=4  flg=02 lr=602b9fdc
RR 24 h=3 t=115.901925 lpos=218 ... act=4  len=4  flg=02
RR 25 h=2 t=115.904949 lpos=224 ... act=4  len=20 flg=02 lr=602b9fdc
RR 26 h=3 t=115.905941 lpos=228 ... act=20 len=20 flg=02
RR 31 h=2 t=115.939976 lpos=254 ... act=20 len=4  flg=02 lr=602b9fdc
RR 32 h=3 t=115.940933 lpos=258 ... act=4  len=4  flg=02
RR 35 h=1 t=138.357581 bm=a1 rq=81 v=0100 i=0002 l=001a lpos=28c cnt=4 st=01 nx=2 fl=8d
RR 36 h=2 t=138.357610 req=68a84680 ... len=26 flg=02 lr=5f5644d0
RR 37 h=4 t=138.357637 bm=a1 rq=81 ... lpos=28c st=02 nx=1 fl=8d
RR 38 h=3 t=138.358552 req=68a84680 ... lpos=290 cnt=4 st=02 nx=3 fl=8d act=26 len=26 flg=02
RR 39 h=1 t=143.369746 bm=21 rq=01 ... lpos=29c cnt=c st=01 nx=2 fl=89
RR 40 h=2 t=143.369763 req=68a84680 ... len=26 flg=00 lr=5f564918
RR 41 h=4 t=143.369777 bm=21 rq=01 ... lpos=29c st=02 nx=1 fl=8b
RR 42 h=3 t=143.369802 req=68a84680 ... lpos=2a4 cnt=4 st=02 nx=3 fl=89 act=0 len=26 flg=00
```
- GET data completes at **138.358552** (`act=26`).
- SET_CUR starts at **143.369746** = **5.011194 s later**; completion `act=0`.
- GET_DESCRIPTOR and GET_CUR still share `flg=02`; the difference remains the **status
  OUT stage** alone.
- `ev`, `trb_ctl`, `trb_sz` are still zero; the ring reads did not become valid at these
  points. No status-stage hook entries were produced (`do_control_status`/`0x29c`/
  `0x2a0` are not instrumented), so this run does not yet capture the status timestamps.

## 2. Disconnect hook result

The hook fired on the host disconnect:
```
[191.890066] [a6400_uvc] DISCONNECT restore trigger started=0 in_flight=1
```
but there is **no `DISCONNECT restore done` line** and the camera did not switch; the
synchronous `a6400_uvc_restore_descriptors()` inside the disconnect callback hung
(with `in_flight=1`), so the user had to pull the battery. The hook is firing, but it
cannot run the full descriptor restore synchronously in the disconnect callback.

## 3. Verdict

- Status stall unchanged: GET data ~1 ms, SET_CUR 5.011 s later, `act=0`.
- Disconnect hook is the right trigger location, but the restore must be **deferred**
  (workqueue/tasklet) and must wait for `in_flight==0`; calling it synchronously from
  `disconnect_cb` hangs.
- The status-stage capture is still missing; the next probe must add a deferred
  disconnect restore and a proper status-stage sample (not just queue/class/complete).
- B21 ETL 158,793,728 B retained; full decode not completed in this run.
