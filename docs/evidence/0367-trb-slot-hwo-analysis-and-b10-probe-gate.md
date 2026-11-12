# E0367 — TRB paradox analysis: completion handler reads the same unvalidated TRB slot (no HWO check); GET data really was ACKed; B10-probe NOT run (module not strictly read-only / not Unicorn-verified for this build)

Date: 2026-11-11. **Offline only.** No camera run. Disassembly of the preserved a6400
vmlinux (`12eeec82…`, `file_off = VA − 0x60108000`), regions
`dwc3_ep0_interrupt`/complete-data (`0x602b2fb0..0x602b3344`) and
`dwc3_ep0_start_trans (0x602b2424)`.

## 1. Why `DEPEVT_XFERCOMPLETE` fired with `trb->size & 0xffffff == 64`

The data-completion path inside `dwc3_ep0_interrupt`:
```
602b30a8  ldr  r3, [r0, #0xd0]        ; eps[0] (OUT / data dep)
602b30b0  str  r3, [fp, #-0x40]
602b30b4  ubfx sl, sl, #1, #5          ; event endpoint number
602b30bc  mov  r3, #3
602b30c0  str  r3, [r0, #0x2dc]        ; dwc->ep0_next_event = 3 (STATUS)  <-- set here
602b30c8  ldr  r5, [r3, #0x24]!        ; dep->request_list head
602b30d8  ldrb r3, [r5, #0x50]         ; (NULL deref if the list is empty — the E0366 crash)
602b30e8  ldr  r2, [r0, #4]            ; TRB buffer pointer (same slot start_trans wrote)
602b30ec..0x3104  read trb[8..0xb]     ; TRB size / TRBSTS (bits 28..31)
602b3108  lsr  r2, r3, #0x1c ; cmp r2, #2 ; bne ...
...
602b31f0  (even dep / OUT) bounce branch
602b3144  (odd dep / IN)  transferred = min(len, ...), actual += transferred
```
- **`start_trans` and `complete_data` use the same scratch TRB pointer `[dwc+4]`**
  (`start_trans` at `0x602b2450: ldr r1,[r5,#4]`, then writes the 16-byte TRB; the
  completion path reads `[dwc+4]` at `0x602b30e8`). There is no `ep0_trb[0]` vs `[1]`
  index validation in this path — the same slot is programmed and read back.
- The handler **does inspect TRBSTS** (`size>>28 == 2` special branch at `0x602b3108`)
  but it **never checks HWO / the TRB ctrl bit0**. It computes
  `transferred = min(len, ...)` from the size field regardless of whether the
  controller has written back that TRB. If the completion event is processed with a
  stale TRB (HWO still 1, size untouched = 64), the arithmetic yields 0.
- That is the SET_CUR paradox: OUT 26 B is staged through the bounce branch
  (`len = roundup(26,64) = 64`, TRB to `dwc->ep0_bounce_addr`); the handler read a TRB
  whose remaining bytes were still 64 → `transferred=0` → `actual=0` with
  `status=0`, without any HWO/TRBSTS validation of the slot.
- For GET_CUR the same arithmetic gives `actual=26` because the IN TRB length was 26
  and its size field was written back as 0 (`remaining=0`): the controller **did
  transmit all 26 bytes and the host ACKed them in ~1.02 ms** (real DATA-stage
  success).

## 2. GET_CUR: why the status stage still did not complete

- The data-completion path sets `dwc->ep0_next_event = 3` at `0x602b30c0` — but the
  `XferNotReady(Status)` handler at `0x602b3448` ignores any status event unless
  `dwc+0x2dc == 3` (`cmp r3,#3; bne exit` at `0x602b3450`). If the controller raises
  `XferNotReady(Status)` while `next` is still 1 (i.e. before this completion handler
  runs), the event is dropped and is not re-generated; the host then waits in the
  data/status transition and times out at 5 s. This ordering race is the best fit for
  GET (data 1 ms, host 5 s timeout).
- `STOP-pre` in Run B9 was `state=0x99 next=3 event=2`: bit4 (`0x10`,
  **setup_packet_pending**) is set, and `ep0state` is still 2 (DATA). That means after
  the timeout the host sent a new SETUP packet (setup_packet_pending=1) and the EP0
  state machine never advanced to STATUS(3); the host was still in the data phase, so a
  status kick could not have helped.

## 3. What module `1765d4cf…` logs (and why it was NOT run)

`artifacts/native/uvc-transport-e0369-trbprobe-fwd/...ko` (82,420 B, SHA
`1765d4cf…`, audit 117/8/0, no status kick) logs:
- `CLASS ep0-pre`/`CLASS ep0-post`: `desc`, `dep_flags`, `ops`, `queue`, `dwc`,
  `state` (dwc+0x2d8), `next` (0x2dc), `event` (0x2e0), `eps0/eps1` flags and list state;
- `EP0 queue` entry: `dir`, `req`, `buf`, `dma`, `len`, `mapped`; exit: `ret`, `dma`,
  `state`, `next`, `event`; plus `EP0 trb` (`dma`, `size`, `ctrl`, `bounce`) and
  `EP0 ops wrapped/restored`;
- `EP0 complete`: `status` (+0x2c), `actual` (+0x30), `state`, `next`, `event`,
  `dep0/dep1` flags, plus the same TRB fields (`dma/size/ctrl/bounce/buf0`).

**It is not "strictly read-only":** it swaps `ep0->ops` to a shadow table, replaces
`req->complete` with the logging thunk, and for OUT requests writes `req->dma`. It is
also **not Unicorn-verified for this exact build** (the verified object in E0366 was the
different kick build `694cb379`). The authorization condition for the B10-probe capture
is therefore **not met**, and no hardware run was performed.

## 4. Options before any run

1. **Truly read-only variant:** only `CLASS ep0-pre/post` + `STOP-pre` snapshots plus
   TRB/size/ctrl reads at those points (no `ep->ops` swap, no `req->complete` hook, no
   `req->dma` write). It cannot see queue/completion timing, but is safe by
   construction and can capture the `state=0x99`/TRB HWO state at STOP.
2. **Unicorn-verify `1765d4cf` exactly** (extend the E0366 exact-object harness to this
   build), then run the B10-probe capture as authorized.
3. The TRB HWO bit (ctrl bit0) and TRBSTS at completion are the missing runtime facts;
   either variant should log them to explain the stale-TRB completion and the
   status-NRDY ordering.
