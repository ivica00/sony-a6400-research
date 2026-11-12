# E0371 — Run B12: GEVNT ring trace proves a stale pending `XferComplete(ep0)` caused SET's HWO=1 giveback; setup_req return 0 double-queues a delegated zero-length ep0 request

Date: 2026-11-11. **Offline disassembly + user-authorized Run B12-probe** (module
`a07af4ef…`, read-only GEVNT ring dump; daemon `99047575…`). Clean teardown, native
054C:0CAA/MSC without a battery pull. ETL 486,924,288 B kept.

## Step 1 — `setup_req` class-callback return semantics and the double queue

`g_setup 0x602b8328` resolves the gadget driver and calls **`setup_req 0x602b94a4`**,
returning its value directly. `setup_req` decodes the request, handles
CONFIG/INTERFACE/DESCRIPTOR, and for class requests loops registered class drivers
(`[r8+0xc]` count, callback `[r0+0x18]` at **`0x602b9b64`**).

Return handling at `0x602b9b6c..0x602b9b8c`:
- **`r0 == 0` → `0x602b9dac`**: gadgetcore treats the class as handled and at
  **`0x602b9f64..0x602b9fd8` builds a delegated request** on `[gadgetcore+8]`
  (length = 0, `complete` = literal, `[+0x1a]` flag bit1), then calls
  **`ep0->ops->queue(ep0, req)`** at **`0x602b9fd8`** — i.e. **gadgetcore queues its
  own extra zero-length EP0 request after our class hook already queued its 26-byte
  request.** Return path goes through `0x602b9fe0`.
- **`r0 == 1` → `0x602b9db8` → `0x602b9ba448`** (`mvn r6,#0x15` → **−22/EINVAL**),
  loop exit, error return.
- any other value → next class driver; after the loop → −22.

So `0` does **not** mean "handled, stop and return 0"; it means "handled, and
gadgetcore will queue a delegated zero-length request". The reference
`core_cb_class` returns **0** on successful GET/SET (`0x191c moveq r4,#0`;
`0x1a64 mov r0,r4`) and our bridge `class_cb` returns that value → **double queue on
ep0** is structural in this path.

## Step 2 — GEVNT ring trace (Run B12-probe)

Read-only dump fields: `dwc+0xcc` = `ev_buffs[]` pointer array, `dwc+0x2c8` = number of
buffers; `struct dwc3_event_buffer` `{+0 buf, +4 length, +8 lpos, +0xc count, +0x10 flags}`
(from `dwc3_event_buffers_setup 0x602ae5d8`, `dwc3_thread_interrupt 0x602b1378`).
Live: `n=1 eb=68a124b0 buf=ffdff000 len=0x1000`.

Event word decode: `type=(w>>6)&0xf` (1=XferComplete, 3=XferNotReady),
`epnum=(w>>1)&0x1f`, NRDY subtype = byte1 bits4–7 (1=DATA, 2=STATUS).

```
GET_CUR:
[141.421481] CLASS pre  lpos=290 cnt=4
   ... 000020c0 0000c040 | 0000c040 0000c042 | 000020c0 0000c040 | 000000c6 000010c8 | 0000c040 000010c4 | 000090c4 00008044
[141.422346] EP0 queue dir=IN  lpos=290
[141.424397] EP0 complete actual=26  lpos=298  (next event 0000c042 = XferComplete ep1)
SET_CUR:
[146.421652] CLASS pre  lpos=2a4
   0000c040 000000c6 000010c8 0000c040 000010c2 0000c042 000020c0 0000c040 |
   0000c040 000020c2 0000c040 000010c4
[146.422385] EP0 queue dir=OUT lpos=2a4   (next event = 0000c040 XferComplete ep0)
[146.424212] EP0 complete actual=0        lpos=2ac  (0000c040 consumed)
STOP: [282.528975] lpos=2b4 cnt=0
```

Key words: `0000c040` = XferComplete ep0; `0000c042` = XferComplete ep1;
`000020c0` = XferNotReady(STATUS) ep0; `000010c2` = XferNotReady(DATA) ep1.

Interpretation:
1. **GET_CUR:** before the data `XferComplete ep1` (`0xc042`) that gave
   `actual=26`, the ring already contains `XferNotReady(STATUS) ep0` (`0x20c0`)
   events. They were processed while `next!=3` and **dropped at `0x602b3450`**; the
   later data completion set `next=3` (`0x602b30c0`) but no new status NRDY arrived →
   host timeout. This confirms the E0370 hypothesis with live event order.
2. **SET_CUR:** at class-entry/queue the next pending event was **`XferComplete ep0`
   (`0xc040`)**; after the class hook armed the 26-byte OUT/bounce TRB, that pending
   completion was processed by `complete_data` (dispatch by `ep0state=DATA`), and
   `lpos` advanced `2a4 → 2ac` while the TRB still had `HWO=1`, `size=0x40` and zero
   bounce bytes. Hence `actual=0, status=0`: the giveback was for a **stale/foreign
   XferComplete ep0**, not for the armed bounce TRB.
3. The pending `XferComplete ep0` is consistent with **gadgetcore's delegated
   zero-length request queue** (return-0 path) plus the earlier dropped status/NRDY
   events; the same `ep0_trb` slot is reused for setup/data, and complete-data never
   checks event identity or HWO.

## Step 2b — How a SETUP can arrive after the GET timeout

`dwc3_ep0_out_start 0x602b2b40` re-arms the next SETUP with
`start_trans(dwc, 0, [dwc+0x10], ep0->maxpacket, 0x20)` — the setup TRB is written
into the **same `ep0_trb` `[dwc+4]`**, with `bpl = [dwc+0x10]` (ctrl_req buffer) and
ctrl `0x20` (SETUP). Callers: `dwc3_gadget_pullup/reset` (`0x602b1cf4`,
`0x602b239c`), `stall_and_restart 0x602b2b8c` (called from `0x602b2bf8` and the
interrupt ep0state==3 path `0x602b3374`), and the NRDY(DATA) handler
(`0x602b3390` → if event endpoint ≠ `ep0_expect_in`, issue DEPCMD and call
`stall_and_restart` at `0x602b343c`). That path gives back pending requests
(`-103`), sets `ep0state=1`, calls `out_start`, and therefore allows the next SETUP to
be received — exactly what happened when the host retried after the GET status
timeout (ring words `0x10c2`/`0x10c8` are NRDY(DATA) ep1 events, `0x20c0` the dropped
status NRDY, and `setup_packet_pending` is visible in STOP `0x99`).

## Conclusion / next

The failure is now a concrete chain, not a hypothesis:
1. class handler returns 0 → gadgetcore `setup_req` **queues an extra zero-length ep0
   request** (double queue);
2. that request's `XferComplete ep0` sits in the GEVNT ring;
3. after the next class queue arms a data TRB, the stale completion is dispatched by
   `ep0state=DATA` into `complete_data`, which lacks HWO/event-identity checks and
   gives back the new request with `actual=0`;
4. GET's STATUS NRDY is dropped because it is processed while `next!=3`.

The next module change should be designed around (1): either make the class hook
return a value that **prevents** gadgetcore's delegated queue (needs the exact UDC
return contract for 0/1/0x7fff, disassembled at `0x602b2f30..0x602b2f60`) or make the
bridge's own queue compatible with the delegated one; plus an event-identity guard is
not possible inside complete-data without kernel text changes. Run B13 should first
test the return-value change (read-only logging of `setup_req`/delegated queue cannot
be added without a hook; the class return path itself is the only controllable knob).
