# E0368 — Run B10-probe: exact module 1765d4cf verified in Unicorn, then one read-only capture; TRB raw pointer is DMA-space (probe logged `trb=none`)

Date: 2026-11-11. **Physical, user-authorized Run B10-probe** after the exact-object
Unicorn verification passed. Module `1765d4cf…` (read-only TRB probe, forwarding-fixed),
daemon `99047575…`, `--dmesg-sd --sd-log --sd-mount`. **Clean teardown, native
054C:0CAA/MSC without a battery pull, no crash.** ETL 480,854,016 B kept.

## Step 1 — Unicorn verification of the exact `1765d4cf` object (PASS)

Exact `callback-bridge.o` from `uvc-transport-e0369-trbprobe-fwd` (SHA
`9baf7e7c…`) loaded with 168 REL relocations into the E0366 harness, real
`dwc3_gadget_giveback 0x602affb8`, synthetic dwc/eps/req, shadow `ep->ops` with queue
stub, `g_req_complete_orig` = probe:
`artifacts/analysis/e0366-b10-verify/e0369-exact-unicorn.json` — **overall_pass=true**:
- direct thunk forward: no fault, original completion probe hit;
- `ep0->ops->queue` wrapper **IN**: wrapper return, `req->complete` replaced by the
  thunk, `dma` stays 0, giveback → thunk → original probe hit, no fault;
- `ep0->ops->queue` wrapper **OUT**: `dma = buf − 0x60000000` (`0x1302000`), forwarding
  hit, no fault;
- **no `__dwc3_ep0_do_control_status` call** (no status kick).

XferNotReady decode (from `lead-ep0_interrupt.disasm.txt`): `dwc3_ep0_interrupt` reads
`ldrb r6,[event+1]; ubfx r6,r6,#4,#4` at `0x602b339c`; **1 = XferNotReady(DATA)**
(branch `0x602b33bc`, which also sets `setup_packet_pending` bit4 at `0x602b3394`),
**2 = XferNotReady(STATUS)** (branch `0x602b3448`). The status path requires
`dwc+0x2dc==3` and then **sets `dwc->ep0state (dwc+0x2e0)=3` at `0x602b3454`**.

## Step 2 — Run B10-probe capture

Kernel lines for the run (`A6400K.LOG`):
```
[124.344993] CLASS entry rt=a1 req=81 val=0100 idx=0002 len=001a      (GET_CUR IN)
[124.345674] EP0 queue dir=IN  req=609d0b40 buf=60aee3fc dma=00000000 len=26 mapped=0
[124.345925] EP0 queue exit ret=0 dma=00aee3fc state=8d next=1 event=2
[124.346077] EP0 trb=none bounce=08a26000
[124.347084] EP0 complete ep=68a1c9c0 req=609d0b40 status=0 actual=26
             state=8d next=3 event=2 dep0=1 dep1=1
[129.359201] CLASS entry rt=21 req=01 val=0100 idx=0002 len=001a      (SET_CUR OUT)
[129.360040] EP0 queue dir=OUT req=609d0b40 buf=60aee3fc dma=00aee3fc len=26 mapped=1
[129.360208] EP0 queue exit ret=0 dma=00aee3fc state=8b next=1 event=2
[129.360364] EP0 trb=none bounce=08a26000
[129.361246] EP0 complete ep=68a1c9c0 req=609d0b40 status=0 actual=0
             state=89 next=3 event=2 dep0=1 dep1=1
[266.440615] [a6400_td] done phases=1ff failed=9 error=0 … reconnect=1
```

Answers with the captured data:
1. **GET_CUR:** `status=0 actual=26` (~1.2 ms), `state=0x8d` (three_stage_setup=1,
   ep0_bounced=0, ep0_expect_in=1), `next=3`, `event=2` (ep0state=DATA), dep0=dep1=1.
   `actual=26` with a 26-byte IN TRB means the TRB was written back with remaining 0
   (host ACKed the data). LIVE `size/ctrl/HWO` were **not captured** (see below).
2. **SET_CUR:** `status=0 actual=0` (~1.0 ms), `state=0x89` (three_stage_setup=1,
   **ep0_bounced=1**, ep0_expect_in=0), `next=3`, `event=2`, dep0=dep1=1;
   `bounce=08a26000`. `actual=0` means `transferred=0` from the TRB size
   (`roundup=64` remaining) — but the live `size/TRBSTS/ctrl/HWO` were **not captured**.
3. **Queue values:** both show `buf=60aee3fc`; GET `dma=00aee3fc` (mapped by UDC),
   SET `dma=00aee3fc` (mapped by our wrapper, `mapped=1`); `state` 0x8d/0x8b,
   `next=1`, `event=2` at exit.

**Probe limitation:** `EP0 trb=none` — the raw `[dwc+4]` value was rejected by the
virtual-pointer guard (`0x5f000000..0x70000000`); the valid `bounce=08a26000` shows the
same object fields are **DMA/physical-space addresses** (`0x08a…`), not kernel virtual
ones. The TRB ring must be read through the direct-map translation
(`virt = phys + 0x60000000`) and the raw `[dwc+4]` value logged regardless of the guard.
The run itself was clean (no crash); this is a probe bug, not a kernel fault.

## Next

1. Fix the probe: log the raw `[dwc+4]`, translate `phys+0x60000000`, then read
   `bpl/bph/size/ctrl` (TRBSTS=`size>>28`, HWO=`ctrl&1`) at queue-exit and completion;
   also log `dwc+8`, `dwc+0x18`, `dwc+0x1c` and the `ep0_trb[0]/[1]` slots.
2. Re-run one read-only capture; the HWO/TRBSTS values decide whether SET's
   `actual=0` is a stale-TRB completion (HWO still 1) or a genuine zero-progress
   completion (TRBSTS/remaining=64), and whether GET's status NRDY arrived while
   `next!=3`.
3. Only then touch the data/status staging (no status-kick from `req->complete`; the
   E0366 verdict stands).
