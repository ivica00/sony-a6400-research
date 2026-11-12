# E0382 — Status stage: `do_control_status`/`start_trans` are correct; host xHC control-TD timeout path completes GET_CUR; device status ACK timestamp is the remaining unknown

Date: 2026-11-12. Offline synthesis of two subagent reports:
[kernel status path](artifacts/analysis/e0382-kernel-disasm/e0382-report.md) and
[xHCI/UCX status-stage timeline](artifacts/analysis/e0382-xhci-status/timeline.md).
No camera, no module build/run.

## 1. `dwc+0x2d8` bits and the 0x29c flow

Confirmed bitfield: bit0 three_stage_setup, bit1 ep0_bounced, **bit2 (0x04) =
ep0_expect_in**, bit3 start_config_issued, bit4 setup_packet_pending,
**bit5 (0x20) = delayed_status**, bit6 resize_fifos, bit7 pullups_connected.
`fl=0x8d` = connected|start_config|**expect_in**|three_stage (GET); `fl=0x89` = SET
(expect_in=0, bounced=0); SET queue `0x8b` adds ep0_bounced; STOP `0x99` adds
setup_packet_pending. `0x04` is **not** delayed_status.

Flow for event `0x29c` (`000020c0` = NRDY STATUS ep0, subtype 2):
```
2c78..2ca0 event code = ((e[1]&3)<<2)|(e[0]>>6); 3 = XFERNOTREADY -> 0x3390
3390..33b8 subtype=e[1]>>4 &0xf; 2 = STATUS -> 0x3448
3448 ldr r3,[dwc+0x2dc] ; cmp #3 ; bne exit (0x3450)   ; next==3 (set by data-complete 0x30c0)
3454 str r3,[dwc+0x2e0]                                ; ep0state=3
3458 ldrb r3,[dwc+0x2d8] ; and #0x20 (delayed) ; beq 0x34a4 ; GET: 0x20 clear
34a4 dep = dwc->eps[(event>>1)&0x1f] = eps[0]
34b0 bl __dwc3_ep0_do_control_status(dwc, eps[0])
```
`do_control_status 0x253c`:
```
253c..2574 resize bit6 check (clear)
2578 r0=[dep+0x48]=dwc ; r1=dep->number=0
2580 ldrb r3,[dwc+0x2d8] ; tst #1 (three_stage_setup=1) -> r2=0x40
2590 tst r1,#1 (odd) -> len 0 ; even (dep0) -> ldrh r3,[dep+0x14] (maxpacket=64)
2598 str r2,[sp]  ; trb ctrl
25a0 ldr r2,[dwc+0x10]  ; ctrl_req DMA
25a4 bl dwc3_ep0_start_trans(dwc, 0, ctrl_req, 64, 0x40)
25a8..25b8 error -> warn_slowpath only
```
`start_trans 0x2424`: if `dep->flags & 0x10` (BUSY) → return 0 with **no TRB, no
DEPCMD, no warning**; else writes the single reused `ep0_trb [dwc+4]` with
`ctrl|0xc03 = 0xc43` (STATUS3, HWO=1), sends DEPCMD type 6 (≤500 µs poll), on success
sets dep BUSY and `next=1`. Both BUSY-skip and success return 0, so callers cannot
distinguish them; only negative DEPCMD gives the warn.

**The 0x29c arm is geometrically correct:** dep=eps[0], OUT status, TRBCTL=0x40,
len=maxpacket 64, buf=ctrl_req, HWO=1. `ep0_expect_in` is not read by
`do_control_status`/`start_trans`; it cannot change trb_ctrl or length. No
`warn_slowpath`/WARNING exists in the 5 s window. `dep->flags` was 0x1 (BUSY clear)
at GET completion, so the BUSY early-return is excluded. `start_trans`/DEPCMD can
therefore not explain the 5.006 s status stall by a wrong direction/length.

## 2. Ring/batch reconstruction

B14 data-complete batch (`cnt=0xc`) is
`[0x2fc=0x10c2 NRDY(DATA ep1, ignored), 0x300=0xc042 data complete (current),
0x304=0x20c0 NRDY(STATUS ep0)]`, ending lpos=0x308. The status arm happens in that
same IRQ batch because complete-data set `next=3` at `0x30c0`. The status
XferComplete slot (B12 `0x2a0`, B14 `0x308`) is written/consumed after the data batch
and before SET class entry; the status path `0x334c` then gives back eps[0] list (empty
after GET giveback), sets `ep0state=1`, and calls `out_start` to arm the SETUP TRB.
The E0381/task-5 “0x2a4 in the same 12-byte batch as its out_start” contradiction was
an **off-by-one batch start**: the SET class-entry batch is
`[0x2a4,0x2a8,0x2ac]` (B12) / `[0x30c,0x310,0x314]` (B14); the status XferComplete
occupies `0x2a0`/`0x308` as its own single-event batch and runs the `out_start`.

Device printk has **no lines between 140.678886 and 145.683359 s** (B14) and none
between 141.424953 and 146.421337 s (B12), so the exact device timestamp of the silent
status XferComplete is not directly logged.

## 3. Host xHCI/UCX timeline (decisive)

The USBXHCI provider records **no per-TRB transfer events** (only ID41 “transfer
initialized” + ID45 companion). The decisive evidence is the xHCI **command ring**:
```
6.090881500 UCX 53 dispatch GET_CUR A1 81 0100 0002 001A, 26 B
6.090886500 USBXHCI 41 transfer initialized Slot15/DCI1/BytesTotal 26
            (control TD queued up-front; status OUT TRB part of this single TD)
6.0909 .. 11.1015  NO HOST EVENT AT ALL (no command, no second transfer-init,
                    no port event; no NAK/retry trace)
11.101533900 Stop Endpoint cmd (Slot15 EP1)      = dispatch + 5.0106524 s
11.101693800 command complete code 1
11.101699800 Set TR Dequeue Pointer (DCS=1, 0x7C18C700); complete 11.101837800
11.101843800 UCX 21: URB completes SUCCESS 0x0, NtStatus 0x0, 26 B
```
- The GET_CUR completion at 11.1018 is **host-triggered**: the 5 s control-transfer
  timeout/cancel path issues Stop Endpoint + Set TR Dequeue, then the driver hands the
  URB back **SUCCESS with the 26 data bytes** 6 µs after Set-TR-Dequeue completes.
  It is not a normal immediate status-stage completion.
- No host retry exists during the 5 s; NAK retries are hardware-level and untraced.
- Host-side congestion ruled out: the same controller serviced another device
  (SlotId 4, separate UCX usbdev) every ~1.06 s with 2–4 ms latency; 91,317
  interrupter/DPC events, max gap 1.013 ms; zero USBHUB3 events in the window.
- SET_CUR follows the same pattern: Stop Endpoint at +5.0095771 s → URB
  **CANCELED** 0xC0010000 (0 B). The three later control requests are fast
  XACT_ERRORs.

## 4. Verdict and next

- **No firmware bug in `do_control_status`/`start_trans` is supported.** The device
  arms the correct OUT status TRB (STATUS3, len 64, ctrl_req, HWO=1) in the data
  completion batch; `ep0_expect_in` is irrelevant; no warning; BUSY excluded.
- The host URB completion at 5.01 s is the host stack’s timeout/cancel path, not a
  device error return. The host ETL cannot decide whether the device ACKed the status
  OUT before the abort (no transfer-event completion/NAK trace).
- **Remaining unknown:** the exact device-side time at which the status stage was
  ACKed/completed and whether it happened before or at the host abort. The next probe
  must timestamp the silent status path (`do_control_status 0x253c` / status
  XferComplete / `out_start`) without changing behavior.
- Read-only `e0381-roprobe` (or `e0382-roprobe`) with:
  - fixed `ev = *([dwc+0xcc])` double-dereference, verified `regs+0xc30c`,
    `evt->lpos/count` and raw event bytes;
  - completion caller LR (`0x3344` vs `0x3364`) and `ep0state/next/flags`;
  - a read-only log hook at `do_control_status 0x253c` (e.g. kprobe if available) or
    an equivalent per-event pre-dispatch trace, timestamped in jiffies/us, so the
    status arm time and the status XferComplete time can be compared with the host
    abort at 145.683 s;
  - no ops shadows, no `lr` filtering, no status kicks, no gcguard.

If the probe shows the status ACK was sent before the host abort but xHC still waited,
the target becomes the host/xHC side (not firmware); if it shows the ACK was only sent
at/after the abort, the target is the device status-arm timing/IRQ scheduling. Only
then design a fix and prove it in Unicorn.
