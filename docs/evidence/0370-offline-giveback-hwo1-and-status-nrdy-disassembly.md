# E0370 — Offline disassembly: how giveback ran with HWO=1, why GET's Status NRDY was dropped, and gadgetcore's setup/queue behavior

Date: 2026-11-11. **Offline only; no camera access.** vmlinux SHA `12eeec82…`
(`file_off = VA − 0x60108000`), kallsyms `a6400-kallsyms-checked.json`.

## 1. Every `bl dwc3_gadget_giveback (0x602affb8)` call site in vmlinux

A full BL-encoding scan finds **7** call sites:

| # | call site | caller | status passed (r2) / role |
|---|---|---|---|
| 1 | `0x602b04bc` | `dwc3_remove_requests` | `mvn r2,#0x6b` = −107/ESHUTDOWN; request removal |
| 2 | `0x602b04dc` | `dwc3_remove_requests` | same; second list pass |
| 3 | `0x602b05e4` | `dwc3_gadget_ep_dequeue` | `mvn r2,#0x67` = −103/ECONNRESET; dequeue |
| 4 | `0x602b0ee4` | `dwc3_endpoint_transfer_complete.clone.12` | `[fp,-0x30]` (0 or −0x78); non-EP0 request completion |
| 5 | `0x602b2be8` | `dwc3_ep0_stall_and_restart` | `mvn r2,#0x67`; EP0 stall/restart |
| 6 | `0x602b3344` | `dwc3_ep0_interrupt` (complete-data branch) | **`r2 = sb` = event status (0 on success)** |
| 7 | `0x602b3364` | `dwc3_ep0_interrupt` (ep0state==3 path) | r2 not set (caller value) |

Run B11's SET completion (`status=0`) matches **#6** (`0x602b3344`, r2=0 from the event).

## 2. How SET_CUR reached `0x602b3344` with `HWO=1`

`dwc3_ep0_interrupt 0x602b2c68` event decode:
```
602b2c78 ldrb r2,[r1,#1] ; 602b2c80 ldrb r3,[r1]
602b2c84 and  r2,r2,#3 ; lsl #2 ; orr r2,r2,r3,lsr#6
602b2c90 cmp  r2,#1 ; beq 0x602b2ca4      ; XFERCOMPLETE
602b2c98 cmp  r2,#3 ; bne exit ; b 0x602b3390 ; XFERNOTREADY
```
XFERCOMPLETE (`0x2ca4`) takes the **event's** endpoint, clears that dep's BUSY and
`setup_packet_pending`, then dispatches **only on `dwc->ep0state` (`dwc+0x2e0`)**:
```
602b2cd0 ldr r3,[r0,#0x2e0]
602b2cd4 cmp r3,#2 ; beq 0x602b30a8     ; EP0_DATA_PHASE -> complete_data
602b2cdc cmp r3,#3 ; beq 0x602b334c     ; STATUS -> dispose eps0 requests + restart
602b2cdd cmp r3,#1 ; bne 0x602b337c     ; SETUP -> setup completion
```
`0x602b30a8` (complete-data) always uses **eps0** (`ldr r3,[r0,#0xd0]`), sets
`dwc->ep0_next_event=3` at **`0x602b30c0`**, walks `dep->request_list`
(`0x602b30c8`), reads the **current** TRB via `[dwc+4]` (`0x602b30e8`), computes
TRBSTS (`size>>28`, special-cased `==2` at `0x602b3108`) but **never tests HWO**
(`ctrl & 1`), computes `transferred = min(len, …)`, and finally calls giveback at
`0x602b3344` with the event status.

Therefore the Run B11 SET observation is explained by **event/state mismatch**, not by a
missing hardware write:
- SET_CUR was queued (`state=0x8b`, `next=1`) and its data TRB armed at
  `[dwc+4] = ffdfd000` (`bpl=08a26000`, `size=0x40`, `ctrl=0x0c53`, **HWO=1**).
- 0.96 ms later a **XFERCOMPLETE for the current ep0state=DATA(2)** was dispatched into
  complete-data even though the armed bounce TRB still had HWO=1 (hardware had not
  touched it; `bounce0/1=0`). complete-data used the current TRB and the queued SET
  request, computed 0 bytes, and gave back with status 0.
- The stale completion is most consistent with a **delayed completion of the setup
  stage / previous control transfer** arriving after the class hook armed the data TRB
  (the interrupt dispatch trusts `ep0state`, not the event's transfer identity or TRB
  ownership). The event byte itself must be logged (GEVNT) to name it exactly.

**No slot confusion:** `[dwc+4]` is the single coherent `ep0_trb` pointer that
`start_trans` writes (`0x602b2450 ldr r1,[r5,#4]`); complete-data reads the same
pointer. The TRB is not consumable while HWO=1, so any processed completion with
HWO=1 is by definition not a completion of that TRB.

## 3. Why GET_CUR's Status NRDY never started the status TRB

`XferNotReady` (`event code 3`, branch `0x602b3390`):
```
602b339c ldrb r6,[r1,#1] ; ubfx r6,r6,#4,#4   ; NRDY subtype
cmp #1 -> 0x602b33bc   (DATA)
cmp #2 -> 0x602b3448   (STATUS)
```
STATUS path:
```
602b3448 ldr r3,[r0,#0x2dc] ; cmp r3,#3 ; bne exit   ; only if next_event==3
602b3454 str r3,[r0,#0x2e0]                          ; ep0state = STATUS(3)
602b3458 ldrb r3,[r0,#0x2d8] ; and #0x20 (delayed) ; beq 0x602b34a4
0x602b34a4: dep = dwc->eps[(event>>1)&0x1f]; bl 0x602b253c (do_control_status)
```
If NRDY(STATUS) is delivered while `next != 3`, it is **dropped at `0x602b3450`** and
not re-generated. For GET, data XferComplete sets `next=3` at `0x602b30c0`; if the
status NRDY on eps0 was already queued/processed **earlier in the same IRQ batch**
(eps0 event ordered before the eps1 data-complete event) it was dropped while `next`
was still 1 → host then waits 5 s and times out. This is the best-supported
explanation for `actual=26` + dropped status; alternatively `do_control_status` ran
and `start_trans` failed (its return is ignored, `0x602b25b4 warn_slowpath_null`), but
that path would have set ep0state=3 (STOP would then show ep0state 3, not 2). STOP
`state=0x99` (setup_packet_pending set, ep0state=2) is consistent with the drop/retry
scenario.

## 4. usb_gadgetcore setup dispatcher before/after the CLASS hook

- UDC → `g_setup 0x602b8328`: it resolves the gadget driver
  (`bl 0x6029b1a0`), checks driver state bit `[+0x68]>>2`, then calls
  **`setup_req 0x602b94a4`** and returns its value directly.
- `setup_req 0x602b94a4` decodes `bRequest/bRequestType`, runs the standard
  SET_CONFIGURATION/SET_INTERFACE/GET_DESCRIPTOR handlers, and for class/vendor
  requests loops over the registered class drivers:
  `[r8+0xc]` = count, `r5` = index, class callback `[r0+0x18]` at **`0x602b9b64`**
  (return 0 → `0x602b9dac`, 1 → `0x602b9db8`).
- A callee scan of the whole `setup_req` body finds **no** call to
  `dwc3_ep0_start_trans`, `__dwc3_gadget_ep0_queue`, `dwc3_ep0_queue`,
  `dwc3_ep0_complete_data` or `ep0_complete` — i.e. **gadgetcore does not queue or
  manipulate ep0 after the class handler returns**. The class hook's own
  `ep0->ops->queue` (our bridge) is the only EP0 queue; there is no second queue and
  no loop that would queue twice for the interface (the loop is over class drivers,
  and the matching callback returns once per matching request).

## 5. Conclusions / next offline step

1. The OUT data stage fails because a **stale/foreign XFERCOMPLETE is dispatched by
   `ep0state` into complete-data**, with no check of event endpoint/direction, TRB
   ownership/HWO, or TRB completion status before giveback. `HWO=1` in the captured
   TRB is the proof.
2. The GET status stage fails because **NRDY(STATUS) can be dropped while
   `next_event!=3`** (event ordering across eps1 data completion vs eps0 status).
3. Gadgetcore queues nothing itself; the fix/guard must live in the EP0 event/queue
   path, not in a second setup handler.
4. Next build/run should be a **read-only event-ring probe** that records the raw
   GEVNT bytes (`byte0`/`byte1`, endpoint/type/subtype/status) for each EP0 event and
   the surrounding `ep0state`/`next`/TRB HWO, so the stale XFERCOMPLETE can be named
   and the NRDY ordering confirmed — before any staging change or status kick.
