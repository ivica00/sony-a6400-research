# E0446 — B21 event-ring decode, EP0 sequence model on real kernel code, read-only EP0 observer (no camera access)

Date: 2026-11-13. OFFLINE only: no camera, no USB, no module load. Python = system `python` (unicorn 2.1.4).

## 1. New decode of the B21 `gev` event-buffer windows (docs/evidence/0398, `A6400K.LOG`)
Window = 8 words before `lpos` then `lpos..lpos+3` (`a6400_uvc_log_events`); depevt word = `ep<<1 | type<<6 | status<<12`.
At the GET_CUR data-complete callback (lpos 0x298) the words are `c042` (XferComplete ep1 = data) at idx 0xa6 and
`20c0` (XferNotReady **status**, ep0) at idx 0xa7 with `cnt=0xc` (3 events pending). At the SET_CUR SETUP (lpos 0x2a4)
the history is `c040 10c2 c042 20c0 c040 | c040(SETUP)`: **NRDY(status) was consumed and an ep0 XferComplete followed
before the next SETUP**. The event was therefore not lost and not mis-ordered; `ep0state=1`/`eps0 flags=0x1` (not BUSY)
at the SET_CUR SETUP agree. `uvc_ep0_comp` (reference 0x1a74) only calls `ep->ops->free_request`; it does not block.

## 2. Model: real vmlinux `dwc3_ep0_interrupt` (0x602b2c68) replayed with those events
`artifacts/analysis/e0446-dwc3-ep0-sequence-model/e0446-ep0-sequences.py` (reuses the E0366 harness; DEPCMD accepted).
| sequence | status armed | result |
|---|---|---|
| A in-order (observed): NRDY-data, data-complete, NRDY-status, status-complete | yes (1 DEPCMD, TRB ctl `0xc43`) | ep0state 2→3→1, clean |
| B NRDY(status) before data-complete (race) | no | status never armed, then NULL deref `UC_ERR_READ_UNMAPPED` |
| C NRDY(status) never delivered | no | stays ep0state=2,next=3 |
Verdict: for the observed ordering the stock kernel software arms the status stage; hypothesis B is refuted (it would
oops, which was never seen live). The 5.01 s stall is **not** an EP0 state-machine/queue bug in software;
the earlier "kick from req->complete" fix (E0366) is not needed and stays rejected.

## 3. What is still unknown (and why no behavioural fix is shipped)
When NRDY(status) was handled and when the status XferComplete arrived relative to the 5 s host abort cannot be read
from the klog (no timestamps between the data-complete and the next SETUP). Candidates left: (S1) status TRB armed
promptly but the host's status OUT never completed it until the abort/new SETUP; (S2) the IRQ thread handled the
status events ~5 s late. Distinguishing them needs timestamps, not another code change.

## 4. Read-only observer (new module)
`tools/native_camera/uvc_callback_bridge.c`: `a6400_uvc_obs_start` (first CLASS request) schedules a work item that polls
`ep0state/next_event/dwc flags/eps0,eps1 flags/event-buffer lpos,cnt` with `msleep(1)` for ≤1500 iterations, records
changes with ktime_get_ts and dumps one `OBS` printk line per change. No hooks, no kernel-text or kernel-object writes.
- Module `artifacts/native/uvc-transport-e0446-obs/usbg_video_a6400_shared_candidate.ko`
  SHA-256 `7c87ab37f0da038f7ce0f3d112948deacb571584abfa275836b6b070c398002f` (82,468 B), 56/56 imports verified,
  audit **117/8/0 offline_module_audit_passed**, UVC unit tests 37 OK.
- `e0446-observer-unicorn.py` executes the compiled observer from the built object against a scripted timeline:
  NULL ep ignored, second start no-op, work func slot (+12) = work fn, **0 writes** to dwc/eps/event objects, all 5
  scripted transitions recorded (incl. the +5 s status-complete) — PASS.
- Not verified: that `schedule_work` with a zeroed static `work_struct` runs on the camera (same pattern as the
  unconfirmed E0399 deferred-restore; B22 was confounded by a reboot).

## 5. Next (needs user go-ahead): one supervised PC Remote run with the observer module
Success criterion: `OBS` lines give timestamps for ep0state 2→3 and the status XferComplete versus the host's 5.01 s
Stop-Endpoint (ETL). S2 ⇒ fix IRQ-thread scheduling/priority; S1 ⇒ investigate host/bus-level status handshake.
Teardown follows the E0397/E0399 rules (MSC switch; battery pull if the switch hangs).
