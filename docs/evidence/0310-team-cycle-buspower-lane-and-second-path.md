# E0310 — team cycle: the buspower 0x012002DA lane is a power lane, not the USB-connect path

Date: 2026-11-10. Four-teammate offline cycle (Lead + usb-wait-analyst,
msg-producer-analyst, receive-id-analyst, usb-harness-runner). No camera/USB I/O,
no source edits in this cycle, no fabricated messages or host-called callbacks.
**No breakthrough yet;** this note preserves the corrected map so the next cycle
does not repeat dead ends.

## 1. Breakthrough definition (Lead)

PASS = after a verified input, BusPower local-queue waiter `0x5E26ED3C` and/or
UsbControl waiter `0x5D23ED3C` leaves its wait (new FUTEX WAKE), or
`usb_otgcore.config` is set / `viewUnified2` or OSD appears. A wake followed by a
re-wait at the same address is not failure (stack frames are reused); the
discriminator is a **new WAKE count** on those flags relative to the retained
baseline (`artifacts/analysis/e0310-verify-runs.py`).

## 2. What changed vs E0309

* E0309 said the three USB threads were "not on a queue". They are:
  `UsbControl` → OSAL **local** queue `0x00CA8192` (waiter `0x5D23ED28`, futex
  `0x5D23ED3C`); `BusPower` → local queue `0x012282F6` (waiter `0x5E26ED28`,
  futex `0x5E26ED3C`); `UsbBusPower` → local queue `0x012182EB` (futex
  `0x5C23ED54`). `LR=libosal_uipc+0x50AF` is `do_sleep_tmo`'s
  `SYS_futex(FUTEX_WAIT_PRIVATE)` — a userspace local-queue condvar, not a
  kernel UIPC wait (`artifacts/analysis/e0310-usb-wait-primitive.md`).
* UsbControl object `0x0002E198`; embedded `UFW::MsgReceiver` at `0x0002E208`
  (id16 `0x00CA`, queue `0x00CA8192`, filter 0). Inbound SETCONFIG is
  `{CategoryId 0x6103, MessageId 0x0A4001, param 0x1006 int 0}`; expected
  transition `SetCateIdMsgId(0x6103, 0x0A4002)` broadcast to `UsbControl+0x04`
  notify list (currently `{0x012282F6 BusPower, 0x00C881BB Hotplug}`)
  (`artifacts/analysis/e0312-report.md`).
* Local-queue ABI is fully mapped (bit-15 paths, queue block fields, 12-byte raw
  header, waiter context, `0x3848` dispatch → `0x32B0` delivery → futex wake).
  Host `--uipc-inject-queue 0x00CA8192` cannot wake TID 1018; a null-ObjMsg
  local post is unsafe. The local-post plan is kept as boundary evidence only
  (`artifacts/analysis/e0315-report.md`).
* `0x008F013A` (530 pending) is the UFW receiver source-mismatch relay queue and
  a ULOG/trace kernel queue, **not** UsbControl's inbound path
  (`artifacts/analysis/e0312-report.md`, `e0310-usb-wait-primitive.md`).

## 3. The 0x012002DA buspower lane is a dead end for USB connect

`RsrcUsbBusPowerCB` (`libUsbBusPower+0x3DCC`, SHA `b06225bf…`) reads body words
`[0],[4],[8],[0xC]` and calls `SendEvent2Me(0x120,w0..w3)` on local
`0x012182EB`; `ReceiveEvent` (`+0x4038`) TBH table dispatches subtypes 0..7.
Only subtype 1 (w1=0) and subtype 7 (w1=0) call `SendEvent2UpperLayer(0)/(3)`,
but `BusPower::InfraUsbBusPowerCb` (`libBusPower+0x5100`) guards `payload[0]==2`
and returns without action for 0/3. Only `SetPowerSupplyState`'s event 2 is
processed — a power-supply lane (`0x6107/0x0A1005` broadcast + `0x00920572` sync),
not USB connect. `usb_buspwr.ko` is the only producer of `0x012002DA`; the
verified body `00000000010000000000000000000000` = `VbusStateCb(raw=1,mapped=0)`
→ subtype 0 present-VBUS power path. **No 0x012002DA body reaches
`Configure 0x58F4` / `StartGadget 0x59F8` / `StopGadget 0x5AFC` or wakes
`0x012282F6` / `0x00CA8192`** (`artifacts/analysis/e0316-...md`).

Trace confirmation (`artifacts/analysis/e0318-trace-analysis.txt`): with the
verified body, `SendEvent2Me` is hit (event `0x120`, body `{0,1,0,0}`),
`ReceiveEvent` runs as TID 1016, one `FUTEX_WAKE` on `0x5C23ED54` and a
`0xF203/0xF204` pair occur; `SendEvent2UpperLayer` is **never hit** (HIT=False).
Verified bodies `{1,0,0,0}` / `{7,0,0,0}` would hit the upper send but are inert
at the guard — useful negative controls, not connect inputs.

## 4. Second forward path (now the critical lane)

BusPower has no kernel-UIPC callback registration at 308.6M; it receives
in-process on `0x012282F6`. Observed command path:
`ProcessCateUsbControl 0x470C → DispatchEvent 0x4762 → UsbCtrl_StartBusPowerFunction
0x5DC0 → Configure 0x58F4 + StartGadget 0x59F8` → `ObjMsg(0x6103, 0x1000/0x1005)`
to UsbControl queue `0x00CA8192`. The missing evidence: (a) sender + message for
UsbControl's kernel sync queues `0x00CA0288` (handle 4109) and `0x00CA01A4`
(handle 4110); (b) sender of Category-0x6103 to BusPower `0x012282F6`; (c)
BusPower `s_stateTbl` (0xF44C) event index that runs `StartBusPowerFunction`;
(d) `/dev/usb/event` subtype→event mapping (TID 1019 reads fd 9). Tasks 10/11
are decoding exactly these.

## 5. Other lanes (E0311, task-9)

* `0x00A3035A/0x00A3035B` are libdig_level's internal request/reply pair; the
  startup handshake is incomplete in the replay (create_thread waits for a
  ready message that the main thread only sends after a first command), and
  libdig registers its API callbacks after that handshake. libObj's
  `InputService::startDigitalLevelNotify` (`0x012F0335`) and the DIAG catalog
  dispatcher (`0x00A00349`) are the in-image callers; task-9 is decoding the
  im.elf/libIMDB entry gating that would invoke them.
* `0x012C032F` is a receiver-only date/event **server** queue in the booted
  image (no sender anywhere in firmware; reply queue taken from `[msg-4]`); an
  external client is missing, not a boot gate.

## 6. Status and next

No PASS yet. Current cycle in flight: task-10 (`/dev/usb/event` connect lane and
UsbControl kernel sync senders), task-11 (BusPower FSM start/configure inbound
event and trigger), task-9 (im.elf/libIMDB gating), plus task-8 negative-control
experiments. No source/test changes this cycle; full suite remains **874 tests
OK**. Nothing in this note is a UVC/PTP function or GUI frame.
