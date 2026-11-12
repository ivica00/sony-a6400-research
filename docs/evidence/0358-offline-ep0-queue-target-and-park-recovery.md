# E0358 — Offline before Run B4: EP0 queue target traced into dwc3 (not gadgetcore); daemon park-recovery implemented

Date: 2026-11-11. **Offline only** (two parallel workstreams; no camera/USB/module load/mode switch/SD or flash write, no GitHub push).
Answers E0357's open question and removes the battery-pull mechanism from the next run.

## Part 1 — what stepping into the EP0 `queue` target reveals

Reference: `artifacts/analysis/e0358-gadgetcore-ep0/REPORT.md`; a6400 `vmlinux.bin`
SHA-256 `12eeec82…` (`file_off = VA − 0x60108000`).

1. **The queue target is the UDC, not gadgetcore.** There is no `usb_gadgetcore.ko`
   (gadgetcore is built in at `0x602b81cc..0x602b8f38`). Its `g_bind` (`0x602b83f4`)
   only stores the gadgetcore manager in `ep0->driver_data` (`ep0 = gadget+0x14`) and
   preallocates a request; it never installs gadgetcore operations on `ep0`.
   `gadget->ep0 = dwc->eps[0]` (`dwc+0x164`, gadget base `dwc+0x150`), and
   `ep0->ops = dwc3_gadget_ep0_ops` (`0x603dfb88`), whose `+0x10` queue slot is
   **`dwc3_gadget_ep0_queue 0x602b2ad0 → __dwc3_gadget_ep0_queue 0x602b26ec`**.
2. **(a) Validation:** there is **no caller/client/interface-handle check** — the ABI
   is `(ep, req, gfp)`. It validates only structural EP0 state: `ep->desc != NULL`
   (else `-ESHUTDOWN -108`), `dep->request_list` empty (else `-EBUSY -16`),
   `dwc->gadget_driver != NULL` (else `-108`); then the dwc3 ep0 state machine decides
   whether to arm a transfer.
3. **(b) wIndex 1 vs 2:** gadgetcore's class dispatch matches
   `(desc.config, desc.interface)` against `(gcore+0x74 active config, wIndex low byte)`
   (`0x602ba05c..0x602ba074`), so `wIndex=2` selects the VS shadow and `1` the VC
   shadow. **But `core_cb_class` never reads its r0 argument** and always uses the
   singleton `this_ex` reply buffer (`this_ex+0x1C`) and the same `ep0` in r2 — the
   reply buffer/length/queue target are identical for `wIndex` 1 and 2; only the
   matched shadow node and the E0357 wire→native translation differ.
4. **(c) Return codes:** `-ESHUTDOWN`/`-EBUSY` as above; **otherwise 0 on every path,
   including three that arm NO transfer** (dep flag bit5 with `dwc+0x2e0!=2`; `dwc+0x2d8`
   bit5 with `dwc+0x2e0!=3`; all state bits clear fall-through). It sets
   `req->status=-EINPROGRESS` only on the arming path and ignores start/control-data
   errors (warn-only). **Run B3's class result 0 therefore does not prove the reply was
   ever submitted.**

**This refutes the E0357 framing that "gadgetcore dropped the reply": gadgetcore never
owns EP0 queueing.** The silent no-transfer branch is now a measurable hypothesis.

- Inner-queue logging: the slot is a runtime function pointer and the reference imports
  no queue symbol, so wrapping is impossible without changing EP0 identity. Implemented
  the safe read-only probe instead: `a6400_uvc_ep0_snapshot()` in
  `tools/native_camera/uvc_callback_bridge.c` logs `CLASS ep0-pre`/`CLASS ep0-post` on
  CLASS only — queued req buf/len/dma/complete/context/status, `ep0 desc/ops/queue slot/
  dep_flags`, `dwc+0x170/0x2b0/0x8c`, `dwc+0x2d8/0x2dc/0x2e0`, eps0/eps1 flags+list. No
  pointer substitution, no kernel writes.
  Module: `artifacts/native/uvc-transport-e0358-ep0probe/usbg_video_a6400_shared_candidate.ko`,
  **79,000 B**, SHA-256 `b21325d9391253ad4d4c10760a9745de31f2c19226f19965ca60d4028002c695`,
  transport audit `offline_module_audit_passed` (117 checks / 8 skips / 0 failures).
- Unicorn (new harness stepping the real `0x602b2ad0`/`0x602b26ec` bytes with synthetic
  dwc3 objects): selector **23/23**, bridge **12/12**, reference-class **10/10**,
  queue-path **8/8**, reference-handler→real-queue **6/6**, exit 0
  (`artifacts/analysis/e0358-gadgetcore-ep0/unicorn/`). The integration case reproduces
  Run B3's signature: class returns 0 with **no transfer armed**.

## Part 2 — daemon park-recovery (battery pull elimination)

Reference: `artifacts/analysis/e0358-park-recovery/README.md` / `evidence.json`.

1. **`state=-1,-1,-1,-1` is the daemon's sentinel, not module data.**
   `camera-daemon/src/runner.c` `a6400_runner_stop_verified()` pre-fills `state[0..3]=-1`;
   if the STOP ioctl (`0xe001`) fails it returns 0 **without** issuing `0x8010f022`, so
   the receipt shows four `-1`s. The module STOP failed because
   `cleanup() → session_end() → a6400_uvc_soft_disconnect()` hit one of the six silent
   early gates (phases 1–4: unconfigure rc, bridge in-flight/started, endpoint-map
   residual, UDC-down quiesce). B3's `A6400K.LOG` confirms the teardown entered
   phase-1 (`reference STOP iface=2 count=1`) and never printed `[a6400_td] done`, so it
   returned at a silent gate — consistent with the wedged uncompleted GET_CUR data
   phase, though B3 cannot name which of 1–4 (no printk). **Erratum:** the 181 TIDs were
   the publish-attestation scope already resumed at publish (`publish_resume rc=0`);
   `freeze_tid_count=181` is a historical count, **not** a park-time frozen set.
2. **Recovery implemented** (clean `stop_verified=1` path untouched): evidence first —
   flush `A6400K.LOG` and rewrite `A6400RCPT.JSON` with `status=degraded_teardown`;
   read-only `0x8010f022` query; **exactly one** bounded STOP retry; verify the four
   state words are zero; freeze → `HOOK_RETIRE` → **always resume**; close. Success:
   `status=degraded_teardown`, `exit_code=5`, `teardown_verified=1`,
   `stop_verified=0` (the failed gate stays visible), `stop_attempts=2` plus a full
   `recovery.*` block. Failure parks as before but the SD evidence is already written.
   Source-verified ABI fact: `HOOK_RETIRE` only removes the entry hook and is refused
   while the session is held, so **STOP retry first** is the only allowed order.
3. Daemon: **630,536 B**, SHA-256 `990475753ecf20e02a9b5c7b095a74606bf72c710271148d939f7edd910b2f16`;
   host tests **474/474** (399 old + 75 new), ARM static build. `--no-park-recovery`
   restores the old immediate park.

## Verification

- Full suite: **1312 tests OK** (Lead final run, `artifacts/analysis/e0358-lead-suite.log`).
- Module audit 117/8/0; Unicorn harness exit 0; host tests 474/474.
- E0351/E0357 receipts untouched; no camera/USB access in either workstream.

## What Run B4 should show (with E0358 module + recovery daemon)

`A6400K.LOG` should contain `CLASS translated wire_iface=2 idx=0002 -> native idx=0001`,
then the `CLASS ep0-pre`/`ep0-post` pair around `CLASS entry rt=a1 req=81 val=0100
idx=0002 len=001a`, with `ops=… queue=602b2ad0`, live `state=`, `next=`, `event=`,
`dep_flags`, and — if the reply is queued — `pending req … len=001a complete=<uvc_ep0_comp>
status=-115`. Decision rule: if post `next` (`dwc+0x2dc`) != 1 and `eps1` bit 0x10 is
clear, the queue returned 0 via a no-transfer branch (identify from state/event/dep_flags,
then fix that branch); if `next == 1` and `eps1` BUSY is set, the transfer was armed and
the remaining failure is post-submission (DMA/completion/usbvideo). A following
`SET_CUR` means GET_CUR finally succeeded. If the teardown again fails, the daemon must
now write `status=degraded_teardown`, run one STOP retry, retire/resume and return the
camera to native `054c:0caa` without a battery pull.

## Limits

Synthetic UDC objects in Unicorn (offsets from disassembly, DMA submission stubbed), so
Unicorn cannot say which silent branch was live; only Run B4's `ep0-pre/post` dump can.
The STOP retry can fail at the same silent phase; a second attempt is not permitted
(one bounded retry, then park).
