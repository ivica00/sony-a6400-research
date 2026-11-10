# E0311 — first UsbControl wake (wake-only), two evidence-backed model contracts, and the GRM wait

Date: 2026-11-10. Four-teammate offline cycle #2 (Lead + usb-wait-analyst,
msg-producer-analyst, receive-id-analyst, usb-harness-runner). No camera/USB I/O.
No fabricated messages or host-called callbacks. **No GUI frame and no full
breakthrough yet**, but the first real USB-thread wake and two model contracts
are now in place.

## 1. First UsbControl wake (wake-only, not connect)

State-valid `/dev/usb/event` record subtype 0 with payload `0100000000000000`
(`78 e8 02 00 dd b0 2f 56 00 08 78 e8 01 00 00 00 00 00 00 00`) produced the
**first genuine new FUTEX WAKE on UsbControl 0x5D23ED3C** (TID 1018 woke, then
re-waited). Trace proof (`artifacts/analysis/e0336-*`):

* producer path: TID 1019 → libInfraUsbCmn `proc_svc_event` (0xCDF4) →
  libUsbControl bridge `0x12E54` → `UsbIfWrapper::EventListner` (0x12D28) →
  `UFW::MsgSender::SendEvt` (0xA6E8) → target `[UsbIfWrapper+0x18] = 0x00CA8192`
  → local-queue post → futex wake.
* delivered message: `ObjMsg{Cat 0x6103, Msg 0x0A6000 (`MSGID_CID_CHANGED_EVT`),
  params 0x1002=1, 0x1003=0}`; `MsgId2EventId` maps it to **event 1**, which does
  not exist in FSM state 1 (`STATE_ID_STOP`) and whose handler `0x110CC` does not
  call `DispatchEvent` → wake without dispatch. Grading: **wake-only**.

## 2. USB second forward path: closed as boundary

Systematic elimination (tasks 10/21/22/23/24/29):

* Enabled context at 308.6M is only `{0x2E878}` with `proc_kevent_otg`
  (`0x562FB0DD`). Host-connect (event 15) and gadget (event 8 → SETCONFIG
  `0x0A4001`) classes need their own callback/context registration, which does
  not exist in this state (`usbg_buspower`/gadget device not open).
* The CUsbSvc client registry is not empty: one node, callback
  `libInfraUsbCmn+0xCDF5 proc_svc_event`, bridged to libUsbControl via a
  15-slot table all pointing at `libUsbControl+0x12E54`.
* The kernel builds no `MWF::ObjMsg`; the `0x0A4000` (VBUS_CHANGED) producer is
  app-side. Task-19's libObj `0x0A4000` literal was a **false positive**
  (2-byte-aligned overlap `0x40000009`/`0x4100000A`); a corrected aligned
  literal + movw/movt scan over libObj, all USB libraries and im.elf finds **no
  construction of `0x0A4000`** anywhere.
* No OTG subtype 0..7 maps to a progressing FSM event from state 1.
* Explicit boundaries: `libobj_usb_vbus_relay_not_derivable`,
  `gadget_event_context_not_enabled`, `usb_vbus_changed_mwf_0x0a4000_producer_not_derivable`.
  Resolution needs a new read-only physical observation (userland USB trace) —
  not fabricated.

## 3. Two evidence-backed model contracts implemented

### `--nanosleep-policy block` (opt-in)

Threads policy `nanosleep` previously returned 0 immediately (no virtual clock).
Opt-in block parks the caller as `blocked_sleep`, reason
`nanosleep_no_virtual_deadline`, and records it; no timer expiry is fabricated.
Motivation: MWF `MonDrv::Getchar` monitor poller (`libMWF+0x251CE`) called
`MSleep(300)` through `nanosleep`, so the no-input poll spun and consumed budget.
Tests: `test_threads_policy_block_nanosleep_parks_caller`; legacy immediate
baseline retained (`test_threads_policy_services_nanosleep`).

### `--gles-device kernel-bound-decoded` (opt-in)

Historical `guest_gles` command table was wrong vs the identity-pinned
`grm_gles.ko` dispatch (E0337/E0341): `0x8004820A` is the suspend/status word
`dev+0x48` (0 at probe, not power_state=1); `0xC004820D` is
wait-for-completion (out 1 only when a completion is pending, 0 timeout), not
GET_RESOURCE_SUB=1; `0xC004820E` signals completion; `0xC0048209` consumes the
suspend/status; `0xC004820F` is kick control (accept 0/1, latch); `0x80048263`
returns the driver status. Decoded mode implements these; default baseline is
unchanged. Tests: `test_decoded_mode_uses_grm_gles_ko_semantics`.

## 4. GRM path: where the first GUI gate now stands

E0309's finding stands: `im.elf` gating passes, GRM phase-1 lazy-init blocks
THREAD_INFRA0, main never creates `THREAD_APP` (entry `im.elf+0x94F8`), so
`viewUnified2`/UI never runs.

Runs (no injection; resume chain):

| run | instructions | result |
| --- | --- | --- |
| `e0318-long-continuation` | 388,310,279 | no THREAD_APP; TID1054 in dmpgles2 poll; TID1007 spinning in MonDrv::Getchar |
| `e0343-grm-decoded` (actually old gles + sleep policy) | 449,524,718 | TID1007 parked blocked_sleep; TID1054 progressed into RM init (`rm_rqueue_hw_log_init` memcpy from /dev/stream); still no THREAD_APP |
| `e0350-grm-decoded` (corrected decoded semantics + sleep policy) | 488,299,004 | TID1054 stuck in the `0x72BAF0` wait loop (0x820D out==0 retry) needing a matching `0xC004820E` signal; TID1011 runnable in RM code; TID1007 parked; THREAD_APP/sem `0x0083037A`/view still absent |

The decoded-GLES model changes the loop faithfully but exposes the real
dependency: the RM hw-log wait needs a **matching completion signal** from a
peer RM thread, and/or the cleanup-exit guard `*[libObj+0x13f0868] != 0` whose
writer is unidentified. Boundaries: `gles_wait_signal_keymap_unmodelled`,
`gles_kick_completion_unmodelled`, `libobj_slot_0x13f0868_writer`,
`mwf_monitor_input_poll`.

## 5. Other decoded lanes (kept for completeness)

* `0x00A3035A/0x00A3035B` are libdig_level's internal request/reply pair; the
  startup handshake cannot self-complete in the replay (main thread answers only
  after a first command; API callbacks registered after the handshake). The
  first command producer is behind `im.elf/libIMDB` gating/GRM, not a USB input.
* `0x012C032F` is a receiver-only date/event server queue (external client
  missing), not a boot gate.
* USB kernel VBUS lane: FUSB IRQ → `event_vbus_exec` → `usb_buspwr.ko`
  `VbusStateCb` → UIPC `0x012002DA`; delivery already verified, power lane only.

## 6. Checks

Full suite **876 tests OK** (19.309 s) after the nanosleep/GLES contracts and
their tests. No UVC/PTP function, no camera access, no GUI frame.

## 7. Later-cycle update (same date, after task-34/35)

The RM cleanup-exit guard `*[libObj+0x13f0868]` is **guest-produced**, not a
missing contract: `libObj 0x72be20` (called from the RM dispatcher path
`0x72a650`) stores `1` into the slot and then calls
`0x72be10 → 0x72bb50(0)` = `ioctl(/dev/dmpgles2, 0xC004820E, arg 0)` — exactly
the completion signal the e0350 TID1054 waits for in `0x72baf0`.
`rm_kick_thread_init 0x72bda0` resets it to 0 (start/finish handshake). The
`0x72ca70` drain alone cannot exit; running the RM start step would set slot=1
and the signal would release the wait. At e0318/e0350 stops the slot is 0 and
the writer has not run yet; which thread runs it (and what blocks it) is now
task-38, with a 100M-instruction continuation from `boot-e0350-grm-decoded`
(`e0356`) in flight. No injected signal and no host-written slot were used.
