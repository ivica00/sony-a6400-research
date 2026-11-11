# E0329 — libosal_uipc receive queue protocol: why the emulated SETCONFIG envelope was not consumed

Date: 2026-11-11. Offline disassembly of live `libosal_uipc.so` (26,644 B,
SHA captured under `artifacts/hardware/live-libs/libosal_uipc.so`) + the E0328
emulator experiments. No camera access, no camera write.

## 1. Result

The OSAL_ERR assertion in E0328 is explained by the user-space OSAL queue
protocol, which the emulator's `osal_rcv_msg_tmo` model does not implement:

`osal_rcv_msg_tmo` (live Thumb 0x3ED8, 276 B):

- `tst.w r0,#0x8000` selects direct-kernel vs user-library path;
- calls helper 0x3604(queue-id) -> **user-space queue object** in r5;
- checks queue flags `[r5+4]` (`tst #2`, `tst #1`) and the local message head
  list `[r5+0xC]`;
- when a head is present: `r1=[head]` (next), `sb=0` (OSAL_OK),
  `head+=0xC`, `*arg_out = head` (the delivered message pointer is
  **head+0xC**), `[r5+0xC]=next`, unlock helper 0x1A10;
- when empty: `sb=-0x3FE` (OSAL_ERR), and if a timeout was supplied it builds
  a wait record at `r7` (`[r7+8]=handler`, `[r7+0xD]=4`, `[r7+0x18]=out arg`),
  calls 0x3A5C (queue/lock wait) and retries; the condvar/lock object is in the
  queue object.

`osal_snd_msg` (live 0x3C34): `r5 = payload - 0xC` (message head), reads queue
object flags `[obj+4]` (bit 3 = async/notify path), and manipulates the queue
head at `[obj+0xC]` / `[obj+0x10]`.  So **head = payload - 12 bytes**, the same
12-byte header that `GuestUipc.allocate_message` writes, but the *local queue
object* (userspace list head + wait/lock state) must also be created/updated.

## 2. Consequence

E0328's envelope allocation and `payload[0]=ObjMsg` layout are consistent with
the -12 byte head pairing, but a message queued only in the emulator's
`GuestUipc.message_queues` does not appear in the **user-space queue object**
that `libosal_uipc` inspects; a manual futex wake then drives the wrapper into
its error path, and the original debug build asserts in
`UFW::MsgReceiver::RcvMsg` (MsgReceiver.cpp:126).  The emulator must model the
user-space queue object (or drive the original `osal_snd_msg`/`osal_rcv_msg_tmo`
pair), not just the kernel-side queue list.

Boundary: **`libosal_user_queue_protocol_unmodelled`**.

## 3. Next step

1. Decode helper 0x3604 (queue-object lookup/creation from the OSAL id table),
   0x3A5C (queue wait/lock protocol) and the queue-object layout
   (`+4` flags, `+0xC` head/tail, cond/lock at the tail of the object).
2. Either model that object faithfully in `GuestUipc` (so enqueue updates the
   user-space head list and wakes the same condvar), or model the synchronous
   `osal_snd_msg -> osal_rcv_msg_tmo` pair end to end.
3. Then re-run the labelled SETCONFIG injection (`--uipc-inject-objmsg-setconfig-
   queue 0x00CA8192`) and observe the FSM event 0x13 dispatch.

No FSM transition or UVC/PTP function is claimed; physical load remains
excluded (debugger read-only only).  Full suite at this point: **952 tests OK**.
