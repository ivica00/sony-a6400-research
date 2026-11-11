# E0334 — Sync callback lane decoded as USB adjustment channel; ADJ packet ABI exercised

Date: 2026-11-11. Team round (3 agents) + Lead integration. Emulator-only: no
camera access, no camera write, no USB mode change, **no GitHub push**.

## 1. Result

The E0332 boundary `sync_callback_packet_format_unmodelled` is resolved, and the
E0332 expectation was wrong:

- `0x00CA0288` (handle 4109) is the **USB adjustment command channel**
  (`UFW::AdjBase::funcOsalSyncCb`, live libUsbControl base 0x56440000, offset
  **0xB0DF**, 156 B). It expects a raw **0x140-byte `UFW::OsalRequestPacket`**,
  not an ObjMsg.
- `0x00CA01A4` (handle 4110) is `UsbControl::funcInputGetCb` (offset
  **0x12A87**, 108 B): input/ jack query packet (word0=0, physical key code at
  +4, status out at +0xC).
- Neither callback posts an ObjMsg / `MsgSender` message to the local queue.
  E0332's injected ObjMsg therefore failed the ADJ packet-id check and returned
  `0x81`, exactly as observed.

## 2. ADJ request ABI (h4109, decoded)

From live `libUsbControl.so` `.dynsym` + instruction evidence (E0333):

| Offset | Size | Meaning |
| --- | --- | --- |
| +0x00 | u8 | phase: `0x01` process_start, `0x04` finish_send_data, `0x10` finish_receive_data |
| +0x01 | u8 | result: `0x80` dispatched, `0x01` handler OK, `0x81` id/arg reject, `0x82` error |
| +0x02 | u16 | echo (request/response) |
| +0x04..+0x0F | - | response header (cleared in the response copy) |
| +0x18 | u16 | **packet id, must be 0x0701** |
| +0x1A | u16 | subcommand 1..7 (`usb_serial_dat`, `usb_set_port`, `usb_get_port`, `usb_test_vbus`, `sysad_sel`, `write_customer_hash256`, `usb_buspower_supply_control`) |
| +0x1C | u8 | subcommand argument |
| +0x1D.. | - | subcommand data |
| response: +0x00 | u8 | response type (0x08 for process_start) |
| response: +0x0C | u32 | value |
| response: +0x10.. | - | response payload (in-place) |

Callback ABI verified in live `libosal_uipc` dispatcher (Thumb 0x3168):
`callback(message_payload, registered_user_data)`.

## 3. e0685 experiment (ADJ packet, read-only subcommand)

Injected `build_adj_process_start_request(3)` (320 bytes: phase 1, id 0x0701,
subcmd 3, arg 0) into `0x00CA0288` with `kernel-origin` delivery:

- proxies woke (`woken=[1001,1002,1003,1006]`); `wait_cb_sync_delivery` and
  `wait_cb_sync_completion` for handle 4109 (proxy 0, tid 1001).
- checkpoint packet diff (320 B in vs out): **5 bytes changed** —
  `+0: 0x01 -> 0x08` (process_start response type),
  `+1: 0x00 -> 0x81` (reject), `+0x18..+0x1A` (id/subcmd) cleared to 0.
- run reached 674,712,489; `boundary = null`; no fault.
- dispatch hooks (`ProcessMsg`, `GetMessageId`, `MsgId2EventId`, FSM
  `DispatchEvent`) recorded **0 hits** — consistent with this lane being
  adjustment control, not SETCONFIG.
- `--uipc-inject-objmsg-packet-hex` + `--trace-usbcontrol-dispatch` worked as
  designed; hook resolution used the resumed module base (libUsbControl
  0x56440000; MWF base 0x53660000).

The reject (`0x81`) is a handler/subcommand validation, not a transport
failure: dispatch was entered (response type written) and the subcommand
returned id/arg reject. Which arg value subcmd 3 accepts is still unknown
(e.g. port/arg semantics); the request field names beyond the decoded offsets
are handler-derived and not captured from a real sender.

## 4. Corrected model for the SETCONFIG lane

- Local queue `0x00CA8192` (bit 15 set) is registered in
  `UsbControl::PreInit` with `UsbControl::funcOsalSyncCb` (thunk -> `preProcess`
  0x123B4); libosal local registration record at **0x504305C0**
  (`+0x14` callback 0x5645261D, `+0x18` user_data 0x2E1B0).
- The missing delivery is the original in-process send path:
  `preProcess` reads `[msg]=cmd ObjMsg`, `[msg+4]=reply msg`, then
  `PostMsg -> RcvMsg -> ProcessMsg -> DispatchEvent -> MsgId2EventId
  0x0A4001 -> event 0x13`.
- Therefore the next model is the **libosal local-queue post** (queue object
  update in guest memory + futex wake), not the adjustment callback lane.
  Host enumeration should deliver the evidence-derived ObjMsg envelope through
  that local post path.

## 5. Evidence/verification

- `src/a6400/execution/usb_sync_callback.py` + `tests/test_usb_sync_callback.py`
  (31 tests, builder/decoder/refusals).
- `src/a6400/execution/interpreter_probe.py`: opt-in observe-only dispatch hooks
  (`trace_usbcontrol_dispatch`) and `inject_uipc_setconfig_objmsg(...,
  packet_hex=...)`; `tools/research/experiment_ui_boot.py` flags
  `--trace-usbcontrol-dispatch`, `--uipc-inject-objmsg-packet-hex`.
- `tests/test_interpreter_probe.py` +20 tests. Full suite: **1008 tests OK**.
- Post-path checkpoint verification: `artifacts/analysis/e0333-postpath-analysis.md`
  (callback executed reject prefix only; proxy tuple preserved; no other side
  effects; live lib base 0x56440000 verified by byte match).
- Runs: `artifacts/execution/e0685-live-synccb4.json`,
  checkpoint `artifacts/checkpoints/boot-e0685-live-synccb4.ckpt`.

## 6. Next

1. Model the libosal local-queue post for `0x00CA8192` (queue object update +
   wake) as an opt-in contract; deliver the decoded ObjMsg envelope through it
   and observe `preProcess -> PostMsg -> RcvMsg -> ProcessMsg -> DispatchEvent`
   (expected FSM event 0x13).
2. Optionally probe the ADJ lane further (subcmd 4 `usb_test_vbus`, nonzero arg
   for subcmd 3) to validate handler dispatch; not required for SETCONFIG.
3. Keep the `unmodelled` defaults and fail-closed guards.
