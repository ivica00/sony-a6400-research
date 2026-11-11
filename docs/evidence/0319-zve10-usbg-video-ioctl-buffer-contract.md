# E0319 — ZV-E10 `usbg_video.ko` ioctl/buffer contract (start of gap-3 decode)

Date: 2026-11-11. Input: ZV-E10 2.03 extracted `usbg_video.ko`
(SHA-256 `d385a051bf01b0e5ea37412623ae85cfe3cda76ab0d11e61d111994ca9fbf4fb`,
20,668 B). Offline only; no camera writes, no module loading.

## 1. Input layout

ELF section map: `.text` file offset `0x34`, size `0x2b90` (vaddr base 0);
`.rodata` `0x2dec`; `.data` `0x31ac`; `.bss` `0x33c8`.
Relevant exported functions (symtab `st_value`, size):

| Function | st_value | size |
| --- | --- | --- |
| `usbg_video_core_open` | 0x1AC8 | 484 |
| `usbg_video_core_release` | 0x1CAC | 356 |
| `usbg_video_core_write` | 0x23F0 | 76 |
| `usbg_video_core_ioctl` | 0x1E10 | 1504 |
| `usbg_video_st_write_comp` | 0x248C | 404 |
| `uvc_transfer_dmac_cb` | 0x6A0 | 76 |
| `usbg_video_get_ep` | 0x5A4 | 192 |
| `usbg_video_get_ep0_buffer` | 0x588 | 28 |
| `usbg_video_call_user_cb` | 0x4B4 | 212 |
| `usbg_video_create_this` | 0x300 | 264 |
| `usbg_video_delete_this` | 0x448 | 72 |
| `usb_sync_alloc_phys_buffer` | 0x2988 | 292 |
| `usb_sync_free_phys_buffer` | 0x2AAC | 228 |

`usb_gadgetcore_register_driver`, `dma330_mem_transfer_async` and the
`osal_*` message API are imports (kernel/other-module exports; a6400 provides
the same set, E0316).

## 2. `usbg_video_core_ioctl` dispatch (ARM, decoded)

Entry `0x1E10` (file `0x1E44`), 376 instructions. Dispatch shape:

```
1e20 ubfx r3, r1, #8, #8      ; ioctl type byte
1e24 mov  r4, r1              ; cmd
1e28 cmp  r3, #0xe0
1e30 bne  0x20b4              ; non-0xE0 command family
1e34 and  r3, r1, #0xff       ; nr byte
1e38 cmp  r3, #2
1e3c bhi  0x23b0              ; nr 0..2 accepted; others -> error path
```

Recognized constants so far:

- `0x4038e000` — literal at file/vaddr `0x23c0`, decoded by `_IOWR` layout:
  dir = 3 (read|write), type = `0xE0`, nr = 0, size = **0x38 = 56 bytes**.
- `0x0000e001` — legacy `movw` command compared at `0x1EC0`.
- The branch with `0xE0`/nr<=2 sets up a request/buffer descriptor in the file
  object and calls helpers with a 56-byte user structure.

## 3. File-object / buffer setup observed in the ioctl

The file object `r4` holds the USB video driver context. Writes/reads observed:

- `[r4+0x24]` — pointer to the UVC request/control buffer; request bytes are
  read from `r2` offsets `[+0]`, `[+1]`, `[+2]` (bRequestType/bRequest/wValue
  style fields), copied into context bytes `+0x3c`, `+0x3d`.
- Global bytes at `global+0x35`/`global+0x36` are updated from request bytes
  (`strb r2,[r3,#0x35]`, `strb r2,[r3,#0x36]`) — likely the streaming
  format/frame parameters.
- `[r4+0x38..0x6c]` is initialized with zero/constant slots and function
  pointers (e.g. `str r3,[r4,#0x38]`, `strb r5,[r4,#0x44]`,
  `str r4,[r4,#0x48]`, `str r3,[r4,#0x40]`, `[r4+0x50..+0x68]` set from
  literals, `[r4+0x6c]` from a literal) — the transfer/request descriptor and
  completion slots used by `uvc_transfer_dmac_cb`.
- `usbg_video_core_open` (0x1AC8) establishes the character-device context and
  `usbg_video_core_write` (0x23F0) queues write data; `usbg_video_st_write_comp`
  is the write-completion path.

## 4. What this gives toward the gap-3 contract

The UVC video device contract needs, at minimum:

1. `/dev/usb/video` open/release semantics and the per-file context above.
2. The 56-byte `0x4038e000` request structure (probe/commit controls:
   `usbg_video_probe_commit_ctrls`) and its translation into global
   format/frame parameters (`global+0x35/0x36`).
3. Buffer registration/lifetime: `usb_sync_alloc_phys_buffer` /
   `usb_sync_free_phys_buffer`, `usbg_video_buf_info` list, `WaitVideoReadCmp`
   and `UpdateVideoBufEvt` producers (E0316).
4. DMA completion: `dma330_mem_transfer_async` + `uvc_transfer_dmac_cb`,
   including `usbg_video dma_info`/`usbg_video dma_req` bookkeeping.

These are the exact contracts to model before real image data can flow; no
fabricated buffers or completions are used here.

## 5. Next decode steps

- Full dispatch table: remaining literal constants in `0x1E10..0x23F0` and
  `0x23B0..0x23D0` branch targets (all `_IOWR` commands and their sizes).
- Reconstruct `usbg_video_buf_info`, `usbg_video_data_info`, and
  `usbg_video_probe_commit_ctrls` layouts from `usbg_video_core_ioctl`,
  `usbg_video_call_user_cb`, `usbg_video_st_write_comp`, `usbg_video_get_ep`
  and the ZV-E10 `libInfraUsbCmn` `RegVideoDataBufInfo`/`UpdateVideoBufEvt`
  call sites.
- Map to `SendProbeInfo`/`SendCommitInfo` in `CUsbGadgetStreaming` (ZV-E10
  `libInfraUsbCmn.so` 0x1E1D9/0x1E211 by symbols) and to a future opt-in
  `usbg_video` device contract in the emulator.

## 6. Follow-up decode (2026-11-11, second pass)

Additional constants confirmed in `usbg_video_core_ioctl`:

- `0x4008F000` (literal at vaddr `0x23E4`): `_IOC` dir write, type `0xF0`,
  nr 0, size **8 bytes** (second small write command).
- `0x0000E001` legacy command (`movw` at `0x1EC0`).
- `0x0000F006` (`movw` at `0x217C`) — numeric/legacy command in the second
  dispatch family (`cmp type,#0xF0`, `cmp nr,#9`).
- Branch/error constants: `0x54B` (`0x1EB4`), `0x590` (`0x2138`), `0x43A`
  (`0x1FF4`), `0x55C` (`0x20A0`), `0x5AA` (`0x2360`), `0x658` (`0x2378`) —
  status/error words written through the request descriptor, not ioctl nr.

Per-file context (`r4`) slots observed by the ioctl (descriptive names only):

| Offset | Meaning (to confirm) |
| --- | --- |
| 0x10/0x14 | transfer state words |
| 0x24 | UVC request buffer pointer |
| 0x38 | request descriptor word |
| 0x3C | request bRequestType |
| 0x3D | request bRequest |
| 0x40 | request pointer slot |
| 0x44 | request index/mode byte |
| 0x48 | self pointer |
| 0x50..0x6C | completion/transfer slots set from literals |

These constants are encoded with tests in
`src/a6400/execution/usb_video_contract.py` (`decode_usb_video_ioctl`,
`ZVE10_USBG_VIDEO_CONTEXT_FIELDS`); tests are structural only and do not claim
driver behaviour. Full suite after this addition: **903 tests OK**.

## 7. Buffer/completion layout pass (third pass, 2026-11-11)

Disassembled `usbg_video_call_user_cb` (0x4B4), `usbg_video_st_write_comp`
(0x248C), `uvc_transfer_dmac_cb` (0x6A0), `usb_sync_alloc_phys_buffer`
(0x2988) and `usb_sync_free_phys_buffer` (0x2AAC).

**Event callback table** (`usbg_video_call_user_cb`): event id `r4` (0..7) is
used as a jump-table index; the handler slot is read from
`this_ex + {0x04,0x08,0x0C,0x10,0x14,0x18,0x1C,0x20}` and invoked with
`(chosen_slot, event_id_u8, arg2, arg3)`. So the driver context has an 8-slot
user-callback vector at `+4..+0x20`.

**Write-completion object** (`usbg_video_st_write_comp`): `r4` points at the
completed data object; `[r4+0x2C]` is read as a signed result (special values
`-0x54` and `-0x68` have dedicated paths). The object is matched by pointer
against a global circular list whose node layout is `[+0]=data_object`,
`[+4]`/`[+8]=links`; on match `[this+8]` -> `[+0xC]` callback is invoked with
`(this, data_object)`, then the node is unlinked and recycled (`[+4]=0x100`,
`[+8]=0x200`).

**DMA completion** (`uvc_transfer_dmac_cb`): argument `r4`; global transfer flag
is set to 1, then `[r4+8]` is invoked if non-NULL — an optional completion
callback inside the DMA argument.

**Physical buffer descriptor** (`usb_sync_alloc_phys_buffer` /
`usb_sync_free_phys_buffer`): observed field offsets on the descriptor argument:
`+0x00` virtual pointer, `+0x02` size/flags, `+0x04` physical pointer,
`+0x0C` cache/alignment word, `+0x10`/`+0x14` output pointer slots,
`+0x16` flags. Names are hypotheses unless directly observed; the offsets are
from the disassembly.

These slots are encoded with tests in
`src/a6400/execution/usb_video_contract.py`
(`USBG_VIDEO_USER_CALLBACK_SLOTS`, `USBG_VIDEO_DATA_INFO_FIELDS`,
`USBG_VIDEO_WRITE_COMP_LIST_NODE`, `USBG_VIDEO_DMA_COMPLETION_FIELDS`,
`USBG_VIDEO_PHYS_BUFFER_FIELDS`, `describe_usbg_video_buffer_contract`).
Structural tests only; no driver behaviour is claimed. Full suite: **906 tests
OK**.

## 8. Register/unregister semantics and probe-info ABI (fourth pass)

Relocations in `.text` resolve the two ioctl paths:

- **`0x4038E000` = register/start:** `usbg_video_get_this()` ->
  `usbg_cmn_copy_probe_info(this, arg)`; on success the driver context
  `+0x38..+0x6C` is filled (descriptor word at `+0x38`, request bytes at
  `+0x3C/0x3D` read from `this+0x24`, global format bytes `+0x35/+0x36`,
  `+0x40` pointer to them, `+0x44 = 2`, `+0x48 = self`, driver op literals at
  `+0x50..+0x68`, `+0x6C`) and `usb_gadgetcore_register_driver(this+0x38)` is
  called. On a registration error the driver logs status `0x43A` and invokes
  the user callback; the ioctl itself returns 0.
- **`0x0000E001` = unregister:** `usb_gadgetcore_unregister_driver(this+0x38)` ->
  `usbg_cmn_clear_probe_info(this)` -> `usbg_video_call_user_cb(this,1,...)`;
  returns 0.

**Probe-info user ABI (`usbg_cmn_copy_probe_info`, 0x15C, 352 B):**
`access_ok(arg, 0x38)`; `copy_from_user` of the 56-byte block; allocate
`count*2` bytes (count read from context `+0x2D`) and copy from user `+0x24`
into context `+0x24`; allocate user `+0x34` bytes and copy from user `+0x30`
into context `+0x30/+0x34`; user `+0x30 == 0` clears the blob and succeeds;
errors return `-0x68`.  `usbg_cmn_clear_probe_info` (0x118, 68 B) frees the
two allocations and clears the pointers.

**ABI parity:** `usbg_cmn_copy_probe_info` (352 B,
`978608ceaa3560fb89af3d77738c9ff01cee6731ff0aebd504359fbaa4c47d7a`) and
`usbg_cmn_clear_probe_info` (68 B,
`ed16a3cb5ff777a0b0938ce2477b453779bbf6dfa5b1087043e385256055f2c9`) are
**byte-identical** between a6400 8.2.5.7 and ZV-E10 2.03 despite different
`usbg_cmn.ko` builds — the probe-info ABI already exists in a6400 firmware.

Encoded with tests in `usb_video_contract`:
`parse_usb_video_probe_info` (56-byte block, fields `+0x24` buffer-table
pointer, `+0x30` blob pointer, `+0x34` blob length), the command constants and
the two ABI SHA-256 values.

**Still undecoded (boundary):** the writer of context `+0x2D` (count), the
semantics of the buffer table/blob contents, and the gadgetcore driver
descriptor literals at `+0x50..+0x6C`; `GuestUsbVideo` therefore stays
fail-closed and does not model register success.  Full suite: **921 tests OK**.

## 9. Gadgetcore driver struct and open() buffer layout (fifth pass)

Resolved `.rel.text` literals in the register path:

- `context+0x38` = driver-name pointer -> `.rodata.str1.1 + 0x296` =
  **"USB Gadget Video Device"**.
- `context+0x3C/0x3D` = request `bRequestType`/`bRequest`, copied from the
  `context+0x24` buffer (allocated by `usbg_cmn_copy_probe_info`).
- `context+0x40` = pointer to `.bss + 8 + 0x35` (global format bytes
  `+0x35`/`+0x36`); `context+0x44 = 2` (driver entry count); `context+0x48 =
  self`.
- `context+0x50..0x6C` = callback table, resolved exactly:

| Context offset | Callback | VA | Size |
| --- | --- | --- | --- |
| +0x50 | `core_cb_start` | 0x10F0 | 204 |
| +0x54 | `core_cb_stop` | 0x0744 | 388 |
| +0x58 | `core_cb_set_halt` | 0x068C | 20 |
| +0x5C | `core_cb_clear_halt` | 0x06EC | 56 |
| +0x60 | `core_cb_nop` | 0x067C | 16 |
| +0x64 | `core_cb_nop` | 0x067C | 16 |
| +0x68 | `core_cb_nop` | 0x067C | 16 |
| +0x6C | `core_cb_class` | 0x17B0 | 708 |

`usbg_video_core_open` (0x1AC8) allocates the iso-in buffers:
`usb_sync_alloc_phys_buffer(...)` -> `arch_phys_to_noncache`; stores
context `+0x00` (virtual), `+0x04` (physical), `+0x08`/`+0x0C` (virtual
start/end), `+0xa0` (tag/handle), `+0xa4` (length), `+0xac` (0xD0-byte request
object), `+0xb0` (0x24-byte DMA-info object with fields `[0]=1`, `[4]=1`,
`[8]=adjusted physical`, `[0xC]`/`[0x10]` literals); it also clears
`.bss+0x28/+0x2C/+0x30` and sets a global flag.

**Remaining boundary:** the writer of `context+0x2D` (buffer-table count read by
`usbg_cmn_copy_probe_info`) was not found in `usbg_video.ko` text; it is
probably initialised by a copied user structure or another module. The table
and blob semantics (`+0x24` count*2 bytes, `+0x30/+0x34`) and the 0xD0/0x24
object contents also remain undecoded, so `GuestUsbVideo` stays fail-closed.

Encoded with tests in `usb_video_contract`:
`USB_VIDEO_DRIVER_NAME`, `USB_VIDEO_GADGETCORE_DRIVER_FIELDS`,
`USB_VIDEO_CORE_CALLBACKS`, `USB_VIDEO_OPEN_CONTEXT_FIELDS`,
`describe_usbg_video_register_contract`. Full suite: **924 tests OK**.

## 10. 0xF0 ioctl family = transfer path (sixth pass)

`usbg_video_core_ioctl` has a second family (type `0xF0`, nr <= 9). Decoded
commands and instruction-level effects:

| Command | Name | Effect |
| --- | --- | --- |
| `0x4008F000` | `set_dma_address` | `copy_from_user` 8 B; context `+0x14` = raw value, `+0x10` = raw + `0x60000000` (>=0) or + `0x20000000` (<0) |
| `0x0000F001` | `clear_dma_address` | context `+0x10` = `+0x14` = 0 |
| `0x0000F002` | `transfer_log_status` | reads global bytes `+0x10/+0x11`, logs via `snprintf`, returns 0 or `-0xF` |
| `0x0000F006` | `enable_transfer` | context `+0xCC` = 1 |
| `0x4008F003` | `write_transfer` | calls helper `0x0D00`: `copy_from_user` 8 B, `usbg_video_get_ep`, mutex locks, transfer bookkeeping |

`usbg_video_core_write` (0x23F0) is a stub: size 0 returns 0, otherwise
`-0x15`.  `usbg_video_create_this` (0x300) allocates and zeroes the 0xC0-byte
context and 0xD0-byte object (so **context `+0x2D` starts at 0**).

**Remaining boundary:** no instruction in `usbg_video.ko` text writes context
`+0x2D` (the buffer-table count read by `usbg_cmn_copy_probe_info`); the writer
must be another module or a structure copy not yet located. Table/blob
semantics and the 0xD0/0x24 object contents also stay undecoded, so
`GuestUsbVideo` remains fail-closed.

Encoded with tests: `USB_VIDEO_TRANSFER_IOCTLS`,
`USB_VIDEO_CONTEXT_COUNT_OFFSET=0x2D`,
`describe_usbg_video_transfer_contract()`. Full suite: **926 tests OK**.

## 11. Endpoint-list setup via `core_cb_start` (seventh pass)

`usbg_video_get_this` returns the global 0xC0 context; `get_this_ex` returns
`[context+0xBC]` (the 0xD0 object).  `core_cb_start` (0x10F0) is invoked by
gadgetcore with `(driver, ep_id, count, list)`:

1. `usbg_video_get_this` -> context in r6;
2. `usbg_video_get_this_ex` -> `strb ep_id, [this_ex+0x9C]`;
3. mutex lock `this_ex+0x3C`;
4. `usbg_cmn_make_ep_list(context, ep_id, count, list)`.

`usbg_cmn_make_ep_list` (0x2BC, 128 B) writes into the context:

| Context offset | Meaning |
| --- | --- |
| +0xB2 | ep_id byte |
| +0xB4 | ep list pointer (kmalloc count*4 + copy of endpoint descriptors) |
| +0xB8 | ep count byte |

`usbg_cmn.ko` a6400/ZV-E10 share the same function sizes/symbols; the layout is
recorded as evidence, not modelled behaviour.

**Boundary:** context `+0x2D` (count read by `usbg_cmn_copy_probe_info`) has no
store in `usbg_video.ko` or `usbg_cmn.ko` text (also no wider 32-bit store
covering it); the writer is external (kernel gadgetcore or a structure copy not
yet located). `GuestUsbVideo` stays fail-closed.

Encoded with tests: `USB_VIDEO_EP_LIST_CONTEXT_FIELDS`,
`USB_VIDEO_THIS_EX_EP_ID_OFFSET=0x9C`,
`describe_usbg_video_endpoint_list_contract()`. Full suite: **928 tests OK**.

## 12. Physical-buffer RPC ABI (`usb_sync_alloc/free_phys_buffer`)

`usbg_video.ko` local copies (alloc 0x2988, 292 B; free 0x2AAC, 228 B) are OSAL
RPC clients using `osal_dynamic_id`/`osal_valloc_msg_wait`/`osal_snd_msg`/
`osal_rcv_msg_tmo` message size **0x18**:

- alloc message: `+0 opcode=1`, `+2 flags=0`, `+4 size u32`, `+8 zero`,
  `+0xC timeout=0xFFFFFFFF`, `+0x14 zero`, `+0x16 flags=1`; dynamic id
  `0x2A` acquired, reply: status at `+2`, length at `+4` (u16 -> out), physical
  at `+0x10`, virtual at `+0x14`; dynamic id `0x4A` released.
- free message: `+0 opcode=4`, `+2 handle u16`, `+0x14 zero`, `+0x16 flags=2`,
  same wait/release; reply status at `+2`.
- `usbg_video_core_open` calls alloc with tag `0x2DA` and size `0x50E`,
  receiving `&length`, `&physical`, `&virtual`.

Encoded with tests: `USB_VIDEO_PHYS_BUFFER_RPC`,
`describe_usbg_video_phys_buffer_rpc()`. Full suite: **935 tests OK**.

**Kernel-writer attempt:** the a6400 `vmlinux.bin` is a custom-compressed image
(`d3f021e3…`, no gzip/xz/bz2/zstd/lz4 signature; LZMA offsets fail), so offline
disassembly of `usb_gadgetcore_register_driver` (kallsyms 0x602B8610) is not
possible with the current tooling; the writer of context `+0x2D` therefore
remains unresolved and is not guessed.
