# E0363 — Run B8: completion thunk crashed the camera (wrong completion ABI); reverted to the safe OUT-DMA wrapper

Date: 2026-11-11. **Physical, user-authorized Run B8.** Module `9933cb1f…` (OUT-DMA
wrapper + `req->complete` logging thunk), daemon `99047575…`
(`--dmesg-sd --sd-log --sd-mount`). One ffmpeg attempt. **The camera rebooted during the
session** (kernel crash); it came back in Mass Storage without a battery pull.

## What happened

- Composite enumerated, WPD snapshot 0 devices, ffmpeg failed as before
  (`Could not RenderStream to connect pins`), ETL captured through the reboot
  (957,317,120 B kept).
- SD kernel trace from the crashed boot:
  ```
  [125.287] CLASS entry rt=a1 req=81 val=0100 idx=0002 len=001a
  [125.288051] EP0 ops wrapped orig=603dfb4c queue=602b2ad0
  [125.288191] EP0 queue dir=IN req=68987260 buf=65d1adbc dma=00000000 len=26 mapped=0
  [125.288363] EP0 queue exit ret=0 dma=05d1adbc state=8d next=1 event=2
  [125.288515] CLASS ep0-post … pending req=68987260 dma=05d1adbc complete=5f5674f0 status=ffffff8d
  [125.289330] EP0 complete req=68a1c9c0 status=1755433452 actual=1755433452 state=8d next=3 event=2
  [130.295] CLASS entry rt=21 req=01 val=0100 idx=0002 len=001a      (SET_CUR PROBE, +5.001 s)
  [130.296039] EP0 queue dir=OUT req=68987200 buf=65d1adbc dma=05d1adbc len=26 mapped=1
  [130.296199] EP0 queue exit ret=0 dma=05d1adbc state=8b next=1 event=2
  [130.297169] EP0 complete req=68a1c9c0 status=1755433452 actual=1755433452 state=89 next=3 event=2
  ```
  The trace ends at 130.297; the camera rebooted before the next 5 s dmesg flush.
- The telemetry itself is **not trustworthy**: the thunk was called with
  `req=68a1c9c0` (the **ep0 pointer**, not the queued request `68987260`/`68987200`) and
  read `status/actual = 0x68A1C9EC` (the ep0 address bytes), then called the original
  `uvc_ep0_comp` with that wrong argument — the likely crash cause. Timestamps suggest a
  callback ~0.15 ms after queue exit, i.e. **possibly immediate completion**, but that
  cannot be claimed until the completion ABI/offset is verified.

## Boundary (safety regression)

**`completion_thunk_crash_reboot`** — replacing `req->complete` at offset 28 and calling
it with the UDC's argument crashed the camera. Do not repeat this hook until the real
`usb_request` layout and the dwc3 giveback call site are verified from the kernel bytes
(offset 28 may not be `complete` in this build, or the callback signature differs).

## Reverted / safe module

The completion thunk was removed. The safe module keeps only the **OUT-DMA queue
wrapper + EP0 probe logging** (Run B7 proved it works: `mapped=1`, valid dma, ret 0, no
crash):
`artifacts/native/uvc-transport-e0364-safe/usbg_video_a6400_shared_candidate.ko`,
**80,828 B**, SHA-256 `35a22b9790f6f8df5549104e3ec7620759fe7fdc37b9e93cf22719e1ab35c652`,
transport audit `offline_module_audit_passed` (**117 checks / 8 skips / 0 failures**).

## Current state

Camera recovered to Mass Storage (42 modules, no `usbg_video`, `/tmp_bt` baseline), no
battery pull; the reboot cleared the crash state. No UVC frame; the host still fails at
RenderStream because both EP0 transfers time out (unchanged from B5/B6/B7).

## Next (offline first, then Run B9 with go-ahead)

1. **Verify the completion ABI offline before any hook:** disassemble
   `dwc3_gadget_giveback`/the EP0 completion call site in the preserved vmlinux and the
   reference `usb_request` field offsets, to find the real `complete` offset/signature
   (the B8 thunk's `r0=ep0` proves offset 28 was not the request completion callback or
   the call passes a different first argument). Use the E0358 Unicorn harness to step the
   giveback path if tractable.
2. Only then re-instrument completion (or use a safer observe-only site such as the
   gadgetcore/UDC request-list state at the next SETUP) and re-run.
3. The E0358 `__dwc3_gadget_ep0_queue` / `__dwc3_ep0_do_control_data` /
   `dwc3_ep0_start_trans` analysis still says failures of the data-stage start are
   ignored (warn-only), so a silent non-start remains the leading hypothesis for the
   timeouts; the correct completion observation is needed to decide Branch A (status
   stage) vs Branch B (start_trans/TRB).
