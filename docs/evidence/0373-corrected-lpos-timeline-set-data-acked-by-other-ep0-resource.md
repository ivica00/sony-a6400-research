# E0373 — Corrected `lpos` timeline: GET status DID complete; SET's OUT data was ACKed by a *different* ep0 resource while the bounce TRB stayed HWO=1

Date: 2026-11-11. Offline only, no camera. Corrects E0371/E0372's `lpos` reading:
inside `dwc3_process_event_entry`, `evt->lpos` is the **currently executing** event
(the `+4` update happens after the entry returns).

## 1. Exact event timeline (ring `ffdff000`, event = 4 bytes)

| offset | word | decode | what ran there |
|---|---|---|---|
| 0x290 | 0000c040 | XferComplete ep0 | **GET_CUR SETUP completion**; bridge CLASS hook runs (`CLASS entry`/`queue` logged at `lpos=290`), queues the 26-byte IN reply |
| 0x294 | 000010c2 | XferNotReady(DATA) ep1 | data-ready for the IN data stage |
| 0x298 | 0000c042 | XferComplete ep1 | **GET_CUR DATA completion** (thunk logged at `lpos=298`, `actual=26`, `next=3`) |
| 0x29c | 000020c0 | XferNotReady(STATUS) ep0 | `next==3` now, so this **is processed**: sets `ep0state=3` at `0x602b3454`, calls `do_control_status` |
| 0x2a0 | 0000c040 | XferComplete ep0 | **GET_CUR STATUS completion** (ep0state==3 path: dispose requests, restart, `out_start`) |
| 0x2a4 | 0000c040 | XferComplete ep0 | **SET_CUR SETUP completion**; bridge CLASS hook runs (`CLASS entry`/`queue` at `lpos=2a4`), queues the 26-byte OUT request (bounce TRB `HWO=1`) |
| 0x2a8 | 000020c2 | XferNotReady(STATUS) ep1 | host status-IN-ready for SET — **requires the 26-byte OUT data to have been ACKed** |
| 0x2ac | 0000c040 | XferComplete ep0 | current event when the SET completion thunk logged (`lpos=2ac`); giveback `actual=0` from the untouched bounce TRB |

Corrections to the earlier evidence:
- **GET_CUR's status stage was NOT dropped.** It was processed at `0x29c`
  (`next` had become 3 at the `0x298` data completion) and completed at `0x2a0`.
  The 5.0 s gap to SET_CUR (`141.42 s → 146.42 s`) is **host-side timing**, not a
  device status timeout.
- The `HWO=1` bounce TRB at SET proves the **host's OUT data was accepted by a
  different ep0 transfer resource**, not by the TRB we armed.

## 2. How can OUT data be ACKed while our data TRB stays HWO=1?

Two mechanically possible paths, both consistent with `0x2a8`:
- **A — DEPSTRTXFER failed / stale active resource:** `dwc3_ep0_start_trans` writes
  the TRB first (`0x602b2450..0x602b24c4`), then issues DEPCMD (type 6) at
  `0x602b24ec`. On failure it branches to `0x602b2534` **without** setting dep BUSY or
  `dwc+0x2dc`, leaving the written TRB at `HWO=1`, and returns negative.
  `__dwc3_gadget_ep0_queue 0x602b26ec` calls `__dwc3_ep0_do_control_data` at
  `0x602b281c` and then **ignores its return**: `0x602b2820..0x602b2828` only clears
  request flags and returns `r4 = 0`. A previously active ep0 transfer resource can
  therefore consume the 26 OUT bytes, and its `XferComplete ep0` is `0x2ac`.
- **B — a second ep0 request queued at `setup_req 0x602b9fd8`:** the delegated
  zero-length request could have accepted/consumed the transfer, leaving our bounce
  TRB unused.

`0x2a8` cannot distinguish A from B by itself; the fact that our queue wrapper logged
only **one** `EP0 queue` per CLASS entry means B, if it happened, used a different
ep0/ops object.

## 3. `setup_req` path re-check

- `0x602b9b64` is `blx r3` with `r3 = [r0+0x18]`, where `r0 = [r8]` is a
  **function-driver object** from the gadgetcore driver list. It is **not** the bridge
  CLASS hook directly: the bridge callback lives in the reference callback table and
  is called from inside that function driver's setup. Therefore our logged
  `CLASS exit result=0` is the **inner reference result**, not necessarily the value
  `setup_req` receives at `0x9b6c`.
- If that function-driver setup returns 0, execution does reach `0x9dac → 0x9f64 →
  0x9fd8`; the delegated queue call there is **unconditional** (no wLength/flag
  gate). It uses `r0 = [r4+4]` (ep0 object), `r1 = [r4+8]` (delegated request),
  `r3 = [[r0+8]+0x10]` (queue op).
- Whether `[r4+4]` is the same pointer as the CLASS hook's `ep0 = 0x68a1c9c0`, and
  what the function-driver setup returns, are not resolvable from the captured log —
  and explain the single-queue-line observation (nonzero driver return, or a
  different ep0/ops).

## 4. Consequence

- GET data+status worked at the wire level (0x298/0x29c/0x2a0).
- SET's data OUT was ACKed by **some** ep0 resource, but not by our bounce TRB; the
  `XferComplete ep0` at `0x2ac` was then dispatched by `ep0state=DATA` into
  `complete_data`, which has no TRB-ownership/HWO check and gave back our request with
  `actual=0`.
- The earlier "status NRDY dropped" conclusion is **superseded**: status was not
  dropped; the SET data-stage resource mismatch is the actual failure.
- Next offline checks before any fix/run:
  1. identify the function-driver setup at `0x602b9b64` (module/data object) and its
     exact return for GET/SET;
  2. determine whether the ep0 at `[r4+4]` is `0x68a1c9c0` (same ops shadow) or a
     different object;
  3. verify whether `dwc3_send_gadget_ep_cmd` in the SET data path returned negative
     (start_trans leaves HWO=1 and queue ignores it), e.g. by adding a read-only
     `dwc+0x2dc`/dep-flags/TRB snapshot immediately after queue in a future run.
