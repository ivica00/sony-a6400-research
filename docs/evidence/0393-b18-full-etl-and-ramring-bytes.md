# E0393 — B18 full-enumeration ETL + RAM-ring bytes: GET_CUR status stalls 5.011 s, SET_CUR canceled, then XACT_ERROR retries; final MSC hang because rmmod was not run before the switch

Date: 2026-11-12. Offline analysis of B18 files.

## 1. Exact B18 RR 0..8 lines

```
RAMRING n=9 dropped=0 start=1 class=2 get=1 set=1 queue=2 complete=2
RR 0 h=0 t=120.879457001 ep=00000000 req=00000001 bm=00 rq=00 v=0000 i=0000 l=0000 lpos=0 cnt=0 ev=00000000 st=00 nx=0 fl=00 ctl=00000000 sz=00000000 act=0 sts=0 b0=00000000 b1=00000000 bo0=00000000 bo1=00000000 res=1756020092
RR 1 h=1 t=128.120845501 ep=68a1c9c0 req=00000000 bm=a1 rq=81 v=0100 i=0002 l=001a lpos=290 cnt=4 ev=00000000 st=01 nx=2 fl=8d ctl=00000000 sz=00000000 act=0 sts=0 b0=00000000 b1=00000000 bo0=00000000 bo1=00000000 res=0
RR 2 h=2 t=128.120900501 ep=68a1c9c0 req=69567720 bm=00 rq=00 v=0000 i=0000 l=0000 lpos=290 cnt=4 ev=00000000 st=01 nx=2 fl=8d ctl=00000000 sz=00000000 act=0 sts=0 b0=60157a00 b1=601396ac bo0=00000000 bo1=00000000 res=0
RR 3 h=4 t=128.120960501 ep=68a1c9c0 req=00000000 bm=a1 rq=81 v=0100 i=0002 l=001a lpos=290 cnt=4 ev=00000000 st=02 nx=1 fl=8d ctl=00000000 sz=00000000 act=0 sts=0 b0=00000000 b1=00000000 bo0=00000000 bo1=00000000 res=0
RR 4 h=3 t=128.121791501 ep=68a1c9c0 req=69567720 bm=00 rq=00 v=0000 i=0000 l=0000 lpos=294 cnt=4 ev=00000000 st=02 nx=3 fl=8d ctl=00000000 sz=00000000 act=26 sts=0 b0=60157a00 b1=601396ac bo0=00000000 bo1=00000000 res=0
RR 5 h=1 t=133.131973001 ep=68a1c9c0 req=00000000 bm=21 rq=01 v=0100 i=0002 l=001a lpos=2a0 cnt=c ev=00000000 st=01 nx=2 fl=89 ctl=00000000 sz=00000000 act=0 sts=0 b0=00000000 b1=00000000 bo0=00000000 bo1=00000000 res=0
RR 6 h=2 t=133.131989501 ep=68a1c9c0 req=69567720 bm=00 rq=00 v=0000 i=0000 l=0000 lpos=2a0 cnt=c ev=00000000 st=01 nx=2 fl=89 ctl=00000000 sz=00000000 act=0 sts=0 b0=60157a00 b1=601396ac bo0=00000000 bo1=00000000 res=0
RR 7 h=4 t=133.132004001 ep=68a1c9c0 req=00000000 bm=21 rq=01 v=0100 i=0002 l=001a lpos=2a0 cnt=c ev=00000000 st=02 nx=1 fl=8b ctl=00000000 sz=00000000 act=0 sts=0 b0=00000000 b1=00000000 bo0=00000000 bo1=00000000 res=0
RR 8 h=3 t=133.132030001 ep=68a1c9c0 req=69567720 bm=00 rq=00 v=0000 i=0000 l=0000 lpos=2a8 cnt=4 ev=00000000 st=02 nx=3 fl=89 ctl=00000000 sz=00000000 act=0 sts=0 b0=60157a00 b1=601396ac bo0=00000000 bo1=00000000 res=0
```

The ring’s `ev`, `trb_ctl`, `trb_sz`, bounce and payload fields are **zero/invalid** because the ring recorded at the hook points before the TRB/event/buf contents were populated (and `req->buf` first words read as kernel addresses `60157a00/601396ac`, not UVC payload). The authoritative data in this ring is the timestamps, setup fields, `lpos/cnt`, `ep0state/next/fl`, and `actual/status`:
- GET data completes at **128.121791**, `actual=26`, `lpos=0x294`, state 2 next 3.
- SET class starts at **133.131973** = **5.011128 s later**, completion at 133.132030 `actual=0`.

## 2. Full-enumeration B18 ETL (143 MB; XML 1.36 GB; UCX control URBs)

Sony UVC device (first `0x5973893B1398`, then re-enumerated `0x597385472D38`):

| t_rel (s) | dur | device | setup | result |
|---|---|---|---|---|
| 23.879812 | 3.7 ms | …3B1398 | `80 06 0100 0000 0040` GET_DESCRIPTOR device 64 | SUCCESS |
| 23.969941 | 3.6 ms | …3B1398 | `80 06 0100 0000 0012` | SUCCESS |
| 24.004137 | 3.3 ms | …3B1398 | `80 06 0300 0000 00FF` string | SUCCESS |
| 27.893929 | 3.8 ms | …472D38 | `80 06 0100 0000 0040` | SUCCESS |
| 27.943103 | 3.7 ms | …472D38 | `80 06 0100 0000 0012` | SUCCESS |
| 27.968787 | 8.0 ms | …472D38 | `80 06 0302 0409 0014` | SUCCESS |
| 28.010438 | 3.3 ms | …472D38 | `80 06 0302 0409 0004` | SUCCESS |
| 28.022065 | 3.7 ms | …472D38 | `80 00 0000 0000 0002` GET_STATUS | SUCCESS |
| **35.200491** | **5.011510 s** | …472D38 | **`A1 81 0100 0002 001A` GET_CUR** | **SUCCESS** (0x0) |
| **40.212017** | **5.004151 s** | …472D38 | **`21 01 0100 0002 001A` SET_CUR** | **0xC0010000 CANCELED** |
| 45.216503 | 2.698 ms | …472D38 | `A1 81 0100 0002 001A` GET retry | **0xC0000011 XACT_ERROR** |
| 45.419116 | 3.102 ms | …472D38 | GET retry | XACT_ERROR |
| 45.422466 | 2.747 ms | …472D38 | GET retry | XACT_ERROR |

- The **initial 26-byte GET_CUR is the one that takes 5.011 s**, exactly as in B14; SET_CUR is then submitted and canceled after another 5.004 s; only afterwards do the fast XACT_ERROR retries occur.
- `wLength=0x1A` for GET and SET; no different length/ZLP request is present.
- No class/interface request on PTP interface 0 appears in the control-transfer list; no colliding EP0 control transfer is visible between GET and SET.
- SET_CONFIGURATION/SET_INTERFACE were not in the setup-bearing control extraction; they are UCX `SELECT_*` URBs and need a separate select extract. No second control transfer on EP0 occurred between GET and SET in this capture.

Thus the initial-enumeration wedge is the **GET_CUR status stage**: device data completes in ~1 ms (ring), host URB completes only at 5.011 s, then SET_CUR is canceled, then EP0 is wedged (XACT_ERROR retries).

## 3. STOP / final MSC switch

The RAM ring was dumped at **134.295 s** (first STOP after the host/ffmpeg session). The final MSC switch was attempted **without running `rmmod` first** because the debugger is not reachable while the camera is in PC Remote; the module was still loaded and the UVC descriptors were still active, so the switch hung and required a battery pull. This is a procedure difference from B17, where MSC was reached first and `rmmod` then restored descriptors. It is not a new module regression; the clean teardown order (stop daemon → `rmmod`/restore descriptors → MSC) was not available before the switch in B18.

No camera run was performed for E0393. The full B18 ETL is retained; the 1.36 GB XML and extracts are under `artifacts/analysis/e0393-b18-etl/`.
