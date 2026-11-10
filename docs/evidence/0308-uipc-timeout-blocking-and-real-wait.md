# E0308 — modeling the positive UIPC receive timeout: from a 19M-instruction poll loop to a real wait

Date: 2026-11-10. Offline original-firmware execution only; no camera access in
this step. No GUI frame. Builds on E0307.

## 1. What the idle state really was

At the E0307 timeout states the app looked idle: `StlDateEvtLoop` (TID 1066)
issued `ioctl(fd=3, cmd=0x80000007 = RCV_MSG_TMO)` with argument
`{queue=0x012C032F, …, tmo=60000}` in a tight loop. The E0307 run recorded
~167,000 such ioctls and the E0313/E0314 reports filled with `returned=-1022`
(`OSAL_ERR_TIMEOUT`).

The model was returning `-1022` **immediately for any empty queue with a finite
timeout**, because no virtual-time model exists. The real call would sleep up to
the timeout. The loop was therefore an emulator modeling artifact, not app
behaviour, and it consumed millions of instructions without letting the wait
become a real dependency.

## 2. Contract change (opt-in `kernel-e0301`/`kernel-e0303`)

`GuestUipc.handle_rcv_msg_tmo` now distinguishes:

| input | behaviour |
| --- | --- |
| message present | dequeue/write message, return 0 (unchanged) |
| empty, `tmo == 0` | non-blocking poll → `-1022` (unchanged) |
| empty, `tmo == 0xFFFFFFFF` | block indefinitely (unchanged) |
| empty, `0 < tmo < 0xFFFFFFFF`, kernel policy | **block until a message arrives** via the existing UIPC waiter scheduler; transaction records `status='blocked_timeout_not_modeled'` and the timeout value; report key `uipc_rcv_timeout_policy='block_until_message_no_virtual_deadline'` |
| empty, finite `tmo`, legacy/other policies | immediate `-1022` baseline preserved |

No timer expiry is fabricated: if no message ever arrives the thread stays
blocked and the report says so. Unit test:
`tests/test_guest_uipc.py::test_positive_timeout_blocks_only_under_kernel_policy`.

## 3. Result: the app moves past the poll loop

Run `e0315-live-block.json`: resume `boot-e0314-live-usbwake.ckpt`
(268,757,618) with the E0303-G5 policies plus
`--nflasha4-device observed-dump --mount-service observed-nflasha1
--setting-service observed-nflasha2 --uipc-pool-options kernel-e0301`; budget
30M instructions / 150 s.

* **308,622,155 instructions** (instruction_budget_exhausted), 68 threads.
* Only two finite-timeout waits occurred instead of 167k: queue `0x012C032F`
  (tmo 60000) and queue `0xA3035B` (tmo 1); both recorded as
  `blocked_timeout_not_modeled`.
* After the poll wait became a real wait, the app continued into graphics
  infrastructure work: repeated `dmpgles2` ioctls (`0xC004820D/11/12`,
  `0x8004820A`, …), `nanosleep` scheduling and further service threads.
* At the budget stop: `THREAD_INFRA1` is `blocked_uipc` on `0xA3035A`,
  `StlDateEvtLoop` is `blocked_uipc` on `0x012C032F`, `main` is `blocked_futex`;
  `UsbControl` (1018), `UsbBusPower` (1016) and `BusPower` (1022) remain
  `blocked_futex`; `usb_otgcore.config` is `None`; `usb_event` context is
  190584; no `viewUnified2`, OSD A/B unmapped, **no frame**.

So the app is now waiting on two UFW/UIPC message ids with no emulated producer
(`0x012C032F`, `0xA3035A`) rather than spinning. That is a clearer, honest
dependency boundary: the next step is to identify the receiver/service behind
those ids and the producer contract (or to model the corresponding kernel/service
message source) — not to inject a synthetic message.

## 4. Boundary and limits

* No new camera input; no device write; all dumped content remains from the
  hash-checked read-only images (E0305–E0307).
* The two blocking queues are **not** identified yet. They are not in the UIPC
  registered-callback map and have no pending messages; their ids look like
  UFW/internal message ids rather than osal dynamic-queue slots.
* `UsbControl` never left `blocked_futex`; the USB FSM, PTP/UVC path, view tier
  and display remain unexercised. No UVC/PTP function is claimed.
* Timeout expiry is not modeled (documented); a blocked thread only wakes on a
  message.

## 5. Next

1. Identify the receivers of `0x012C032F` (StlDateEvtLoop) and `0xA3035A`
   (`THREAD_INFRA1`) from the checkpoint objects/maps and the original
   libraries; then find the evidence-backed producer for each (likely UFW/
   service messages, not host-injected ones).
2. Continue the USB lane: UsbControl runtime receive id + inbound SETCONFIG,
   buspwr port-type reply, or the `0x008F013A` relayed-notification consumer.
3. Keep the default/legacy immediate-timeout baseline; do not make the finite
   timeout silently succeed.

## 6. Artifacts

* Change: `src/a6400/execution/guest_uipc.py`,
  `src/a6400/execution/interpreter_probe.py`, `tests/test_guest_uipc.py`.
* Run: `artifacts/analysis/e0315-run-live-block.py`; report
  `artifacts/execution/e0315-live-block.json`; checkpoint
  `artifacts/checkpoints/boot-e0315-live-block.ckpt`.
* Inspectors: `artifacts/analysis/e0315-idle-loop-inspect.py`,
  `e0315-queue-id.py`, `e0315-detail.py`, `e0315-inspect.py`.

## 7. Checks

Full suite **874 tests OK** (20.629 s).
