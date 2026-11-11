# E0337 — Emulator UVC/PTP preparation round: SETCONFIG dispatch completed to 0x0A4002 broadcast

Date: 2026-11-11. Team round (7 teammates) + Lead integration. Emulator-only: no
camera access, no camera write, no USB mode change, no GitHub push.

## 1. Result

The inbound SETCONFIG lane now executes through the original code beyond the
E0335 point:

**e0687** (resume `boot-e0673-live-full2e.ckpt`, labelled ObjMsg built with a valid
Param 0x1006 and allocated from the **guest OSAL allocator**, posted through the
libosal local queue):

- guest allocation: ObjMsg image via vpool, envelope via fblock (allocator
  inspected/planned/verified; counter and free lists consistent); local post
  `futex_woken=1`.
- dispatch trace TID 1018:
  - `UsbControl::ProcessMsg` msg=0x504AA... cat **0x6103**, messageId **0x0A4001**
  - `GetMessageId` → 0x0A4001
  - `MsgId2EventId` → **event 0x13 (19)**
  - `UFW::Fsm::DispatchEvent(event 0x13)`
  - **`GetMessageId` → 0x0A4002 (671746)**, twice, on a message at TLS stack
    0x10FFED... — the event handler built and broadcast the reply/notify
    message `{cat 0x6103, msg 0x0A4002}` (matching E0310's decoded
    `SetCateIdMsgId(0x6103,0x0A4002)` broadcast).
- The run continued to **557,164,099** and stopped at
  `unsupported_filesystem: open_flags_not_read_only_subset` for **`/dev/tty`**
  (flags 0x902 = 2306). This is the next downstream boundary (a console/log sink
  open inside the notify path), not a UVC/PTP contract failure.

**No UVC/PTP mode transition or frame is claimed.** The inbound message chain is
now verified end to end to event dispatch + reply broadcast.

## 2. New evidence-backed pieces (this round)

| Area | Deliverable |
| --- | --- |
| SETCONFIG Param | `mwf_objmsg.build_setconfig_objmsg_image` now emits a valid ParamMap + `ParamStd<int,7>` funcTable (live libMWF base 0x53660000, funcTable **0x536A067C**, verified in checkpoint memory); typed `MsgUtil::GetInt32` chain decoded (type gate requires the funcTable, not just the value) |
| Guest allocation | `guest_osal_alloc.py` (44 tests): fblock/vpool planner, allocator inspection, fail-closed on foreign/corrupt lists; dry-run on the real checkpoint returns allocator exactly to baseline after modelled free |
| Local post | `local_queue_post.py` (45 tests) + probe wiring; e0686/e0687 delivery/wake verified |
| Sync-lane analysis | `artifacts/analysis/e0336-local-sync-lane.md`: physical USB-event path is **sync first** (`EventListner → SendEvt → osal_snd_sync_msg → funcOsalSyncCb → preProcess`), then async `PostMsg → osal_snd_msg → RcvMsg`; TLS stamp on TID 1019; keep e0687 async post as labelled second-stage proof |
| Host enumeration | `usb_host_enum.py` (17 tests): hash-pinned 173-byte UVC+PTP descriptor (PTP 3 EP, VC 0 EP, VS 1 EP; IAD first 1 count 2), `plan_set_configuration(1)` → `{0x6103,0x0A4001,param 0x1006=0}` / event 0x13 |
| usbg_video gaps | `usb_video_contract.py`/`guest_usb_video.py` extended (27 new tests): ctx+0x2D external writer, 0xD0 request object, 0x24 DMA-info, buffer table/blob bounds, phys-buffer RPC builders/parser, frame-source refusals; explicit unresolved boundaries |
| ZV-E10 overlay | enablement/overlay hygiene (24 tests): component hashes, vermagic, API symbols, devno 248:32/33 model, load authorization; readiness **blocked**, executable **False** always |
| PTP | controls/liveview hardening (13 new tests): property decodings/types/ranges, unknown≠success, response table, recovery/lifecycle/teardown plan helpers |

Full suite at this point: **1179 tests OK** (before the final integration patch;
after wiring: 1179 OK).

## 3. Remaining boundaries for "UVC/PTP mode"

1. `/dev/tty` open (flags 0x902) in the notify/log path — needs an explicit
   opt-in console/log sink contract (or a decoded reason) before continuing past
   e0687.
2. Physical producer fidelity: deliver a `/dev/usb/event` record so the guest
   runs the sync lane itself (bridge subtype→ObjMsg-id table at
   libUsbControl 0x12E54/0x13054 still unobserved); no host-calling of guest
   callbacks.
3. `usbg_video` external ctx+0x2D writer, 0xD0/0x24 object contents, buffer
   table/blob producers, JPEG/DMM frame source remain unresolved.
4. ZV-E10 overlay remains data-only: no load authorization, node creation
   mechanism open.
5. Physical UVC remains 0% under the read-only scope (modules absent; no
   install).

## 4. Reproduce

- Runner: `artifacts/analysis/e0687-run-live-param-alloc.py`
- Report: `artifacts/execution/e0687-live-param-alloc.json`
- Checkpoint: `artifacts/checkpoints/boot-e0687-live-param-alloc.ckpt`
- Flags: `--uipc-local-post-setconfig-object 0x504305E0
  --uipc-local-post-waiter 0x10FFED28 --uipc-local-post-guest-alloc
  --uipc-local-post-libosal-base 0x50030000
  --uipc-local-post-libmwf-base 0x53660000 --trace-usbcontrol-dispatch`
