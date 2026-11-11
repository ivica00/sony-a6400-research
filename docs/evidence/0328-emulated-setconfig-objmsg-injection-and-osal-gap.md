# E0328 — Emulated inbound SETCONFIG ObjMsg injection: reaches RcvMsg, OSAL wait model gap

Date: 2026-11-11. Emulator-only experiment; no camera access, no camera write, no
USB mode change. Inputs: live 8.2.6.0 checkpoint `boot-e0673-live-full2e.ckpt`
(557,079,079 instructions, service-idle) and the decoded MWF/UsbControl layouts
E0323/E0324/E0325/E0327.

## 1. Result

**Live receive queue confirmed:** live `libUsbControl.so` (94,176 B) ctor at
0x11750 constructs the receiver at `this+0x70` with `r1=0xCA` and the queue
literal 0x00CA8192 (literal pool 0x11938); `Main` (0x112C4) loops
`RcvMsg -> ProcessMsg(source,msg) -> ObjMsg::~ObjMsg`.

**Labelled emulated SETCONFIG ObjMsg injection (opt-in):**
- new CLI `--uipc-inject-objmsg-setconfig-queue` (+ optional
  `--uipc-inject-objmsg-wake-uaddr`);
- `InterpreterProbe.inject_uipc_setconfig_objmsg(queue, wake_uaddr=None)`
  allocates the ObjMsg image in the UIPC pool (obj `+0` body pointer, body
  `+4` category 0x6103, `+8` messageId 0x0A4001), allocates a 4-byte envelope
  whose word0 points at it, enqueues to the queue, and optionally wakes the
  receiver futex; provenance is recorded (`objmsg`, `body`, `envelope`, zeroed
  param map, "not a captured kernel message").
- `build_setconfig_objmsg_image()` builds the image from the decoded layout;
  tests cover layout/validation.

**Run e0680** (no wake): envelope queued (queue 0x00CA8192, obj 0x50359C4C),
`woken=[]`, run continued to 628,993,333 with boundary null — receiver stayed
`blocked_futex`.

**Run e0681** (with `wake_uaddr=0x10FFED3C`): `futex_woken=1`, UsbControl
resumed into `RcvMsg`, then **fail-closed assertion**:

```
im.elf: ufw/MsgUtil/MsgReceiver.cpp:126:
OSAL_ERR UFW::MsgReceiver::RcvMsg(OSAL_ID*, MWF::ObjMsg**):
Assertion `0' failed
```

then `syscall_boundary` (tgkill 1000,1018,SIGABRT; pc 0x5024...; run stopped at
557,668,465). The queue still contained the envelope, i.e. the OSAL receive
path did not consume it as a valid message.

## 2. Interpretation (no success claimed)

The emulated notification reached the original `RcvMsg` function, but the
emulator's **OSAL queue-wait/wake semantics are incomplete**: a direct futex
wake is not the same as the kernel/OSAL `snd_msg` wake. `osal_rcv_msg_tmo`
(emulated ioctl 0x80000007) returns a blocking marker for timeout -1 without
registering the thread as a queue waiter; a manual futex wake then resumes
`RcvMsg` with an OSAL error, which the original debug build asserts on.

Boundary: `uipc_osal_rcv_wait_semantics_unmodelled` — the message is not
consumed, no FSM event 0x13 / mode transition is claimed.

## 3. Next step

Model OSAL receive blocking properly: when `osal_rcv_msg_tmo(timeout=-1)` finds
an empty queue, register the thread in the UIPC queue-waiter table keyed by the
queue id; `enqueue_message`/`handle_snd_msg` would then wake exactly that waiter,
and the retried receive returns 0 with the message pointer (matching
`RcvMsg`'s success path). Then re-run the labelled SETCONFIG injection and
observe whether FSM event 0x13 dispatches.

## 4. Code/tests

`inject_uipc_setconfig_objmsg` in `interpreter_probe.py`;
`build_setconfig_objmsg_image` in `mwf_objmsg.py`;
session/CLI wiring (`--uipc-inject-objmsg-setconfig-queue`,
`--uipc-inject-objmsg-wake-uaddr`); tests `tests/test_setconfig_objmsg.py`.
Full suite: **952 tests OK**. Runs: `artifacts/execution/e0680-live-setconfig.json`
(no wake), `e0681-live-setconfig2.json` (wake + assertion),
checkpoints `boot-e0680`/`boot-e0681`.
