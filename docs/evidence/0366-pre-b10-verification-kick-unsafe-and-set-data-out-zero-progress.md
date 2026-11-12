# E0366 — Pre-Run-B10 verification FAILED safety: status-kick leaves ep0state=2 and NULL-derefs; B9's real blocker is the SET_CUR DATA-OUT bounce TRB (zero progress)

Date: 2026-11-11. **Offline only.** Run B10 was NOT executed. Two parallel verification
workstreams: exact thunk/status ABI + lock safety stepped in Unicorn
(`artifacts/analysis/e0366-b10-verify/e0366-thunk-*`), and `dwc+0x2d8` bitfield/status
direction + `actual=0` analysis (`e0366-dwc3-ep0-flags-and-status-direction.md`).

## 1. Register ABI + lock context (verified in vmlinux and Unicorn)

- `__dwc3_ep0_do_control_status 0x602b253c` ABI: **r0 = struct dwc3 \*dwc, r1 = struct
  dwc3_ep \*dep** (dep is the argument; internally only `dep->dwc` +0x48,
  `dep->number` +0x54 are used). The normal call site `0x602b34a4` builds
  `r1 = dwc->eps[event->endpoint_number]` (`ubfx r3,r3,#1,#5; add #0x34;
  ldr r1,[r0,r3,lsl#2]`) and calls with `r0 = dwc`.
- `dwc3_gadget_giveback 0x602affb8`: at `0x602b00c8..d4` it does
  `add r6,dwc,#0x70; bl 0x603c691c (rt_spin_unlock); bl 0x6012bee0 (__migrate_enable)`
  **before** `req->complete(ep,req)` at `0x602b00e4`, and re-locks afterwards
  (`bl 0x6012c0ac`, `bl 0x603c68f4`). So the completion callback runs with
  `dwc->lock` **released** (not a recursive-lock deadlock).
- Unicorn stepped the **exact compiled thunk** from
  `artifacts/native/uvc-transport-e0367-statuskick/callback-bridge.o` through the real
  `dwc3_gadget_giveback` bytes → thunk → `0x602b253c` → `0x602b2424` →
  `0x602b0220` with all 168 relocations applied. Scenarios: `kick-GET-IN`,
  `kick-SET-OUT`, `kick-busy-silent-noop`, `kick-depcmd-rejected-timeout`,
  `direct-thunk-forward-check`, `post-kick-xfer-not-ready-status-ignored`,
  `post-kick-status-xfercomplete-misrouted-NULL-deref`,
  `control-proper-status-state-no-fault` — **all pass** (JSON/log under
  `artifacts/analysis/e0366-b10-verify/`).

## 2. Why the status kick is UNSAFE as written

The kick does arm a status transfer (DEPCMD issued, dep BUSY set, `next=1`), but it
**leaves `dwc->ep0state = 2`**. On the next XferComplete(status) the real
`dwc3_ep0_interrupt` dispatches to `complete_data` with an **empty eps0 request list**,
then `ldrb r3,[r5,#0x50]` with `r5 = NULL` at **`0x602b30d8`** → unmapped read in IRQ
context. Unicorn reproduces exactly this (`post-kick-status-xfercomplete-misrouted-NULL-
deref` PASS = handler faults). That is another B8-style reboot risk. A safe kick would
have to arm the status and also write `dwc->ep0state=3` (mirror `0x602b3454`), derive
the dep from live `ep0_expect_in` (bit 2) rather than `g_class_dir_out`, and log
`dep->flags` before/after — still not justified before the data-phase issue below.

## 3. `dwc+0x2d8` bitfield (8/8 bits evidenced)

| bit | field | note |
|---|---|---|
| 0 0x01 | **three_stage_setup** | wLength!=0; selects status TRB type `0x40` (STATUS3) vs `0x30` (STATUS2); **not direction** |
| 1 0x02 | **ep0_bounced** | set when the OUT data TRB goes to `dwc->ep0_bounce_addr`; cleared only in giveback for dep number 0 |
| 2 0x04 | **ep0_expect_in** | set from bRequestType bit7 → Run B9 `0x8d` = GET data IN, `0x89` = SET data OUT |
| 3 0x08 | start_config_issued | EP enable/DEPSTARTCFG |
| 4 0x10 | setup_packet_pending | set in interrupt, cleared on XferComplete |
| 5 0x20 | delayed_status | set when setup returns 0x7fff (never here) |
| 6 0x40 | resize_fifos | resize TX fifos |
| 7 0x80 | pullups_connected | run/stop |

Run B9 `0x8d` vs `0x89` differ only in **bit2** (`ep0_expect_in`). Status direction is
the **dep argument** (GET→eps0 OUT, SET→eps1 IN), which the kick selected correctly;
TRB control `0x40` (3-stage) is correct for both. E0365's "zero-length ctrl_req buffer"
is corrected: OUT status (eps0) gets **maxpacket (64)**, IN status (eps1) gets 0;
`0x30/0x40` are STATUS2/STATUS3, not direction.

## 4. What actually failed in B9 for SET_CUR: the DATA-OUT bounce TRB

SET_CUR is OUT 26 B; `26 % 64 != 0`, dep number 0 → the **bounce branch** arms a TRB to
`dwc->ep0_bounce_addr (dwc+0x18)` with len `roundup=64`, setting `ep0_bounced` (bit1) —
consistent with queue-exit `state=0x8b` (bit1 set). `req->actual` is written only in
`dwc3_ep0_complete_data`: `transferred = min(len, roundup − (trb->size & 0xffffff))`,
then `memcpy(req->buf, dwc->ep0_bounce, transferred)`; giveback clears bit1 after the
copy. B9 `actual=0` ⇒ **transferred=0 ⇒ TRB remaining == 64 (zero progress)**; the 26
OUT bytes never arrived in the bounce buffer. `status=0` rules out the
SETUP_PENDING/-EPROTO branch. The STOP-pre state `0x99 next=3 event=2` means the late
XferNotReady was **DATA** (matching direction → ignored at `0x602b33d0`): `ep0state`
never became 3, i.e. **the host was still in the data phase**; no status stage existed
to complete. So the status kick cannot help; the blocker is the SET_CUR DATA-OUT stage
(TRB never progressed / host data not ACKed).
E0365 corrections recorded: (a) status buffer length is not always 0 (OUT status = 64);
(b) `0x30/0x40` are STATUS2/3 not direction; (c) bit0 is three_stage_setup, not
setup/data; (d) kick risk is the ep0state dispatch NULL-deref, not double-arm.

## 5. Actions

- **Run B10 cancelled** (guardrail failed: Unicorn proves the kick's follow-on NULL
  deref; and the B9 target was the data phase, not status).
- Unsafe kick removed. Safe **read-only** instrumentation module built for a future run:
  logs the live TRB (`dwc+4`: dma/size/ctrl), `dwc+0x18` bounce address, `req->buf`
  first word, state/next/event, dep0/dep1 flags in both queue-exit and completion —
  no kernel writes, no status kick.
  `artifacts/native/uvc-transport-e0368-trbprobe/usbg_video_a6400_shared_candidate.ko`,
  **82,344 B**, SHA-256 `8d28f5d286f5128daa8e7c1b8af3987f13e9a6b5140d604ddf28ce181ee65013`,
  transport audit **117/8/0**.
- Next offline step: explain why the SET_CUR bounce TRB completed with
  `remaining=64`/`actual=0` (TRBSTS, host ACK/NAK from the retained ETL, and
  `dwc3_ep0_xfernotready` DATA path); then fix the data stage before any status work.
