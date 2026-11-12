# E0399 — B21 ETL, deferred-restore workqueue, and Run B22: MSC reached without battery pull, but no deferred-restore log and no status-stage capture

Date: 2026-11-12. Offline + physical B22.

## 1. Documentation sync + B21 ETL

Documentation snapshot synced through E0398; full suite **1312 OK**.

B21 ETL (`artifacts/analysis/e0398-runb21statusdisconnect/usb-capture.etl`,
158 MB) decoded via XML + UCX control extraction:
- Sony UVC device `…849E8398`: GET_DESCRIPTORs 3.5–4.0 ms, GET_STATUS 3.9 ms.
- **GET_CUR `A1 81 0100 0002 001A` at t=48.311019, duration 5.012133 s, SUCCESS.**
- **SET_CUR `21 01 0100 0002 001A` at t=53.323167, duration 5.010848 s, CANCELED.**
- After the wedge: PTP class requests `A1 67 0000 0000 0024` (2.33 s, XACT_ERROR) and
  `21 66 0000 0000 0000` (2.78 ms, XACT_ERROR), plus GET retries (XACT_ERROR).
- No SELECT_CONFIGURATION/SELECT_INTERFACE records were emitted by the UCX session
  (same trace limitation); no PTP interface-0 traffic precedes the initial GET_CUR.

The first GET_CUR is therefore the 5 s transfer, as in B14/B18; SET_CUR is canceled
after another 5 s and the PTP interface then wedges.

## 2. e0399 deferred-restore workqueue

- Added `schedule_work` + `msleep` imports; a 32-byte work object with the handler at
  offset 12; `disconnect_cb` now schedules the work instead of calling restore
  synchronously.
- Work handler polls `in_flight` with `msleep(10)` up to 200 ms, then calls
  `a6400_uvc_restore_descriptors_bridge()`.
- Module `800d5cfd1dbac5ea1f8137089023bc8d282bb6c000524d62bd2b8ae3e3cb0013`
  (81,152 B), audit **117/8/0**, suite **1312 OK**.
- Static audit confirms no sleeping call in atomic context: `disconnect_cb` only
  schedules; `msleep` is in the work handler.

## 3. Run B22 result

- ETW started before PC-Remote switch: 182,591,488 B.
- ffmpeg still fails; no frame.
- The user switched to MSC **without a battery pull** (reported), but the camera log
  shows a fresh boot/uptime reset and **no `DISCONNECT schedule deferred restore` or
  `DEFERRED restore work` lines**; the module was already absent and `rmmod` returned
  "No such file or directory". So B22 cannot confirm that the deferred work ran: the
  camera likely rebooted during the mode switch rather than the workqueue restoring the
  descriptors. It is not evidence that the workqueue path is correct.

## 4. Status-stage capture

No status-stage (`0x29c`/`0x2a0`/`do_control_status`) hook was implemented: a clean
read-only hook is not available (no kprobe), and a 4-byte ARM branch trampoline in
kernel text would be a write to live kernel text and was not attempted. The `ev`/`trb`
ring fields therefore remain zero at the existing hook points, and B22 still has no
status-stage timestamps. This is the remaining gap.

## 5. Verdict

- B21 ETL confirms the initial GET_CUR is the 5.012 s transfer; SET_CUR is canceled;
  the PTP interface wedges afterward.
- The deferred workqueue is built and audited, but B22's no-battery-pull result is
  confounded by an apparent camera reboot; no deferred-work log exists.
- Status-stage capture remains unimplemented; it requires either a safe kprobe or a
  carefully verified kernel-text trampoline, not another queue/class ring.
