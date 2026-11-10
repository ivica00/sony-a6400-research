# E0303 — USB/UIPC/otgcore contracts ready for UVC/PTP (short note)

Date: 2026-11-10. Inputs: extended 55-thread checkpoint `boot-e0303-symbol-fix3.ckpt`
(231,909,376), current UIPC/driver evidence; no camera/USB was used for this note.

- **USB event (ready, opt-in):** exact `/dev/usb/event` record shape and injection are
  emulated; in this state context `0x2E878`, callback `0x552FB0DD`, subtype 2, event reader
  TID 1019 (`78e80200ddb02f55020078e8`). The exact callback differs from E0299 states; the
  subtype→event meaning is still experimental, so this is a labelled input, not a proven MSC trigger.
- **buspwr VBUS (ready, opt-in):** verified producer queue `0x012002DA`, 16-byte
  `00000000010000000000000000000000`; consumer handle 4106 (callback `0x5BA034CD`,
  user_data `0x2C2A8`). The injection wakes the four proxies; the required
  `sync_cb_delivery`/`sync_cb_completion` for handle 4106 has not yet been observed.
  **E0304 update:** on the pre-MPR base (`boot-e0301-live-receiver.ckpt`) the async
  path is now observed as `wait_cb_delivery` → original callback `free_msg` →
  `wait_cb_completion` (handle 4106, message untouched by the model); the run still
  stops at the MPR ioctl with no USB FSM transition. See
  [E0304](0304-preboundary-usb-injection-and-vbus-delivery.md).
- **Generic UIPC completion (`kernel-e0303`, opt-in):** multiple async consumers per queue,
  broadcast delivery from the verified `0x7000..` slot range, sync queue `0x009c015b` through the
  original wrapper tuple, and allocator-driven CONNECT fourth word / dynamic IDs (no hardcoded id);
  unresolved: kernel consumer order, broadcast refcount/free timing, multiple sync registrations.
- **otgcore/gadget (ready, opt-in):** verified 64-byte SET_CONFIG layout and function-descriptor
  table; Mass Storage row is the verified baseline (`08/06/0x50`, 2 bulk endpoints), PTP/UVC rows
  are explicitly marked placeholders with `descriptor_unresolved` boundaries; no silent success.
- **MSGID (ready):** `MSGID_SETCONFIG_MASSSTORAGE_EVT = 0x0A4002`; the real inbound switch is
  `{MessageId 0x6103, CategoryId 0x0A4001, param 0x1006 = 0}` → broadcast `{0x6103, 0x0A4002}`.
  PTP reuses the path with param 11 → `0x0A4003`; UVC uses `MSGID_SETINTERFACE_EVT 0x0A4005`.
  The dynamic 16-bit receive id lives at `[senderObj+0x10]`; its concrete runtime value is unresolved.
- **Media buffers (mapped, not reusable yet):** stream2 ioctl `0xC0047805` + mmap shape and the
  mcmn/PTP path are mapped; a UVC/PTP buffer contract needs the six ordered contracts in
  `artifacts/analysis/e0303-ptp-uvc-media-buffers.md` (stream2 registration/mmap, ownership,
  lifetime, mcmn read, UVC frame source/DMA).
- **MPR observation:** the 4-byte guest buffer at `/dev/nflasha4` ioctl `0x80014123` was captured
  (`0000f0e3`), LR `0x5590F30B`, SP `0x5A1DE3CC`, TID 1012; content was not returned or invented.
- **Exact boundary:** all runs stop at the MPR ioctl `0x80014123` at instruction 231,916,699
  (55 threads). OSD A/B are not mapped, `viewUnified2` is not loaded, and no OSD/GUI frame exists.
- **Defaults unchanged:** every contract above is opt-in; full suite **854 tests OK** (18.1 s).
- This is transport/descriptor readiness only: **UVC/PTP does not function** in the emulator yet.
