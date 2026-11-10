# E0298 - Safe OSD capture via im.elf's existing mapping; Sugilite buffer is not a display

Date: 2026-11-09. Read-only camera process-memory capture through the native
USB debugger. No camera mode switch, `/dev/stream` open, display write or SD
write was performed.

## Why this method

E0297 recorded that an external helper's `open("/dev/stream", O_RDONLY)` plus
`PROT_READ` mmap of OSD pages preceded a camera reboot. A safer path exists:
`im.elf` (PID 149) already maps the OSD buffers and the GRM pools through
`/dev/stream`. The host can read those existing mappings with the debugger's
ptrace `mem` operation. This performs only process-memory reads; it does not
open the display driver or write any camera state.

`/proc/149/maps` (read-only) contains, among others:

```
08a5f000-0aa5f000 rw-s 202e0000  /dev/stream   (gl_common, 32 MiB)
0bfd0000-0c066000 rw-s 23a80000  /dev/stream   (OSD A, 0x96000)
0cfdd000-0d073000 rw-s 23b16000  /dev/stream   (OSD B, 0x96000)
16fbb000-173bb000 rw-s 222e0000  /dev/stream   (mpMemoryHeap, 0x400000)
173ea000-175ea000 rw-s 22880000  /dev/stream   (mpTextHeap, 0x200000)
175f7000-17797000 rw-s 226e0000  /dev/stream   (mpMemoryHeap2, 0x1a0000)
```

## Observations

Read-only ptrace capture (`tools.research.capture_camera_osd_ptrace`,
4,064-byte chunks, 152 chunks per OSD buffer; 256 for gl_common):

* OSD A: 614,400 bytes, 607,746 nonzero,
  SHA-256 `7a535b09be2e370fda25091a3819289bf59d8f23e82ec0bb8030a43768c32906`.
  Decoded RGBA4444 (640x480) is a complete PlayMemories screen: phone/PC
  icons, "PlayMemories Mobile/Home", QR code, "Go To www.sony.net/pmx",
  "Don't show this again.", "OK". This is a real camera UI frame.
* OSD B: identical length and SHA-256
  `7a535b09...` - the two OSD buffers contain the same frame.
* gl_common + `0x1000` (the E0297 Sugilite colour-buffer candidate):
  1,036,800 bytes, 604,162 nonzero,
  SHA-256 `903f6910878ea1d11dc07a5b0e47b0a86ba58ca650aa700415a8557eae100b04`.
  Decoded as RGBA4444/RGB565 it is a repeated patterned/glyph-like buffer, not
  a rendered UI frame. The earlier 960x540 "screen" artifact from E0297 is an
  internal buffer and is **superseded as a display claim**.

The camera stayed responsive: the debugger answered `info` (PID 703, root) and
`/proc/uptime` remained consistent after the reads; no reboot occurred. The
riskier `/dev/stream` open method from E0297 was not repeated.

## Correction to the display contract

* Camera-verified display surfaces are **OSD A and OSD B**
  (PA `0x23A80000`/`0x23B16000`, 640x480 RGBA4444, E0074/E0044), now
  additionally confirmed by a full UI decode.
* `sugilite_color0` (PA `0x202E1000`) is retained as `role='internal'` only.
  `DisplayModel.select()` never presents it as a screen; a mapping containing
  only that buffer yields `None` and an explicit "no verified display surface"
  result.
* The 201M checkpoint maps only `gl_common` and one WBI window, not OSD A/B;
  therefore it has no verified display surface to present. The E0297
  `emulator-screen-sugilite_color0.png` is an internal-buffer diagnostic, not
  an emulator screen.

## Evidence and tooling

* Ignored captures: `artifacts/display/camera-ptrace/` (OSD A),
  `artifacts/display/camera-ptrace-both/` (A+B identical), and
  `artifacts/display/camera-ptrace-gl/` (OSD A + gl_common candidate), each
  with raw bytes, decoded PNGs and a manifest.
* New tracked tool: `tools/research/capture_camera_osd_ptrace.py`; tests:
  `tests/test_camera_osd_ptrace.py` (mapping parse, exact reads, missing OSD
  mapping, short-read rejection).
* Full suite after the display and USB work: **778 tests OK** (18.1 s).

## USB split workstream (Parts A/A2/A3/B/C)

The USB trigger was split into independent parts; all reports are under
`artifacts/analysis/e0299-*`:

* **A (record ABI):** `/dev/usb/event` records are `12 + len + ((-len)&3)`
  bytes: context u32, callback u32, subtype u8, length u8, context-word pad,
  payload. `read` is a raw ring stream; `ENABLE` registers a context id (the
  gate), not a subtype mask. Checkpoint contexts: `0x2D568` (172M) and
  `0x2B5C0` (260M). The 12-byte subtype-2 candidate is structurally verified.
* **A2 (subtypes):** `CUsbSvc::proc_kevent_otg` maps subtype 0..7 to CUSB
  events 0..7; **these events do not directly drive UsbControl**. UsbControl's
  FSM is driven by MWF/OSAL messages (`ProcessMsg`/`MsgId2EventId`/UFW).
* **A3 (decisive producer):** `usb_buspwr.ko` `VbusStateCb` emits a verified
  16-byte async message to queue `0x012002da` (`{0, raw_vbus, mapped, 0}`);
  a consumer is registered in the checkpoint. `usb_darwin.ko` emits 4-byte
  state messages to `0x012302d8`/`0x012303c8`. The exact
  `MSGID_SETCONFIG_MASSSTORAGE_EVT` id (0x0a4xxx family) and UsbControl's
  dynamic receive id remain unresolved.
* **B (injection):** `GuestUsbEvent.inject_record/validate/readable` with
  exact bytes, context gating, pad checks and raw-stream read; no invented
  connect semantics. The Lead's probe wiring (`inject_usb_event`/wake fd)
  is in place.
* **C (replies):** opt-in `reply_policy='verified-connect'` for buspwr/otgcore
  implements the evidence-backed replies (SET_CONFIG/SET_PARAM/SET_PORT_DESC/
  GET_INFO etc.) and stops with explicit boundaries on undecoded hardware
  queries (`GET_CURRENT_PORT_TYPE`, `GET_STATUS`, `SET_MODE`).

Bounded runs: the subtype-2 `/dev/usb/event` record (context `0x2B5C0`) was
accepted and woke the reader TID 1013, but produced no UI/OSD change. The
verified buspwr VBUS message to queue `0x012002da` was enqueued, but no
consumer was waiting (`woken=[]`) and no thread read it; the app reached
355.9M instructions with no boundary and still no OSD A/B mapping. The
missing contract is therefore **UIPC async callback delivery / the
libInfraUsbCmn consumer thread** (or the UI/USB service tier that owns it),
not the event record bytes. A host-forced callback call is not allowed.

## GPU identity correction

`libObj.so` (sha256 `60ffd2b0...`) self-identifies as DMP **SMAPH-S30**
(OpenGL ES 2.0) at file offset `0xFDF0F0`, next to the vendor/GLSL strings and
`es_set_command_buffer_addr`/`EGL_DMP_commandbuffer_attributes`. E0081/E0082's
**PICA200** register/ISA mapping is invalid for this device. The retained
command stream uses verified 8-byte framing (`header = 0xF000 | (index<<16)`)
with 566 packets in 17 runs; `0x10 = 0x12345678` is the only repeated
terminator candidate. Draw boundaries are command list A `0x40-0x680`, retarget
groups `0x8000-0x8100`, state list B `0x3000-0x3280`, and shader/uniform blocks
`0x15000-0x20040`. A bounded command/state model is possible, but a bounded
**rasterizer** is blocked: the SMAPH-S30 register meaning, draw trigger, colour
target/format, fragment shader and texture state would have to be fabricated.
No frame or pixel claim is made for the internal buffer.

## GRM pool policy and boot progress

The opt-in `GrmMaService(pool_policy='captured-e0044')` implements the six E0044
pools with per-pool allocation and explicit failures for unknown names/units;
the default single-`gl_common` policy is byte-identical. A fresh run with the
policy still requested only `gl_common` (open + six mallocs); it did not map
OSD A/B, so the policy alone does not instantiate the UI.

Two bounded boot gates were then found and fixed from real wrappers:
* `semtimedop` is syscall **312** in the a6400 glibc 2.11.2 wrapper
  (`libc-2.11.2.so` at `0xA2160`), not only 301. Both numbers are now
  serviced; the app's semtimedop calls succeed.
* the app calls `mkdir("/setting/gps", 0777)`; the camera (read-only `ls`)
  shows `/setting/gps` already exists. The opt-in `--setting-overlay
  observed-gps` answers `-EEXIST` for the observed `/setting` and
  `/setting/gps` directories only; other paths still stop.

With those two inputs, a resume from `boot-120m-grm-e0298.ckpt` reached
**312,382,269 instructions** without a new boundary (41 threads). It still did
not load `viewUnified2`/`/usr/share/app` resources or map OSD A/B. This is
consistent with the trigger analysis below: the app is waiting for a USB
connection, not merely for more instructions.

## OSD/USB trigger

Safe offline analysis of the camera maps, the firmware and the checkpoint
(`artifacts/analysis/e0298-usb-osd-trigger.md`) identifies the captured screen
as the **USB Mass Storage device view**: `/usr/share/app/viewUsbMassStorage.uxc`,
`global.xdb`, `lang.uxb`, `string_english.uxc` and `libObj.so` are mapped on
the camera; `viewUnified2.so` `DefRootView` has `CheckerUSBConnect`,
`ActionOpenUSB`, `ActionChangeUSBType` and `ActionOpenPMH`; `libUsbControl.so`
has the USB FSM and `:MSGID_SETCONFIG_MASSSTORAGE_EVT`. The trigger is a USB
port/VBUS connect with type Mass Storage; "Don't show this again." is only a
suppression flag. The 312M emulator state has USB initialised but idle: no
SET_CONFIG, `buspwr` port type 0, no pending `/dev/usb/event` record, and OSD
A/B are not mapped. The next experiment is the verified USB connect/event
record (task-4), not a host-drawn screen.

## Limits and next boundary

* One camera screen in its current mode; no claim that it is the emulator's
  future screen or that it matches a shooting/MSC mode pixel-for-pixel.
* The emulator does not map OSD A/B and the app has not instantiated the
  `viewUnified2`/USB MSC view.
* The next contract is UIPC async callback delivery / the libInfraUsbCmn
  consumer thread for queue `0x012002da` (and the UI/USB service tier), or
  decoding UsbControl's dynamic receive id and the exact
  `MSGID_SETCONFIG_MASSSTORAGE_EVT`; a host-forced callback call is not
  allowed. The event-record bytes and the buspwr/otgcore replies are ready.
* Do not repeat the E0297 `/dev/stream` open/mmap method.
