# E0333 — h4109/h4110 sync-callback packet formats and downstream path

Date: 2026-11-11. Offline static decode + checkpoint-memory inspection only: no
camera access, no camera write, no USB mode change, no firmware injection in
this step. Continues E0323/E0324/E0327/E0328/E0331/E0332.

## 1. Inputs and identities

| Input | Size | SHA-256 |
| --- | --- | --- |
| `artifacts/hardware/live-libs/libUsbControl.so` (live 8.2.6.0 capture) | 94,176 B | `b5cea9d2c92a0b0810353900871fa2806ca3064aa5d8cf3ca7db5ddb6f3940e2` |
| `artifacts/hardware/live-libs/libosal_uipc.so` (live capture) | 26,644 B | `eecc322b81ebf63b26829fb2e8beee43af56f571b0ffbfc16d234dee5063becf` |
| `artifacts/checkpoints/boot-e0673-live-full2e.ckpt` (pre-injection) | 98,063,078 B | `1befe5958dfb54bf2ac494e345b8efeeb7006f51f635c3bdc71543d6eecb24f9` |
| `artifacts/checkpoints/boot-e0684-live-synccb3.ckpt` (E0332 run) | 98,284,464 B | `2a46a8884623f30564a2adb3a122d02bf6baa7ba632c604379dccc845d4084d5` |
| `artifacts/execution/e0684-live-synccb3.json` (E0332 report) | — | UIPC table + mappings source |

Both libraries are analysed with `pyelftools`/`capstone`
(`.\venv\Scripts\python.exe`, Thumb-2) and the checkpoint memory is unpickled
and decompressed read-only. Scratch scripts and raw decoder output:
`artifacts/analysis/e0333-decode*.py` / `e0333-decode*.out.txt` (git-ignored).

## 2. Live load base and computed callback offsets

The e0684 mapping table (also present in e0673) records
`/usr/lib/libUsbControl.so` text at **0x56440000** (`p_offset` 0) and its
data page at **0x5645E000** (`p_offset` 0x16000).  Therefore:

| handle | live callback VA | − base | `.dynsym` symbol | size |
| --- | --- | --- | --- | --- |
| 4109 | **0x5644B0DF** | **0xB0DF** | `_ZN3UFW7AdjBase14funcOsalSyncCbEPvS1_` = `UFW::AdjBase::funcOsalSyncCb(void*, void*)` | 156 B |
| 4110 | **0x56452A87** | **0x12A87** | `_ZN10UsbControl14funcInputGetCbEPvS0_` = `UsbControl::funcInputGetCb(void*, void*)` | 108 B |

`0x5644B0DF - 0x56440000 = 0xB0DF` and `0x56452A87 - 0x56440000 = 0x12A87`
match the dynamic-symbol function starts exactly (Thumb bit set in `st_value`),
so both callbacks are libUsbControl text, not libInfraUsbCmn/libMWF.  (The E0304
`0x562FB0DD` callback was `libInfraUsbCmn+0xB0DD`, a different module; no
relation.)

Live `user_data`:

- **4109**: `0x5645EA98` = libUsbControl base + **0x1EA98** = `.bss`
  (VA range 0x1EA7C..0x1EAC8) + 0x1C.  Checkpoint contents:
  `+0x00 vptr 0x5645E0E0 = _ZTV9UsbAdjCmd+8`; `+0x04 = 0x0701`;
  `+0x08 = 0x100D` (handle 4109); `+0x0C = 0x00CA0288` (queue);
  `+0x10/+0x14 = 1`; `+0x18 = 0x2E1B0` (see 4110).  This is the **static
  `UsbAdjCmd` instance**.
- **4110**: `188848 = 0x2E1B0`, the checkpoint **heap** address
  (heap initial 0x15000) of the `UsbControl` singleton, vptr
  `0x5645E100 = _ZTV10UsbControl+8`.  It is not a library address.

## 3. Callback ABI (verified from live libosal_uipc.so)

`libosal_uipc.so` registers a sync callback record and installs the internal
dispatcher at `[record+8]`.  The dispatcher is the Thumb function at
**0x3168**; `osal_reg_sync_msg_queue_cb` (0x3AE0) computes it at
0x3B1C..0x3B2A: `ldr r3,[pc,#0x30]` reads `0xFFFFF641` from file 0x3B50,
`add r3,pc` (pc 0x3B28) yields Thumb pointer **0x3169**, stored at
`[record+8]`.  The dispatcher instructions:

```
0x3178: ldr   r3,[r5,#0x14]   ; registered callback field
0x317A: add.w r0,r6,#0xC      ; message head + 0xC = payload pointer
0x317E: ldr   r1,[r5,#0x18]   ; registered user_data field
0x3180: blx   r3              ; callback(payload, user_data)
```

So the ABI is **`callback(message_payload, user_data)`**, with the payload at
message-head + 0xC (this matches E0330's `head = payload-0xC` layout).  The
record layout used here: `+0x08` internal dispatcher, `+0x0C` activity byte,
`+0x0D` flags byte, `+0x14` callback, `+0x18` user_data.  Messages whose queue
id has bit 15 set take the process-local path; **0x00CA0288 and 0x00CA01A4
have bit 15 clear, so they are kernel/UIPC queues** (E0332's kernel-origin
delivery lane).

## 4. h4109 — `UFW::AdjBase::funcOsalSyncCb` / `UsbAdjCmd` packet

Registration: `UsbAdjCmd::UsbAdjCmd()` (0xFC90) does
`movw r1,#0x701`; `ldr r2,[pc,#0x14]` = `0x00CA0288` (literal at 0xFCB0);
calls `AdjBase::AdjBase(uint16,uint32)` (0xB1BC), which stores the vtable, then
`this+4 = 0x0701`, `this+0xC = queue`, and calls
`osal_reg_sync_msg_queue_cb(queue, &this+8, callback, this)` (0xB1E2).
`UsbControl_Init` (0x10255) constructs that static instance at
`0xBSS+0x1C` (`ldr r0,[pc,#0x7c]` = 0xE7EC, `add r0,pc` with pc 0x102AC →
0x1EA98; `__cxa_guard_acquire`/`__aeabi_atexit` around it), so the instance
begins with the `_ZTV9UsbAdjCmd` vptr.

The callback (0xB0DF..0xB17A) treats its **arg0 as a 0x140-byte
`OsalRequestPacket`** and arg1 as the `UsbAdjCmd` object:

```
0xB0E8 ldrh r2,[r0,#0x18]     ; request packet id
0xB0EA ldrh r3,[r1,#4]        ; object expected id (0x0701)
0xB0EC cmp  r2,r3
0xB0F0..B0F4 mismatch -> strb #0x81,[r0,#1]; return
0xB0F6..B100 memcpy(sp, msg, 0x140)
0xB104..B11C response header [0x10..0x140) zeroed
0xB120 ldrb r3,[r4]           ; request phase byte
0xB122..B12C phase 4 / 0x10 / 1
0xB12E/B13C/B152 response type byte 8 / 8 / 0x20, result byte 0x80
0xB136/B144/B15A vtable [obj] + 8 / 0xC / 0x10
0xB148..B14E handler(r0=obj, r1=request, r2=response)
0xB160 default -> response type 0, result 0x82
0xB166 memcpy(msg, response, 0x140)   ; synchronous in-place response
```

Decoded request layout (offsets in the 0x140-byte packet):

| offset | type | field | evidence |
| --- | --- | --- | --- |
| +0x00 | u8 | phase: `0x01` process_start, `0x04` finish_send_data, `0x10` finish_receive_data | 0xB120..0xB12C |
| +0x01 | u8 | result (output): 0x80 dispatched, 0x01 handler OK, 0x81 id/arg reject, 0x82 error | 0xB0F0, 0xB13E/0xB140, 0xB162/0xB164, handler tails |
| +0x02 | u16 | echoed unchanged into the response | 0xB104/0xB10E |
| +0x04..+0x0F | — | zeroed in the response | 0xB10C..0xB11A |
| +0x10..+0x13F | bytes | response payload (zeroed before the handler runs) | 0xB112/0xB11C |
| +0x18 | u16 | **packet id, must be 0x0701**; mismatch → result 0x81 | 0xB0E8..0xB0F4 |
| +0x1A | u16 | subcommand 1..7 (dispatch only for phase 1) | `process_start_exec` 0x100DA `ldrh r3,[r1,#0x1A]` |
| +0x1C | u8 | subcommand argument (port/selector/mode) | handlers below |
| +0x1D..+0x25 | bytes | serial/hash data area (handler-specific) | handlers below |
| +0x0C | u32 | response value (e.g. port, serial size) | handler stores |

`UsbAdjCmd::process_start_exec` (0x100DB) reads `req+0x1A`, `subs #1`,
`cmp #6`, `tbb` (table at 0x100EA = `04 08 0C 10 14 18 1C`) and tail-calls:

| +0x1A | handler | offset | decoded use |
| --- | --- | --- | --- |
| 1 | `usb_serial_dat_process_start` | 0xFD79 | `req+0x1C` 0/1 selects serial-dat path |
| 2 | `usb_set_port_process_start` | 0xFDA1 | `req+0x1C` port (`1<<arg & 0x0003FDFF`), Backup_write |
| 3 | `usb_get_port_process_start` | 0xFE05 | Backup_read only; response +0xC port, +0x10 port data |
| 4 | `usb_test_vbus_process_start` | 0xFE71 | `req+0x1C` 0/1/2, `req+0x1D/0x1E`; response +0x10/+0x11 |
| 5 | `sysad_sel_process_start` | 0xFFC5 | `req+0x1C` byte into `execSysAdSel` |
| 6 | `write_customer_hash256_process_start` | 0x10041 | `req+0x1C`: 64 hex chars + NUL (0x41 B), BackupWrapper_Write |
| 7 | `usb_buspower_supply_control_process_start` | 0x100C1 | `req+0x1C` 0/1 into `execBsprwSpplyCtrl` |

Result codes written into response+1 by the handlers: `0x01` OK, `0x81`
argument/id reject, `0x82` processing error; the callback pre-writes `0x80`
("dispatched, no handler result") and uses `0x82` for an unknown phase.
Response type byte: `0x08` for phases 1/4, `0x20` for phase 0x10, `0x00` for
the unknown-phase branch.

## 5. h4110 — `UsbControl::funcInputGetCb` / input-get message

Registration: `UsbControl::PreInit` (0x1045C) makes two sync registrations via
`osal_reg_sync_msg_queue_cb`:

1. `r0 = [0x10498] = 0x00CA01A4`, `r1 = this+0xB4`, callback
   `[GOT 0x568] = UsbControl::funcInputGetCb`, `r3 = this` → this is h4110
   (checkpoint `[this+0xB4] = 0x100E` = 4110);
2. `r0 = [0x1049C] = 0x00CA8192`, `r1 = this+0x84`, callback
   `[GOT 0x51C] = UsbControl::funcOsalSyncCb` (0x1261C), `r3 = this`.  Queue
   0x00CA8192 has bit 15 **set** (process-local queue): this registration is
   not in the kernel UIPC table and `[this+0x84]` holds a local record pointer
   `0x504305C0`, not a handle.

`UsbControl::funcOsalSyncCb` (0x1261C) is only an argument-swapping thunk:
`mov r0,r1; mov r1,r0; b.w UsbControl::preProcess` (0x123B5).  So the
0x00CA8192 sync path is the *ObjMsg* `preProcess` lane (GetCmdMsg/GetRetMsg,
MsgId2EventId), not a packet transform.

`UsbControl::funcInputGetCb` (0x12A87) decodes as:

```
0x12A8E blx osal_msg_size(msg); reject if size <= 0x13 (log 0x14)
0x12AA0 ldr r3,[msg]; reject if word0 != 0 (log 0x30)
0x12AA4 this->keyPhys2LocalCode(msg+4)   ; 0x129D9: table [this+0xB8],
                                          count [this+0xBC], 8-byte entries
0x12AAC (local-1) <= 3 else log 0x2A -> return without status
0x12AC4 GetJackStatus(this, 1..4)        ; 0x127B9 reads this+0xCC/0xD0/0xD4/0xD8
0x12AC8 str r0,[msg+0xC]                 ; status written into the message
```

Decoded message layout (`>= 0x14` bytes, i.e. `osal_msg_size > 0x13`):

| offset | type | field |
| --- | --- | --- |
| +0x00 | u32 | must be 0 (otherwise debug log tag 0x30, no status) |
| +0x04 | u32 | physical key code; live table maps 0x07000001..4 → local 1..4 |
| +0x0C | u32 | **output** jack status (this+0xCC/0xD0/0xD4/0xD8) |

Live key table read from checkpoint memory `[0x2E1B0+0xB8] = 0x2E318`,
`[+0xBC] = 4`: entries `{local 1, phys 0x07000001}`, `{2, 0x07000002}`,
`{3, 0x07000003}`, `{4, 0x07000004}`.

## 6. Downstream path (corrects the E0332 expectation)

- Both h4109 and h4110 paths are **synchronous packet transforms**.  Neither
  constructs an `MWF::ObjMsg`, neither calls `SetCateIdMsgId`, and neither
  posts through `MsgSender`/`SendEvt` into local queue 0x00CA8192.
- h4109: request bytes → `process_start_exec` handler (or base no-op for
  phases 4/0x10) → response bytes copied back into the same message buffer
  (`memcpy` at 0xB166) → libosal sync sender unblocks with the response.
- h4110: request bytes → phys→local map → `GetJackStatus` → status at
  message+0xC → return.
- The only registration that feeds `UsbControl::preProcess`/ObjMsg work is the
  **process-local** queue 0x00CA8192 sync registration (bit 15 set), which
  carries ObjMsg pointers and was already modelled by the async `RcvMsg` lane.
- **Why E0332 saw no downstream message**: the injected envelope was 4 bytes
  whose word0 pointed at the ObjMsg image.  The callback compares
  `ldrh [msg+0x18]` with object+4 (`0x0701`); the envelope/ObjMsg bytes at
  +0x18 are not 0x0701, so the decoded mismatch branch writes result `0x81`
  into the message and returns without invoking any handler.  This exactly
  accounts for "callback executed and completed, no downstream message" — the
  transport worked, the packet did not match the decoded format.

## 7. Confidence and remaining unknowns

Verified (instruction-level): callback VAs/offsets and dynsym identities; the
`callback(payload, user_data)` ABI and payload = head+0xC; registration sites
and queue ids; user_data identities (static `UsbAdjCmd` in BSS, `UsbControl`
heap singleton); h4109 phase/result/id/subcommand offsets and the 1..7 handler
table; h4110 word0/phys-code/status offsets and the live 4-entry key table.

Inference (documented, not captured): the sender side.  No captured kernel
sender packet exists yet; the field *names* are handler-derived, and the
`+0x02` echo and header bytes 0x04..0x0F are decoded only as "copied/zeroed".
The Backup_* device contracts behind subcommands 1..7 (BackupWrapper / backup
service) are outside this module and may stop on their own boundaries.  The
4110 status values were all zero in the live checkpoint (no jack state).

## 8. Next experiment (info the next injection needs)

1. **h4109** — inject a *raw* 0x140-byte packet (not an ObjMsg envelope) into
   queue `0x00CA0288` with the kernel-origin sync delivery policy:
   `--uipc-inject-objmsg-setconfig-queue 0x00CA0288
   --uipc-inject-objmsg-packet-hex <hex> --uipc-sync-callback-delivery
   kernel-origin`, where `<hex>` is generated by
   `src/a6400/execution/usb_sync_callback.py:build_adj_process_start_request`:
   phase +0x00 = 0x01, id +0x18 = 0x0701, subcommand +0x1A = **3**
   (`usb_get_port_process_start`, Backup_read-only), arg +0x1C = 0.
   Expected: callback takes the match path, `process_start_exec` dispatches,
   response+1 becomes 1 (OK) or 0x81/0x82, response+0x0C gets the port value;
   no ObjMsg/FSM event 0x13 is expected on this lane.
2. **h4110** — inject a 0x14-byte message into `0x00CA01A4`: word0 = 0,
   word+4 = 0x07000001..4; expected `msg+0xC` = jack status (0 in the live
   state).
3. Keep the default `unmodelled` policy and the fail-closed guards; both
   packets are labelled synthetic requests, not captured kernel messages.

## 9. Code and tests

`src/a6400/execution/usb_sync_callback.py`: registration/ABI constants,
`decode_adj_request_packet`/`decode_adj_response_packet`,
`build_adj_request`/`build_adj_process_start_request`,
`decode_input_get_request`/`decode_input_get_response`,
`phys_key_to_local_code`, `describe_sync_callback`,
`describe_downstream_path`, `describe_sync_callback_packet_format`
(all fail closed with `ValueError`; import needs no firmware).

Tests: `tests/test_usb_sync_callback.py` (31 tests; identity offsets, ABI and
lane bits, request/response decode + refusals, builder validation, input-get
mapping/rejections, downstream/report invariants).  Full suite: see status
report; suite baseline was 957 tests before this change.
