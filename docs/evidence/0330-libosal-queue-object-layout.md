# E0330 — libosal user-space queue object layout (next modelling target)

Date: 2026-11-11. Offline disassembly of live `libosal_uipc.so` (26,644 B).
No camera access, no camera write. Follow-up to E0329.

## 1. Result

Queue-object handling helpers decoded:

- **0x3604** queue lookup: `0x33C4(queue_id)`; if not found, creates the
  object via `0x341C(queue_id)` and returns it.
- Object fields observed so far:
  - `+0x04` flags byte (`tst #8` async/notify path in `osal_snd_msg`;
    `tst #2` toggles the wait/list path in the receive helper);
  - `+0x08` **wait-record list head** (linked through `[record]` = next);
  - `+0x0C` **message head list** (head = payload − 0xC;
    `*out = head + 0xC` on receive);
  - `+0x18` pending waiter slot used by the send/notify helper
    (`[obj+0x18]=wait_record`, waiter flag `[record+0xD] |= 1`);
  - `+0x1C` used in the send path (`osal_snd_msg` reads it).
- **0x3A5C** (receive-wait registration): walks `[obj+8]` to the list tail,
  zeroes `[record]`, links `[tail]=record`; then if flags `#2` is clear and
  `[obj+0xC]` is non-empty, calls **0x3848** (immediate delivery path);
  otherwise returns without consuming (the caller then waits/sleeps).
- Lock/unlock around the object use helpers 0x16D8 / 0x1A10.

## 2. Why this matters

E0329 showed the assertion came from the user-space queue protocol. This
evidence gives the concrete object layout needed to model it: a faithful
`GuestUipc` model must update the **object's message head at +0xC** (not only
the kernel-side queue list), append/consume wait records at `+0x8..`, honour
flags at `+0x4`, and wake the object's wait list (0x3848 delivery path) from
the enqueue side.

## 3. Boundary

`libosal_user_queue_protocol_unmodelled` still stands: no user-space queue
object exists in the emulator for 0x00CA8192 (the emulator tracks queue lists
only), so the E0328 labelled SETCONFIG injection cannot be consumed yet and no
FSM event 0x13 is claimed. Remaining decode: 0x33C4/0x341C object table and
creation (object size, lock/cond fields), 0x3848 delivery path, and how the
kernel-side ioctl result is linked into the object (the receive helper sees a
message head after the kernel returns it).

## 4. Next

Decode 0x33C4/0x341C/0x3848 and the queue-object creation size, then extend
`GuestUipc` with an opt-in faithful user-space queue object (head list + wait
list + delivery) so the receive helper returns the message and `RcvMsg`
proceeds to `ProcessMsg`; re-run the labelled SETCONFIG injection.

Bounds unchanged: no camera write, no USB mode change, no fabricated FSM
transition. Test suite unchanged at **952 tests OK**.
