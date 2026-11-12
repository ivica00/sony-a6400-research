# E0383 — Run B15 status timestamps: a 4.997 s gap starts **inside the EP0 completion callback**, before any status-stage processing

Date: 2026-11-12. Physical read-only Run B15-roprobe with module `b76de9e1…`
(87,800 B, audit 117/8/0, exact-object Unicorn overall_pass=true), daemon
`99047575…`. Clean receipt, native 054C:0CAA/MSC, no battery pull, camera healthy
(42 modules, `/tmp_bt` baseline). Host ETL 528,949,248 B retained.

## 1. Complete, un-truncated B15 `GCRO` lines

GET_CUR:
```
[127.128368] TS CLASS-pre-ts sec=143 nsec=430711501
[127.128511] GCRO CLASS pre ctrl=ffdfe000 cr0=010081a1 cr1=001a0002 dma=089fe000 trb=ffdfd000 ta=089ff000 bpl=089fe000 bph=00000000 sz=00000000 ctl=00000c22 bv=ffdfc000 ba=08a26000 dep0=68a1c9c0/00000001 dep1=68a1c3c0/00000001 e0=68a1c9e4 e1=68a1c3e4 ev=689fc810 lpos=0 cnt=0 flg=6970a7a0 gcnt=0 state=1 next=2 fl=8d
[127.129982] TS queue-before-orig sec=143 nsec=432325501
[127.130114] TS queue-after-orig sec=143 nsec=432457001
[127.130372] TS queue-entry sec=143 nsec=432717501
[127.130508] GCRO queue ctrl=00000000 cr0=00000000 cr1=00000000 dma=089fe000 trb=ffdfd000 ta=089ff000 bpl=08e38efc bph=00000000 sz=0000001a ctl=00000c53 bv=ffdfc000 ba=08a26000 dep0=68a1c9c0/00000001 dep1=68a1c3c0/00000011 e0=609d0574 e1=68a1c3e4 ev=689fc810 lpos=0 cnt=0 flg=6970a7a0 gcnt=0 state=2 next=1 fl=8d
[127.130956] GCRO queue dep0_head req=609d0540 buf=68e38efc len=26 actual=0 status=-115
[127.131738] TS CLASS-post-ts sec=143 nsec=434083001
[127.131879] GCRO CLASS post ctrl=ffdfe000 cr0=010081a1 cr1=001a0002 dma=089fe000 trb=ffdfd000 ta=089ff000 bpl=08e38efc bph=00000000 sz=00000000 ctl=00000c52 bv=ffdfc000 ba=08a26000 dep0=68a1c9c0/00000001 dep1=68a1c3c0/00000011 e0=609d0574 e1=68a1c3e4 ev=689fc810 lpos=0 cnt=0 flg=6970a7a0 gcnt=0 state=2 next=1 fl=8d
[127.132354] GCRO CLASS post dep0_head req=609d0540 buf=68e38efc len=26 actual=0 status=-115
[127.133280] EP0 complete ep=68a1c9c0 req=609d0540 status=0 actual=26 state=8d next=00000003 event=00000002 dep0=00000001 dep1=00000001
[127.133582] EP0 complete lr=602b00e8 state=02 next=00000003 fl=8d
[127.133749] GCRO complete ctrl=00000000 cr0=00000000 cr1=00000000 dma=089fe000 trb=ffdfd000 ta=089ff000 bpl=08e38efc bph=00000000 sz=00000000 ctl=00000c52 bv=ffdfc000 ba=08a26000 dep0=68a1c9c0/00000001 dep1=68a1c3c0/00000001 e0=68a1c9e4 e1=68a1c3e4 ev=689fc810 lpos=0 cnt=0 flg=6970a7a0 gcnt=0 state=2 next=3 fl=8d
[127.135097] TS complete-entry sec=143 nsec=437441001
```
SET_CUR:
```
[132.132525] TS CLASS-pre-ts sec=148 nsec=434869001
[132.132668] GCRO CLASS pre ctrl=ffdfe000 cr0=01000121 cr1=001a0002 dma=089fe000 trb=ffdfd000 ta=089ff000 bpl=089fe000 bph=00000000 sz=00000000 ctl=00000c22 bv=ffdfc000 ba=08a26000 dep0=68a1c9c0/00000001 dep1=68a1c3c0/00000001 e0=68a1c9e4 e1=68a1c3e4 ev=689fc810 lpos=0 cnt=0 flg=6970a7a0 gcnt=0 state=1 next=2 fl=89
[127.134?] TS queue-before-orig sec=148 nsec=436219001
[132.134017] TS queue-after-orig sec=148 nsec=436359001
[132.134338] TS queue-entry sec=148 nsec=436682001
[132.134489] GCRO queue ctrl=00000000 cr0=00000000 cr1=00000000 dma=089fe000 trb=ffdfd000 ta=089ff000 bpl=08a26000 bph=00000000 sz=00000040 ctl=00000c53 bv=ffdfc000 ba=08a26000 dep0=68a1c9c0/00000011 dep1=68a1c3c0/00000001 e0=609d0574 e1=68a1c3e4 ev=689fc810 lpos=0 cnt=0 flg=6970a7a0 gcnt=0 state=2 next=1 fl=8b
[132.134981] GCRO queue dep0_head req=609d0540 buf=68e38efc len=26 actual=0 status=-115
[132.135771] TS CLASS-post-ts sec=148 nsec=438115001
[132.135912] GCRO CLASS post ctrl=ffdfe000 cr0=01000121 cr1=001a0002 dma=089fe000 trb=ffdfd000 ta=089ff000 bpl=08a26000 bph=00000000 sz=00000040 ctl=00000c53 bv=ffdfc000 ba=08a26000 dep0=68a1c9c0/00000011 dep1=68a1c3c0/00000001 e0=609d0574 e1=68a1c3e4 ev=689fc810 lpos=0 cnt=0 flg=6970a7a0 gcnt=0 state=2 next=1 fl=8b
[132.136386] GCRO CLASS post dep0_head req=609d0540 buf=68e38efc len=26 actual=0 status=-115
[132.137374] EP0 complete ep=68a1c9c0 req=609d0540 status=0 actual=0 state=89 next=00000003 event=00000002 dep0=00000001 dep1=00000001
[132.137594] EP0 complete lr=602b00e8 state=02 next=00000003 fl=89
[132.137750] GCRO complete ctrl=00000000 cr0=00000000 cr1=00000000 dma=089fe000 trb=ffdfd000 ta=089ff000 bpl=08a26000 bph=00000000 sz=00000040 ctl=00000c53 bv=ffdfc000 ba=08a26000 dep0=68a1c9c0/00000001 dep1=68a1c3c0/00000001 e0=68a1c9e4 e1=68a1c3e4 ev=689fc810 lpos=0 cnt=0 flg=6970a7a0 gcnt=0 state=2 next=3 fl=89
[132.139197] TS complete-entry sec=148 nsec=441541001
```
(The `TS queue-before-orig` sec=148 line appears at uptime 132.133874; the `[127.134?]` above is a transcription placeholder — the exact line is
`[132.133874] TS queue-before-orig sec=148 nsec=436219001`.)

## 2. Timestamps and the 4.997 s gap

- GET complete-entry ktime **143.437441 s**; the very next user-visible event is
  SET CLASS-pre-ts **148.434869 s** → **4.997428 s** gap with no intermediate log.
- The completion callback's entry is logged *after* GCRO/complete logging but *before*
  the original completion call. The thunk code is:
  `... GCRO complete ...; TS complete-entry; if (orig) orig(ep,req); return;`
  (the after-orig timestamp insertion did not make it into this build — source has no
  `complete-after-orig` call, so the gap cannot be localized between orig and return
  from the log alone).
- Queue processing itself is fast (queue-before-orig 143.432325 → after-orig
  143.432457, entry 143.432717); CLASS pre→post is ~3.4 ms. The 5 s gap starts
  **after the completion callback logs entry**, i.e. in the completion callback/orig
  free path or the subsequent event-loop transition.
- The following event batch is processed only at 148.434 s (SET setup), with
  `ep0state=1 next=2 fl=89` — the status path (0x334c → out_start) has run by then,
  matching E0381/E0382: the status XferComplete is silent and occurs just before SET
  class entry.
- `EP0 complete lr=602b00e8` is the giveback return address, not the dispatch site;
  the actual giveback caller remains `0x602b3344` (state=2 at entry).

## 3. What the gap means

Two candidates remain for the 4.997 s between `TS complete-entry` and the next event:

1. **The original completion call blocks** (`orig = g_req_complete_orig`, the
   reference `uvc_ep0_comp` → `ep->ops->free_request`). This build did not log
   `g_req_complete_orig` or an after-orig timestamp, so it is not proven, but the
   gap starts exactly at that call.
2. **The IRQ thread/event loop does not process the pending status NRDY** for ~5 s
   after the completion returns (IRQ scheduling/wakeup), and only the host abort
   (Stop Endpoint/Set TR Dequeue at ~5.01 s) causes the device to complete/restart
   the status stage.

E0382 proved `do_control_status`/`start_trans` geometry is correct and issue no
warnings; the host xHC queued one control TD and waited until its timeout. Therefore
the remaining suspect is the completion callback path or the IRQ thread scheduling,
not the status arm itself.

## 4. Concrete fix design (to implement after this last probe)

Minimal, testable change in priority order:

1. **Stop hijacking `req->complete` for the diagnostic thunk.** In the fix build,
   restore the reference `req->complete` and remove the synchronous `orig(ep,req)`
   call from the IRQ completion path; keep GCRO/queue logging only. If the 5 s gap
   disappears, the thunk/orig call (free_request/printk) was the blocker.
2. If the 5 s persists with the original completion, **defer the reference
   completion/free_request to a tasklet/workqueue** scheduled after the IRQ giveback,
   so the status event can be processed immediately (must serialize with
   `dwc->lock`, no double-free).
3. Do not touch `do_control_status`/`start_trans` (correct per E0382); no status
   kick, no `lr` filter, no ops shadows, no gcguard.

The next run must first build the **fix candidate (not read-only)** and prove the
completion/IRQ path change in Unicorn where possible (thunk-free completion ABI,
request ownership), then one bounded hardware run.

## 5. State

Clean receipt (`stop_verified=1`, `teardown_verified=1`), 0CAA/MSC, no battery pull,
camera healthy (42 modules, no `usbg_video`, `/tmp_bt` baseline). Full suite
**1312 tests OK**; host ETL 528,949,248 B retained under
`artifacts/analysis/e0382-runb15roprobe/`.
