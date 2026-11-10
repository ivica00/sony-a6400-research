# E0304 — pre-MPR injectable state: VBUS delivery/completion observed; the event-record callback must match the state

Date: 2026-11-10. Offline original-firmware execution only; no camera/USB access,
no host UI/OSD and **no GUI frame**. Everything below is bounded by the listed
checkpoints/policies; the injected inputs are labelled experiments.

## Why this experiment

E0303 injected the verified VBUS UIPC body and the subtype-2 `/dev/usb/event`
record at instruction 231,909,376 — only 7,323 instructions before the
`/dev/nflasha4` MPR ioctl stopped the run. No proxy work could be observed.
This round searches the retained chain for an earlier resumable state on which
the same verified input can run for millions of instructions before MPR.

## Checkpoint survey (read-only unpickle)

| checkpoint | instruction | saved stop | resume result |
| --- | --- | --- | --- |
| `boot-e0302-stream2` | 185,772,548 | `memory_boundary` (tzset `pop`/literal-pool defect) | re-hits the same boundary |
| `boot-e0302-branch` | 186,000,000 | `instruction_budget_exhausted`, but the saved CPU context is the bad path (PC `0x5026EC2C`, SP `0x14FFE400`) | faults after 17 instructions |
| `boot-e0302-gles-table` | 185,358,896 | `unsupported_filesystem` (`/dev/stream2` open) | resumes, but still hits the same tzset `memory_boundary` at 185,772,548 |
| `boot-e0302-cont` / `boot-e0303-symbol-fix` | 224,338,158 | `syscall_boundary` (`exit_group(127)` in ld.so) | retry re-executes the exit; cannot advance |
| **`boot-e0301-live-receiver`** | **214,289,958** | `timeout` (clean) | **resumes and advances to the MPR boundary** |

The **fresh-path tzset re-verification fails**: a clean pre-fault resume
(`boot-e0302-gles-table`) with the current `0x5026EBC4/0x5026EC26` IT-clear
workaround still stops at the same `memory_boundary` (PC `0x5026EC2C`, write to
`0x502F924C`). The workaround only runs when the `pop` instruction itself is
executed; the stored bad-path context and the resume-after-`pop` case are not
repaired. Do not claim the tzset defect fixed.

## E0305 — verified VBUS delivery and completion (usable base)

Runner: `artifacts/analysis/e0305-run-live-vbus.py`; report
`artifacts/execution/e0305-live-vbus.json`; checkpoint
`artifacts/checkpoints/boot-e0305-live-vbus.ckpt`.
Resume from `boot-e0301-live-receiver.ckpt` with the E0303-G5 Path-1 policies
(`--uipc-pool-options kernel-e0301`, `--stream2-device open-only`,
`--nflasha4-device open-only`, USB devices driver-bound, verified-connect
replies, display contract) and the verified 16-byte VBUS body
`00000000010000000000000000000000` on queue `0x012002DA`.

Result: **232,049,966 instructions / 55 threads**, stop at the MPR ioctl
`0x80014123` (same read-only observation boundary). UIPC transactions show the
first observed real delivery and completion of that notification:

```
wait_cb_delivery  proxy 0, handle 4106, queue 0x012002DA,
                  callback 0x5BA034CD, user_data 0x2C2A8, msg 0x5033296C
free_msg          pool 0x012002DA by the original callback
wait_cb_completion proxy 0, message_touched=false, same handle/queue/message
```

The original consumer executed and freed its message; the model did not touch
or double-free it. This closes E0303's "handle-4106 delivery not yet observed"
item for the async path. It does **not** establish a USB FSM transition:
`UsbControl` (1018), `UsbBusPower` (1016) and `BusPower` (1022) remain
`blocked_futex`; `usb_otgcore.config` is still `None` (no SET_CONFIG);
`viewUnified2` is not loaded; OSD A/B are unmapped; no frame.

The original callback's relay in this state targets queue `0x008F013A`
(`snd_sync_msg` after delivery); that queue has **338 pending messages and no
registered consumer** in the stop state — a candidate missing consumer
contract, not yet identified.

## E0306/E0307 — event-record callback is a per-state pointer

`/dev/usb/otgcore` port descriptor at this base has word0 context **0x0002E878**
(190584) and callback word **0x562FB0DD** (`libInfraUsbCmn` base `0x562F0000`).
E0303's record bytes used callback `0x552FB0DD` (that checkpoint's layout).

* `e0306-live-both.json` (callback `0x552FB0DD`): the event reader woke and read
  12 bytes, then the consumer called the record's `+4` field — a wrong address
  here — and the run ended at **UC_ERR_INSN_INVALID** (PC `0x552FB0EC`,
  TID 1019). This proves the record callback is not validated against the
  consumer's registration; a stale pointer from another checkpoint is an input
  error, not a guest bug.
* `e0307-live-both2.json` (corrected record `78e80200ddb02f56020078e8`): reader
  TID 1019 read 12 bytes, `CUsbSvc::proc_kevent_otg` executed without fault,
  and the run reached **232,073,652** before the same MPR stop. No USB FSM or
  otgcore request appeared; subtype→event semantics remain experimental.

The VBUS-only and VBUS+event runs differ by ~23.7k instructions (the event
consumer path), not by a service transition.

## Boundary, limits and next

* All runs stop at the `/dev/nflasha4` ioctl `0x80014123`
  (`emmc_seq_get_erased_mem_cont`, 1-byte read-only query). MPR content and the
  erased-state byte remain unknown; nothing was fabricated. **MPR read-only
  content dump authorization is the shared GUI/USB gate.**
* The verified injection lane (VBUS) and the labelled experimental event lane
  are both usable from `boot-e0301-live-receiver.ckpt`; the MPR stop now occurs
  ~1.76M instructions after the injection instead of ~7k.
* Open contracts: the consumer/queue for the relayed buspower notification
  (`0x008F013A`), UsbControl's runtime dynamic receive id and the exact inbound
  SETCONFIG message (`{0x6103,0x0A4001,param 0x1006=0}`, E0303 U5), the buspwr
  port-type reply (`0xF209`), and the unresolved fresh-path tzset CPU defect.
* Opt-in otgcore function selection is now wired for runs:
  `--usb-function-policy descriptor-table --usb-configured-functions
  mass-storage` (default `legacy` unchanged; PTP/UVC rows stop at the explicit
  `descriptor_unresolved` boundary).

## Artifacts

* Runners: `artifacts/analysis/e0304-run-branch-vbus.py`,
  `e0304-run-gles-vbus.py`, `e0305-run-symbol-vbus.py`,
  `e0305-run-live-vbus.py`, `e0306-run-live-both.py`,
  `e0307-run-live-both2.py`.
* Reports: `artifacts/execution/e0304-branch-vbus.json`,
  `e0304-gles-vbus.json`, `e0305-symbol-vbus.json`, `e0305-live-vbus.json`,
  `e0306-live-both.json`, `e0307-live-both2.json`.
* Checkpoints: `boot-e0304-branch-vbus.ckpt`, `boot-e0304-gles-vbus.ckpt`,
  `boot-e0305-symbol-vbus.ckpt`, `boot-e0305-live-vbus.ckpt`,
  `boot-e0306-live-both.ckpt`, `boot-e0307-live-both2.ckpt`.
* Inspectors/summaries: `e0303-verify-checkpoint-policy.py`,
  `e0303-verify-uipc-migration.py`, `e0304-inspect-registers.py`,
  `e0304-inspect-gles-table.py`, `e0305-inspect-chain.py`,
  `e0305-inspect-live-receiver.py`, `e0305-inspect-stop-state.py`,
  `e0305-queues.py`, `e0305-after-delivery.py`, `e0306-fault-detail.py`,
  `e0307-detail.py`.

## Checks

Full suite **857 tests OK** (20.348 s) after the session/USB wiring change
(`--usb-function-policy`, `--usb-configured-functions`,
`emulator_session.usb_otgcore_options`); focused wiring+otgcore subset 46 tests
OK. Defaults remain `legacy`; no earlier replay behavior changes. This note is
offline evidence only: no camera, no GUI frame, no UVC/PTP function.
