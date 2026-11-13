# E0471 — B25 Status-OUT forensics: host queued the whole control TD, camera armed the correct STATUS3/OUT TRB, the 5.000 s is the Windows control-transfer timeout

Date: 2026-11-13. **Strictly offline**, no camera/USB/module action; no source change.
Full analysis + tables: `artifacts/analysis/e0469-dwc3-status-forensics/report.md`
(tools `disasm_dwc3_ep0.py`, `etw_window.py`, `etw-window.jsonl` 157,992 events,
`etw-facts.json`). Inputs: B25 ETL `artifacts/analysis/e0466-runb25-ep0-observer/`
(`usb-capture.etl` sha `edf4925d…`, 3.29 GB XML), B25 ring/OBS (`preflight/`), retained
`live-vmlinux.bin` (`file_off = VA − 0x60108000`).

## Host (B25 ETL, all providers re-scanned, SlotId 8 / DCI 1)

- GET_CUR dispatch `09:27:20.975942` local (`A1 81 0100 0002 001A`, 26 B, class-interface
  URB), xHCI `ID41` at `.975946` **SlotId 8, DCI 1, BytesTotal 26** → the entire control
  TD (Setup + Data + Status TRBs) was queued **at dispatch**. No second submission, no
  event of any kind for slot 8 until the Stop Endpoint.
- `09:27:25.976359` **Stop Endpoint** + `Set TR Dequeue Pointer` (`+5.000417 s`), URB
  completes **SUCCESS 0x0, 26 B** at `.976666` (`+5.000724 s`) via the timeout/cancel
  path. SET_CUR: same up-front TD, Stop Endpoint at `+5.015035 s`, URB **CANCELED
  0xC0010000**. Retried GET_CUR then fails fast (`0xC0000011`, 2.733 ms).
- Host controller: AMD USB 3.10 eXtensible Host Controller 1.20 (Microsoft) xHCI.

## Camera (B25 OBS + RR + DWC3 disassembly)

- Data stage: host ACKs 26 B, request giveback `actual=26 status=0` at **+0.972 ms**;
  event ring consumes DATA XferComplete (slot 0x298) then a **single
  XferNotReady(STATUS, ep0)** (slot 0x29c) → the host attempted the Status OUT once
  before the camera was ready.
- OBS row1 (`≤ +16.388 ms`): `ep0s=3 next=1 st=9d f0=11 f1=1 lpos=2a0` — NRDY(STATUS)
  serviced: status TRB armed on **eps0 OUT** (ENABLED\|BUSY), `next=1` only after a
  successful `DEPCMD_STARTTRANSFER`; no BUSY-skip, no warning in dmesg.
- Then **5000.010 ms with no state change** (ep0state 3, eps0 BUSY, lpos frozen, no
  status XferComplete). Row2 at `+5016.398 ms` = `+15.7…16.0 ms` after the host
  Stop Endpoint: pending status TRB retired (bit4 clears), new SET_CUR processed as a
  3-stage data phase.
- Code (backport): status trb type = **STATUS3 (0x40)** for `three_stage_setup`, else
  STATUS2 (0x30); direction comes only from the `dep` argument (eps0 OUT for a read);
  OUT status len = maxpacket 64 on `ctrl_req`, ctrl `0xC43` (HWO\|LST\|IOC\|ISP_IMI);
  `ep0_expect_in` not read by the status arm. Same path as the stock reads, which work.

## Root cause and next step

**Root cause: a missed Status OUT handshake.** The host issued its single Status OUT
immediately after the DATA-IN, before the camera's threaded-IRQ path had armed the
status TRB; the DWC3 NAK'd it (the recorded NRDY(STATUS)). The driver then armed the
correct STATUS3/OUT/len-64/`ctrl_req`/HWO TRB, but no later Status OUT ever completed
(no bus completion, no further EP0 event for 5.000 s), so the control TD stayed pending
until the Windows 5.000 s control-transfer timeout aborted it via Stop Endpoint + Set TR
Dequeue. Descriptors/composite are **not** implicated; the DWC3 status programming is
correct. Remaining discriminator (ETL has no per-TRB/NAK trace; OBS bounds the arm to
≤16.388 ms): H1 = the host does not re-drive the NAKed Status stage; H2 = the armed TRB
never ACKs a later Status OUT.

**Proposed minimal fix (offline first):** pre-arm the status TRB at class data-stage
completion — set `dwc->ep0state=3` then call `__dwc3_ep0_do_control_status(dwc,
dwc->eps[0])` (`0x602b253c`) from the bridge's class-completion hook when
`ep0state==2 && next==3` for a 3-stage IN class request (corrected form of the E0366/B10
kick; later NRDY sees `next==1` and is ignored, BUSY guard prevents a double TRB).
Verify in Unicorn (arm-once, `ep0state=3` set before the call, status completion
dispatches to `0x334c`, no B10-style NULL deref), audit 117/8/0, full suite, **then**
request one supervised session under the usual safety rules. No camera action now; no
hardware run without explicit GO.
