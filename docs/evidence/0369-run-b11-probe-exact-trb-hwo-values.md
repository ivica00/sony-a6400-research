# E0369 — Run B11-probe: exact TRB capture; GET's TRB consumed (HWO 1→0, size 26→0), SET's TRB NEVER consumed (HWO stays 1, size 0x40, bounce zeros) — the "completion" was a misrouted/stale-TRB event

Date: 2026-11-11. **Physical, user-authorized Run B11-probe** after the fixed probe
module `fb2e294d…` passed the exact-object Unicorn harness (overall_pass=true, queue
wrapper IN/OUT + forwarding, no status kick). Clean teardown, native 054C:0CAA/MSC
without a battery pull. ETL 470,523,904 B kept.

## 1. Correcting the probe: `[dwc+4]` is `dma_alloc_coherent` virtual memory

Raw disassembly offsets (start_trans `0x602b2424`, complete-data):
- `[dwc+4]` = **`ep0_trb` CPU virtual pointer** (`dma_alloc_coherent` coherent window;
  live value `ffdfd000`, outside the old `0x5f…0x70` guard → old probe wrongly printed
  `trb=none`);
- `[dwc+0x14]` = **`ep0_trb_addr`** (DMA, passed as `param1`: `0x602b24d0 ldr r3,[r5,#0x14];
  0x602b24e4 str r3,[fp,#-0x24]` before `dwc3_send_gadget_ep_cmd`); live `089ff000`;
- `[dwc+8]` = **`ep0_bounce` virtual** (`0x602b3224 ldr r1,[r4,#8]` → memcpy source);
  live `ffdfc000`;
- `[dwc+0x18]` = **`ep0_bounce_addr` DMA** (`0x08a26000`; lowmem alias `0x68a26000`).

The fixed probe logs the raw fields unconditionally, reads the TRB via the coherent
virtual pointer (or `ep0_trb_addr + 0x60000000` alias) and logs the first two bounce
words. Module `fb2e294d…` = `artifacts/native/uvc-transport-e0370-trbprobe2/…ko`,
82,528 B, audit 117/8/0.

## 2. Exact live values

```
GET_CUR (IN):
[170.092695] queue  dir=IN  req=68a84440 buf=6894497c dma=00000000 len=26 mapped=0
[170.093031] queue  trb_v=ffdfd000 trb_a=089ff000 bounce_v=ffdfc000 bounce_a=08a26000
             bpl=0894497c bph=00000000 size=0000001a ctrl=00000c53 trbsts=0 rem=1a hwo=1 bounce0=0 bounce1=0
[170.094311] complete status=0 actual=26 state=8d next=3 event=2 dep0=dep1=1
[170.094561] complete trb_v=ffdfd000 trb_a=089ff000 … bpl=0894497c bph=0
             size=00000000 ctrl=00000c52 trbsts=0 rem=0 hwo=0 bounce0=0 bounce1=0

SET_CUR (OUT):
[175.095605] queue  dir=OUT req=68a84440 buf=6894497c dma=0894497c len=26 mapped=1
[175.095929] queue  trb_v=ffdfd000 trb_a=089ff000 bounce_v=ffdfc000 bounce_a=08a26000
             bpl=08a26000 bph=00000000 size=00000040 ctrl=00000c53 trbsts=0 rem=40 hwo=1 bounce0=0 bounce1=0
[175.097044] complete status=0 actual=0 state=89 next=3 event=2 dep0=dep1=1
[175.097286] complete trb_v=ffdfd000 trb_a=089ff000 … bpl=08a26000 bph=0
             size=00000040 ctrl=00000c53 trbsts=0 rem=40 hwo=1 bounce0=0 bounce1=0
```

Answers to the two questions:
1. **GET_CUR:** at completion `size=0` (TRBSTS=0, remaining 0), **`ctrl=0x0c52` → HWO=0**,
   `state=0x8d`, `next=3`, `event=2`; the controller consumed the TRB (26 bytes sent,
   host ACKed) — exactly matching `actual=26`.
2. **SET_CUR:** at completion **`ctrl & 1 == 1` (HWO still set)**, `size=0x40`
   (remaining 64), `bpl=0x08a26000` (bounce DMA), **bounce bytes both 0**. The TRB was
   **never consumed** (hardware still owns it); `dwc3_ep0_complete_data` does not check
   HWO, so it computed `transferred = 64 − 64 = 0` → `actual=0`, `status=0`. The ~1 ms
   "completion" is therefore a **stale-TRB/misrouted event**, not a real OUT data
   completion; the host's 26 SET_CUR bytes were never accepted, and the host then
   remained in the data phase (`STOP state=0x99` with `setup_packet_pending`, E0367).

This also proves the old guard, not the kernel, caused `trb=none`: `ep0_trb` lives at
`0xffdfd000` (coherent window), and its DMA address is `0x089ff000`.

## 3. Consequence

- The control-OUT data stage is not functioning: the data TRB stays HWO=1 while an
  event that reaches `giveback`/`complete_data` is processed against the stale TRB.
  The next target is the **event dispatch**: determine which interrupt event
  (`XferNotReady(DATA)` vs `XferComplete`) reaches complete_data with HWO=1 and why
  (composite/EP0 state, event byte subtype, or the `next_event=3` write at
  `0x602b30c0` executed for a non-completion event). Do this from the E0367/E0368
  disassembly (`0x602b3390..0x602b3344`) before any new module change.
- GET's DATA stage works; its status stage remains the E0367 ordering issue
  (`next!=3` when the status NRDY arrives, `0x602b3450`).
- No status kick (E0366 verdict stands).

## 4. Verification / state

Receipt clean (`stop_verified=1`, `teardown_verified=1`); camera ended healthy in MSC
(42 modules, no `usbg_video`, `/tmp_bt` baseline); full suite **1312 tests OK**; no host
flash/SD writes (read-only SD mount); ETL/receipts under
`artifacts/analysis/e0371-runb11probe/`.
