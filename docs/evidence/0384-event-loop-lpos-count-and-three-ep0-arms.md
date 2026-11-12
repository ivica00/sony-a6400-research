# E0384 — Event-loop lpos/count semantics and the three `ep0out XferComplete` words before `SET pre`

Date: 2026-11-12. Offline (`vmlinux` 12eeec82, file_off=VA-0x60108000; B12 e0372
log). No camera, no build.

## 0. Correction after full replay (authoritative)

The batch bands in the first draft were one event late because `evt->count` is the full
snapshot and the printed `lpos` is the current event with one already-processed event
behind it. Correct bands:
- GET complete `lpos=0x298 cnt=0xc` ? batch **[0x294 NRDY DATA ep1, 0x298 XC ep1
  (current), 0x29c NRDY STATUS ep0]**; `0x2a0` is NOT in this batch (stale other-endpoint
  word, later overwritten by the status XC).
- SET pre `lpos=0x2a4 cnt=0xc` ? batch **[0x2a0 XC ep0 status, 0x2a4 XC ep0 SETUP
  (current), 0x2a8 NRDY STATUS ep1]**; the next invocation is `lpos=0x2ac cnt=8`
  ([0x2ac,0x2b0]).
- Therefore there are **not three `0000c040` before SET pre**: `0x2ac` is generated
  during the SET_CUR setup handler (after the setup receipt) and consumed in the next
  invocation.
- `0x602b3408` is NOT a `dwc3_ep0_start_trans` caller (it is a
  `dwc3_send_gadget_ep_cmd` Update-Transfer call). BL/BLX scan finds exactly **five**
  start_trans call sites: `0x25a4`, `0x26c8`, `0x2b68`, `0x31d8`, `0x3314`.
- `0x29c` entry: `ep0state=2` (it is set to 3 at 0x3454 inside the handler), `next=3`,
  `fl=0x8d`, `dep0->flags=1`; `do_control_status` is called and arms the correct
  STATUS3 TRB.
- Chronology: 0x2a0 = status XC (status path gives back eps[0] and calls out_start),
  0x2a4 = SETUP XC (current, class hook runs), 0x2a8 = NRDY STATUS ep1 (next was reset
  to 1 by the arm; dropped at 0x3448/0x3450), 0x2ac = a **duplicate ep0 XferComplete**
  generated during the SET setup handler and consumed in the next invocation while the
  bounce TRB remains HWO=1; complete_data lacks ownership validation and gives back the
  SET request with actual=0.
- Remaining contradiction: the controller emitted a second ep0 XferComplete for a
  control-phase transfer already reported, while the data TRB was never completed. The
  event format carries no TRB pointer and the single `ep0_trb` is rewritten between
  phases, so static analysis cannot say which fetch duplicated (status 0x0c43 vs setup
  0x0c23) or why. This is the remaining blocker; do not build a fix past it.

## 1. `dwc3_thread_interrupt` lpos/count semantics

`dwc3_thread_interrupt 0x602b1378..0x191b` (event processing is inlined here):
```
13ac ldr r3,[dwc+0xcc]        ; ev_buffs[] array
13b0 ldr r2,[r3,r7,lsl#2]     ; ev = ev_buffs[i]
13b4 ldr r3,[dwc+0x2b4]       ; regs
13b8 ldr r1,[r3,r8]           ; GEVNTCOUNT (r8=0x30c+0x10*i)
13c0 movw r3,#0xfffc ; 13c4 and r3,r1,r3
13c8 cmp r3,#0 ; beq next buffer
13d0 str r3,[ev+0xc]          ; ev->count = FULL batch byte count
13d4..13dc set ev->flags busy
13e4 ldr r5,[ev_buffs+i]
13e8 ldr r3,[ev+0x10] ; 13ec ldr sb,[ev+0xc]   ; sb = count
...
13fc ldr r2,[ev]              ; buf
1400 ldr r3,[ev+8]            ; lpos (current event offset)
1404 ldr r2,[buf+r3]          ; event word
...
1444 bl dwc3_ep0_interrupt    ; entry handler (callback logs here)
...
1864 ldr r3,[r5,#8]           ; lpos
1868 sub sb,sb,#4             ; remaining count -= 4 per event
186c add r3,r3,#4             ; lpos += 4
1870..1878 mask/store lpos
1898 mov r3,#4 ; 189c str r3,[regs+r8]  ; ack 4 bytes to GEVNTCOUNT
18a0 cmp sb,#0 ; bgt 13fc      ; loop while events remain
18ac str r3*0,[ev+0xc]         ; clear count at batch end
18b0.. clear busy flag
```
Therefore:
- `ev->count` in memory is the **full batch byte count** and is not decremented
  during the batch; the loop keeps a separate `sb` remaining count and subtracts 4 per
  event.
- `ev->lpos` is the **currently executing event** during the callback; it is
  incremented by 4 only **after** the entry handler returns.
- `cnt=0xc` = 3 events from the current `lpos`.

B12 batches:
- GET complete: current `lpos=0x298`, batch = `0x298` (`0xc042` data XC),
  `0x29c` (`0x20c0` NRDY status ep0), `0x2a0` (at that instant `0x0000a046` — a
  different endpoint's XferComplete, **not** `0xc040`).
- SET pre: current `lpos=0x2a4`, batch = `0x2a4` (`0xc040`), `0x2a8`
  (`0x20c2` NRDY status ep1), `0x2ac` (`0xc040`); `0x2b0` was `0x10c4` and
  changed to `0x10c0` during SET queue.
So the earlier claim that `0x2a0=0xc040` was already in the GET batch was a window
misread: the status XferComplete overwrote the stale `0x2a0` **after** `0x29c`
processing. `0x2a0` (status XC) and `0x2a4` (setup XC) are in separate batches.

## 2. `dwc3_ep0_start_trans 0x602b2424` call sites that can arm dep0

| call site | caller | TRB written (single `ep0_trb [dwc+4]`) | when |
|---|---|---|---|
| `0x602b25a4` | `__dwc3_ep0_do_control_status` | ctrl `0x30/0x40` (STATUS2/3), len 0 (odd dep) / maxpacket (even dep), buf `ctrl_req [dwc+0x10]` | 0x29c NRDY STATUS → arms status OUT |
| `0x602b26c8` | `__dwc3_ep0_do_control_data` | data ctrl, len req->length, buf request DMA (bounce for short OUT) | class/most setup data phase; also called from `__dwc3_gadget_ep0_queue` |
| `0x602b2b68` | `dwc3_ep0_out_start` | setup ctrl `0x20`, len maxpacket, buf `ctrl_req` | after status completion 0x334c/0x3374 and stall/restart |
| `0x602b31d8` | `dwc3_ep0_complete_data` OUT/status branch | ctrl `0x50`, buf `ctrl_req` | inside complete-data handling of an ep0 completion |
| `0x602b3314` | `dwc3_ep0_complete_data` (second branch) | ctrl `0x50`, buf `ctrl_req` | same |
| `0x602b3408` | NRDY(DATA) handler (0x3390 path) | DEPCMD type 0x108 / transfer-resource setup, not a new TRB | NRDY data mismatch |

Because there is one reused `ep0_trb`, three `XferComplete ep0` events mean **three
separate arm/completion instances**:
- `0x2a0` = status XC from the `0x29c` arm (`do_control_status`);
- `0x2a4` = setup XC from `out_start` after the status-complete path;
- `0x2ac` = a third ep0out XC whose arm is before `SET pre` (class data arm cannot be
  it — the class queue runs after SET pre). Candidates are the `0x31d8/0x3314`
  complete-data re-arm paths, an `out_start`/stall-restart triggered by the host abort
  (Stop Endpoint/Set TR Dequeue at ~5.01 s), or a back-to-back setup/status arm. The
  exact arm for `0x2ac` is **not yet assigned**; it cannot be the bounce data TRB
  because that arm happens at `SET queue` and the TRB is still HWO=1 at completion.

`0x2a8=0x20c2` is NRDY STATUS ep1 (SET's status endpoint) and is a separate event from
the three ep0 XCs; it cannot complete the ep0 data request.

## 3. GET status at `0x29c`

When the batch reaches `0x29c`:
- event decode: XFERNOTREADY, ep0, subtype STATUS;
- `next [dwc+0x2dc] == 3` (set by data complete at 0x30c0);
- `ep0state [dwc+0x2e0] = 3` at `0x3454`;
- `fl [dwc+0x2d8] = 0x8d` (delayed_status bit5 clear);
- `dep0->flags = 0x1` (BUSY clear);
- `do_control_status(dwc, eps[0])` is called at `0x34b0`, arms the correct OUT status
  TRB (STATUS3 `0x0c43`, len maxpacket 64, `ctrl_req`), DEPCMD type 6. No warning.

So the GET status software path is correct; the host still timed out and only completed
the URB via its Stop Endpoint/Set TR Dequeue path at ~5.01 s (E0381/E0382). The
unresolved part is host-side and the origin of the extra `0x2ac` ep0 completion, not the
status-arm geometry.

## 4. Remaining contradiction

The third `0x2ac = 0000c040` before `SET pre` requires a third dep0 arm that is not yet
identified in the call-site chronology. The candidate paths (`0x31d8/0x3314` inside
complete-data, or out_start/stall-restart after the host abort) must be matched by a
timestamped trace; the class data arm (`0x26c8`) is excluded because it runs after
`SET pre`. No fix should be built on the stale/ownership hypothesis until this arm is
identified.
