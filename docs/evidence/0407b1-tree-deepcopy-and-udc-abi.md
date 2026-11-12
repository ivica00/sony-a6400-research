# E0407b1 — DWC3/gadgetcore soft-connect ABI and native per-speed descriptor-tree ABI

Date: 2026-11-12. **Offline static analysis only.** No camera access, no USB
tool, no module load, no `/dev/mem`, no `/setting`, no device write. Every
address below is either a decoded instruction address in the preserved image or
a data address read from it. Dynamic results come from executing the original
ARM bytes under Unicorn with synthetic fixtures, not from hardware.

This document is the input for the kernel-C implementer of E0407b1 (deep-copy
the native tree, append a zero-endpoint vendor interface 1, swap the root,
trigger a clean re-enumeration). It deliberately separates **verified**,
**inference** and **unproven** items.

---

## 0. TL;DR for the implementer

* The native tree root is `*(void **)(gc + 0x6c)`, an **88-byte** (`0x58`)
  gadgetcore-owned heap block produced only by `save_desc_tbl()` from a
  caller-supplied descriptor specification. It is **not** one contiguous block:
  every config / interface array / alternate array / endpoint array / extra blob
  / string is a separate `__kmalloc`/`kmem_cache_alloc` allocation.
* `gc+0x6c` is **read without any lock** by every serializer. The only native
  serialization is the `gc+0x68` bit 2 "started" gate plus the single DWC3
  threaded-IRQ context. A module may swap the root only while the UDC is
  disconnected (D+ low) and interface endpoints are stopped.
* `free_desc_tbl()` frees the root and sets `gc+0x6c = NULL`. It frees the
  `root+0x00` and `root+0x10` per-speed config trees but **not**
  `root+0x20` (SuperSpeed) — a verified leak/omission.
* A module-owned root must be removed from `gc+0x6c` before any app stop/start
  or `free_desc_tbl()`; otherwise gadgetcore `kfree()`s module memory. There is
  no refcount.
* `save_desc_tbl()` deep-copies from user space (`__copy_from_user`), including
  all strings and extras. After it returns, the caller's source tree may be
  freed. Installing a second tree without freeing the first leaks the first.
* Clean re-enumeration is: clear `gc+0x68` bit 2 → `pullup(0)` →
  `setup_disconnect(gc)` → `usb_gcw_stop()` → change/free tree →
  `save_desc_tbl()` (or assign module root) → `usb_gcw_start(mode)` → arm EP0 →
  set `gc+0x68` bit 2 → `pullup(1)`.
* DWC3 connect/disconnect is `DCTL` bit 31 (`RUN_STOP`) at
  `regs = *(u32 *)(dwc + 0x2b4)`, register offset `+0x604`; stop completion is
  `DSTS +0x60c` bit 22. `pullup(1)` sets it, `pullup(0)` clears it.
* **Correction to E0405ab/E0407a:** the device-descriptor record selection is
  `speed 3 (HIGH) -> root+0x00`, `speed 5 (SUPER) -> root+0x20`, **else
  (FULL) -> root+0x10**. E0407a's table (`3 -> root+0x10`) is inverted, and its
  physical bcdUSB patch at `root+0x10` therefore did not change the descriptor
  served while `[gadget+0x20] == 3`. See §6.2.

---

## 1. Tools, image identity and VA mapping

### 1.1 Image

| Item | Value |
| --- | --- |
| Path | `firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin` |
| Size | 4,085,888 bytes |
| SHA-256 | `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707` |
| First bytes | `d3 f0 21 e3` (Sony container header; text is not at offset 0) |
| `_stext` (retained kallsyms) | `0x60108160`; bytes at file `0x160` = `0d c0 a0 e1` (`mov ip, sp`), a normal ARM prologue |
| Mapping used by retained tools and here | `file_offset = VA - 0x60108000` |
| Independent identity anchors | `"Linux version 3.0.27_nl-rt106+"` at file `0x2c0028` → VA `0x603c8028`; `"gadgetcore"` at file `0x342455` → VA `0x6044a455` |

The mapping is also the one used by the retained E0358/E0402/E0405 tooling
(`disasm_gadgetcore.py`, `build_uvc_ptp_descriptor_candidate.py`,
`probe_ptp_endpoint_contract.py`: `kernel[lookup-0x60108000]`).

### 1.2 Tools

| Tool | Version/identity |
| --- | --- |
| Python | 3.14.6 (`venv`) |
| Capstone | 5.0.7 |
| Unicorn | 2.1.4 |
| Symbol source | `artifacts/analysis/e0401-kallsyms-now.txt` (retained `/proc/kallsyms` snapshot, same kernel) |
| Reference firmware | a6400 `vmlinux.bin` above; ZV-E10 `libInfraUsbCmn.so` only for data-template cross-checks |

No REA/Ghidra session was needed: all target functions have exact kallsyms
names and the decoding is instruction-level.

### 1.3 Exact commands that produced the receipts

```powershell
# per-function disassembly with raw bytes + BL symbol resolution
.\venv\Scripts\python.exe artifacts\analysis\e0407b1-work\analyze.py `
  --function <name> [--function ...] --output artifacts\analysis\e0407b1-work\<file>.txt

# BL/data cross-references, raw data reads
.\venv\Scripts\python.exe artifacts\analysis\e0407b1-work\xref.py `
  --bl 602b1d3c --literal 6051b24c --read 603dfdf4:0x50

# real-byte serializer/gcw execution (81 checks)
.\venv\Scripts\python.exe artifacts\analysis\e0407b1-work\verify_serializers.py

# real-byte save_desc_tbl/free_desc_tbl allocator trace (19 checks)
.\venv\Scripts\python.exe artifacts\analysis\e0407b1-work\verify_alloc.py

# gc field / root-pointer scan
.\venv\Scripts\python.exe artifacts\analysis\e0407b1-work\scan_gc.py
```

Receipts (all under `artifacts/analysis/e0407b1-work/`):

* `gcw.txt/.json`, `gc-ioctl.txt`, `dwc3-pullup.txt`, `dwc3-startstop.txt`,
  `dwc3-init.txt`, `dwc3-probe.txt`, `udc-core.txt`, `setup-helpers.txt`,
  `setup_req` excerpts, `save-config.txt`, `desc-alloc.txt`,
  `free-desctbl.txt`, `serializers-small.txt`, `make-config.txt`,
  `lookup.txt`, `ep-ctrl.txt`, `bus.txt`, `gcw-driver.txt`, `g-setup.txt`,
  `thread-irq.txt`, `delegate.txt`.
* `verify/manifest.json` — 81/81 serializer+gcw checks passed.
* `verify/allocator-manifest.json` — 19/19 allocation/free checks passed,
  25 original allocations, 6 leaked SuperSpeed-tree allocations.
* `verify/gc-field-scan.json` — 164 `gc+field` instruction hits, 13 literal
  references to the `gc` global slot.

---

## 2. Layering and key symbols

```text
camera app (userspace)
   open/ioctl /dev/gadgetcore (char device)
        |
        v
usb_gadgetcore_ioctl 0x602b8844          (gadgetcore cdev ABI)
   start 0x400CE203, stop 0xE204, install/clear 28-byte event object
        |
        v
gadgetcore object gc = *(u32*)0x6051b17c  (allocated at module init 0x604a580c)
   gc+0x6c  root descriptor table
   gc+0x68  flags (bit1 opened, bit2 started)
   gc+0x78  registered function-driver node list (0x18-byte nodes)
   gc+0x84  is_dual/mode (app-supplied at start)
   gc+0x85  max_speed (app-supplied at start)
        |
        v
gadgetcore's struct usb_gadget_driver 0x604e5020
   bind g_bind 0x602b83f4, setup g_setup 0x602b8328,
   disconnect g_disconnect 0x602b8bc8, suspend/resume 0x602b82ec/0x602b82b0
        |
        v
usb_gcw_register_driver 0x602bd66c wraps that driver at gcw+0x268 and calls
usb_gadget_probe_driver 0x602b4ba8
        |
        v
UDC core udc_bind_to_driver 0x602b4af0 -> gcw_bind -> g_bind,
then gadget->ops->udc_start (+0x20) = dwc3_gadget_start 0x602af3a4
        |
        v
DWC3: request_threaded_irq(irq, NULL, dwc3_thread_interrupt 0x602b1378,
                           flags 0x2080, "dwc3", dwc)
      setup path: dwc3_thread_interrupt -> dwc3_ep0_interrupt 0x602b2c68
                  -> dwc3_ep0_delegate_req 0x602b28e4
                  -> driver->setup (+0x10) = gcw_setup -> g_setup -> setup_req
```

Key object global:

| Object | Address | Meaning |
| --- | --- | --- |
| `gc` slot | `0x6051b17c` (value on last boot `0x68aa4ec0`) | gadgetcore device struct pointer |
| gadgetcore driver | `0x604e5020` | 0x58-byte `struct usb_gadget_driver`; function name `0x60463950`, speed 3, bind/unbind/setup/disconnect/suspend/resume at +0x08/+0x0c/+0x10/+0x14/+0x18/+0x1c |
| gcw wrapper | `0x6051b24c` | BSS object: +0x00 copied driver, +0x58 lock pointer, +0x60 state, +0x64 MTP staging buffer (0x200), +0x264 length, +0x268 wrapped `usb_gadget_driver` |
| DWC3 ops table | `0x603dfbf0` | get_frame +0, wakeup +4, set_selfpowered +8, vbus_session +0xc, vbus_draw +0x10, **pullup +0x14 = 0x602b1d3c**, ioctl +0x18, udc_start +0x20, udc_stop +0x24 |
| MS OS string table | `0x604e5130` | 18 bytes `12 03 4d 00 53 00 46 00 54 00 31 00 30 00 30 00 30 00` (`MSFT100`, vendor code 0x30) |

---

## 3. UDC soft-connect / disconnect / re-enumeration ABI

### 3.1 gadgetcore cdev ioctl ABI

`usb_gadgetcore_ioctl` is the 0x284-byte function at `0x602b8844`. It is the
only app-facing control plane for the native tree and the D+ line.

Decoded command words (ARM `_IOC` little-endian):

| Command | `_IOC` meaning | Address of handler | Semantics |
| --- | --- | --- | --- |
| `0x401CE201` | `_IOW(0xE2,1,28)` | `0x602b8890` | copy 28 user bytes to `gc+0x14`; first word must be non-zero; fails `-EBUSY` if `gc+0x14` already non-zero |
| `0xE202` | `_IO(0xE2,2)` | `0x602b8948` | lock `gc+0x30`, `gc+0x14 = 0`, unlock |
| `0x400CE203` | `_IOW(0xE2,3,12)` | `0x602b8980` | **start / install tree / connect** |
| `0xE204` | `_IO(0xE2,4)` | `0x602b8a24` | **stop / disconnect / free tree** |

Start (`0x400CE203`) instruction order — `gc` in r4, user arg in r5:

```text
602b8990: 686084e2  add  r6, r4, #0x68
602b8994: 0200a0e3  mov  r0, #2
602b8998: 0610a0e1  mov  r1, r6
602b899c: 0b83feeb  bl   0x602595d0   ; _test_and_set_bit(2, gc+0x68)
602b89a0: 000050e3  cmp  r0, #0
602b89a4: 1c00001a  bne  0x602b8a1c   ; already started -> -EBUSY
602b89a8: 90f5ffeb  bl   0x602b5ff0   ; usb_otgcore_get_hs_disable
602b89ac: 0510a0e1  mov  r1, r5
602b89b0: 8000c4e5  strb r0, [r4, #0x80]   ; gc+0x80 = hs_disable
602b89b4: 0400a0e1  mov  r0, r4
602b89b8: e40e00eb  bl   0x602bc550   ; save_desc_tbl(gc, user_arg)
602b89bc: 005050e2  subs r5, r0, #0
602b89c0: f4009f15  ldrne r0, [pc, #0xf4]
602b89c4: 13110013  movwne r1, #0x113
602b89c8: 0e00001a  bne  0x602b8a08   ; fail path -> clear bit2
602b89cc: 8400d4e5  ldrb r0, [r4, #0x84]  ; is_dual/mode
602b89d0: 881300eb  bl   0x602bd7f8   ; usb_gcw_start(mode)
602b89d4: 000094e5  ldr  r0, [r4]        ; gadget
602b89d8: 103090e5  ldr  r3, [r0, #0x10] ; gadget->ops
602b89dc: 143093e5  ldr  r3, [r3, #0x14] ; ops->pullup
602b89e0: 000053e3  cmp  r3, #0
602b89e4: 0400000a  beq  0x602b89fc   ; no pullup -> -EOPNOTSUPP
602b89e8: 0110a0e3  mov  r1, #1
602b89ec: 33ff2fe1  blx  r3            ; pullup(gadget, 1) == D+ high
602b89f0: 005050e2  subs r5, r0, #0
602b89f4: 2a00000a  beq  0x602b8aa4   ; success
602b89f8: 000000ea  b    0x602b8a00
602b89fc: 5e50e0e3  mvn  r5, #0x5e    ; -EOPNOTSUPP
602b8a0c: 0200a0e3  mov  r0, #2
602b8a10: 0610a0e1  mov  r1, r6
602b8a14: d578feeb  bl   0x60256d70   ; _clear_bit(2, gc+0x68) on failure
```

Stop (`0xE204`):

```text
602b8a40: 0200a0e3  mov  r0, #2
602b8a44: 681084e2  add  r1, r4, #0x68
602b8a48: ce82feeb  bl   0x60259588   ; _test_and_clear_bit(2, gc+0x68)
602b8a4c: 005050e2  subs r5, r0, #0
602b8a50: 1300000a  beq  0x602b8aa4   ; already stopped -> 0
602b8a54: 000094e5  ldr  r0, [r4]        ; gadget
602b8a58: 103090e5  ldr  r3, [r0, #0x10] ; ops
602b8a5c: 143093e5  ldr  r3, [r3, #0x14] ; pullup
602b8a60: 000053e3  cmp  r3, #0
602b8a64: 0300000a  beq  0x602b8a78
602b8a68: 0010a0e3  mov  r1, #0
602b8a6c: 33ff2fe1  blx  r3            ; pullup(gadget, 0) == D+ low
602b8a70: 000050e3  cmp  r0, #0
602b8a74: 0200000a  beq  0x602b8a84
602b8a78: 44009fe5  ldr  r0, [pc, #0x44] ; "pullup failed" printk
602b8a7c: 3b1100e3  movw r1, #0x13b
602b8a80: 8c2e04eb  bl   0x603c44b8   ; printk
602b8a84: 0400a0e1  mov  r0, r4
602b8a88: 0050a0e3  mov  r5, #0
602b8a8c: 740200eb  bl   0x602b9464   ; setup_disconnect(gc)
602b8a90: 671300eb  bl   0x602bd834   ; usb_gcw_stop()
602b8a94: 0400a0e1  mov  r0, r4
602b8a98: 510e00eb  bl   0x602bc3e4   ; free_desc_tbl(gc)
```

Important: the start path's third argument is a **12-byte user header** copied
by `save_desc_tbl`, not a pointer to the 88-byte table directly. Header layout
used by `save_desc_tbl`:

| Header offset | Meaning |
| --- | --- |
| +0x00 | user pointer to the 88-byte device/per-speed table |
| +0x04 | `extra_ptr`: user pointer to the serial-number bytes |
| +0x08 | `extra_len` (u8): serial-number length |
| +0x09 | `is_dual` → written to `gc+0x84` |
| +0x0a | `max_speed` → written to `gc+0x85` |
| +0x0b | pad |

`save_desc_tbl` copies this 12-byte header with `__copy_from_user` at
`0x602bc590`. It uses header+0 as the tree pointer (`0x602bc5d0`), header+4/+8
for the serial string (`0x602bcdbc`/`0x602bcdc8`), and header+9/+10 for
`gc+0x84`/`gc+0x85` (`0x602bcd88`/`0x602bcd90`). This matches the shim's
`struct a6400_desc_arg`.

The start path sets `gc+0x68` bit 2 **before** installing the tree, and clears
it on failure. The stop path clears bit 2 **before** `pullup(0)`, so `g_setup`
immediately stops dispatching new requests.

### 3.2 gcw state layer

`usb_gcw_register_driver` (`0x602bd66c`) is called by gadgetcore's own module
init (`0x604a58c8`) with the 0x58-byte driver object at `0x604e5020`. It:

1. allocates a 0x20-byte lock object and stores it at `gcw+0x58`;
2. copies 0x58 bytes of the caller driver to `gcw+0x00` and `gcw+0x268`;
3. overwrites the wrapped driver callbacks at `gcw+0x270..0x284`:

```text
gcw+0x270 = 0x602bd2ec gcw_bind
gcw+0x274 = 0x602bd31c gcw_unbind
gcw+0x278 = 0x602bd344 gcw_setup
gcw+0x27c = 0x602bd374 gcw_disconnect
gcw+0x280 = 0x602bd39c gcw_suspend
gcw+0x284 = 0x602bd3c4 gcw_resume
```

4. `change_gcw_state(1)`;
5. `usb_gadget_probe_driver(&gcw+0x268)`.

The wrappers forward to the original gadgetcore driver through the copied first
0x58 bytes (`gcw+0x08` bind, `+0x0c` unbind, `+0x10` setup, `+0x14` disconnect,
`+0x18` suspend, `+0x1c` resume). Thus the call chain for a host setup is:

`dwc3_ep0_delegate_req -> gcw_setup -> g_setup -> setup_req`.

State is a 32-bit word at `gcw+0x60`, protected by the lock object at
`*(u32*)(gcw+0x58)`:

```text
602bd420: 24409fe5  ldr  r4, [pc, #0x24]   ; r4 = 0x6051b24c
602bd428: 1fbbf9eb  bl   0x6012c0ac       ; __migrate_disable
602bd42c: 580094e5  ldr  r0, [r4, #0x58]  ; lock object
602bd430: 2f2504eb  bl   0x603c68f4       ; rt_spin_lock
602bd434: 580094e5  ldr  r0, [r4, #0x58]
602bd438: 605084e5  str  r5, [r4, #0x60]  ; state = arg
602bd43c: 362504eb  bl   0x603c691c       ; rt_spin_unlock
602bd440: a6baf9eb  bl   0x6012bee0       ; __migrate_enable
```

`usb_gcw_start` (`0x602bd7f8`) does **not** store the raw argument. It first
calls `get_gcw_state`; only if the state is exactly 1 does it map the argument
to a new state and call `change_gcw_state`:

```text
602bd808: 10ffffeb  bl   0x602bd450   ; get_gcw_state
602bd80c: 010050e3  cmp  r0, #1
602bd810: 0500001a  bne  0x602bd82c   ; not stopped -> -1
602bd814: 010054e3  cmp  r4, #1       ; arg == 1 ?
602bd818: 02008002  addeq r0, r0, #2  ; 1 + 2 = 3
602bd81c: 0200a013  movne r0, #2
602bd820: fbfeffeb  bl   0x602bd414   ; change_gcw_state(2 or 3)
602bd824: 0000a0e3  mov  r0, #0
```

`usb_gcw_stop` (`0x602bd834`) is `change_gcw_state(1); return 0`.

`usb_gcw_setup_setconfig` (`0x602bd850`) maps the active config value to an
expected state from a table at `0x603dfdf4 + 0x3c = 0x603dfe30`
(`config 0 -> 3`, `config 1 -> 4`, `config > 1 -> 7`) and calls
`change_gcw_state(expected)` if the current state differs. The validity gate
accepts states 2..7 and rejects states 0/1. `usb_gcw_setup_setinterface`
(`0x602bd8c4`) is a tail call to the same function.

Dynamic confirmation (real bytes, 81 checks):

| Call | Initial state | Result state | Return |
| --- | --- | --- | --- |
| `usb_gcw_start(1)` | 1 | 3 | 0 |
| `usb_gcw_start(0)` | 1 | 2 | 0 |
| `usb_gcw_start(2)` | 1 | 2 | 0 |
| `usb_gcw_start(x)` | ≠1 | unchanged | -1 |
| `usb_gcw_stop()` | 3 | 1 | 0 |
| `usb_gcw_setup_setconfig(0)` | 3 | 3 | 0 |
| `usb_gcw_setup_setconfig(1)` | 3 | 4 | 0 |
| `usb_gcw_setup_setconfig(2)` | 4 | 7 | 0 |
| `usb_gcw_setup_setconfig(0)` | 1 | unchanged | -1 |

State names (inference from values and call sites): 1 = stopped/registered,
2 = single-function started, 3 = dual-function started, 4 = configured,
5/6/7 = MTP bulk-out/completion transients used by `gcw_complete`/`gcw_queue`.

### 3.3 DWC3 pull-up: register and field

`gadget->ops->pullup` is `dwc3_gadget_pullup` (`0x602b1d3c`). The DWC3 object is
`dwc = gadget - 0x150` (first instruction: `sub r4, r0, #0x150`).

| DWC3 field | Offset from `dwc` | Meaning |
| --- | --- | --- |
| `gadget` base | +0x150 | `struct usb_gadget`; `gadget.speed` at `dwc+0x170` |
| `ep0_out` | +0xd0 | `struct usb_ep *` |
| `ep0_in` | +0xd4 | `struct usb_ep *` |
| event buffer cell | +0xcc | pointer to a 4-byte cell holding the event-buffer object; `(*cell)+0x10` bit0 is waited on |
| `gadget_driver` | +0x2b0 | `struct usb_gadget_driver *` (disconnect callback at +0x14) |
| `regs` | +0x2b4 | `devm_ioremap_nocache()` result (DWC3 register base) |
| max-speed config | +0x2d4 | compared against a constant in `run_stop` |
| software event flags | +0x2d8 | byte flags |
| `ep0state` | +0x2e0 | 1 = SETUP phase |
| `ep0_next_event` | +0x2dc | software ep0 state |

`dwc3_probe` stores the ioremap result: `0x602ae338: b48284e5 str r8,[r4,#0x2b4]`
and writes `0x40000000` to `regs+0x604` for the core soft reset
(`0x602ae464`). This proves `regs+0x604` is `DCTL` (bit 30 = CSFT soft reset).

Connect/disconnect is **DCTL bit 31 (`RUN_STOP`)** at `regs+0x604`; stop
completion is **DSTS bit 22 (`DEVCTRLHLT`, `0x400000`)** at `regs+0x60c`.

`dwc3_gadget_pullup(udc, is_on)`:

```text
602b1d48: 154e40e2  sub  r4, r0, #0x150    ; dwc
602b1d5c: 707194e5  ldr  r7, [r4, #0x170] ; old gadget.speed
602b1d60: d1e8f9eb  bl   0x6012c0ac      ; __migrate_disable
602b1d68: e15204eb  bl   0x603c68f4      ; rt_spin_lock(dwc+0x70)
602b1d6c: 000058e3  cmp  r8, #0
602b1d70: 70818405  streq r8, [r4, #0x170] ; is_on==0 -> gadget.speed=0
602b1da0: 10309ae5  ldr  r3, [sl, #0x10]  ; wait event-buffer bit0 clear
602b1dac: 0400a0e1  mov  r0, r4
602b1db0: cff9ffeb  bl   0x602b04f4      ; dwc3_stop_active_transfers(dwc)
602b1db4: 800016e5  ldr  r0, [r6, #-0x80] ; udc-0x80 = dwc+0xd0 (ep0_out)
602b1db8: 1fffffeb  bl   0x602b1a3c      ; __dwc3_gadget_ep_disable(ep0_out)
602b1dbc: 7c0016e5  ldr  r0, [r6, #-0x7c] ; dwc+0xd4 (ep0_in)
602b1dc0: 1dffffeb  bl   0x602b1a3c      ; __dwc3_gadget_ep_disable(ep0_in)
602b1dc4: 000057e3  cmp  r7, #0          ; old gadget.speed != 0 ?
602b1dcc: 0400a0e1  mov  r0, r4
602b1dd0: def4ffeb  bl   0x602af150      ; dwc3_disconnect_gadget(dwc)
602b1dd4: 0810a0e1  mov  r1, r8
602b1dd8: 0400a0e1  mov  r0, r4
602b1ddc: 86f4ffeb  bl   0x602aeffc      ; dwc3_gadget_run_stop(dwc, is_on)
602b1de8: cb5204eb  bl   0x603c691c      ; rt_spin_unlock
```

Notes:

* The wait loop at `0x602b1da0` polls `[(*[dwc+0xcc])+0x10] & 1`; on contention it
  unlocks, calls `schedule()` (`0x603c4e68`), re-locks. It is a sleeping wait in
  threaded/process context, not a busy hardirq spin.
* `dwc3_disconnect_gadget` (`0x602af150`) loads `[dwc+0x2b0]` (driver) and
  `[driver+0x14]` (disconnect), **drops dwc+0x70**, calls
  `driver->disconnect(gadget)`, then re-takes the lock. For the gadgetcore
  stack this is `gcw_disconnect -> g_disconnect -> bus_disconnect`.
* On `is_on==1` the stop/disable/disconnect block is skipped; only
  `dwc3_gadget_run_stop(dwc, 1)` executes.

`dwc3_gadget_run_stop` (`0x602aeffc`) register writes:

```text
602af008: b43290e5  ldr  r3, [r0, #0x2b4] ; regs
602af014: 043693e5  ldr  r3, [r3, #0x604] ; DCTL
602af020: 0261c303  biceq r6, r3, #0x80000000 ; stop: clear RUN_STOP
602af030: d41290e5  ldr  r1, [r0, #0x2d4]
602af03c: 1e38c393  bicls r3, r3, #0x1e0000
602af040: 0a388393  orrls r3, r3, #0xa0000    ; start-only bits 17/19
602af044: 026183e3  orr  r6, r3, #0x80000000  ; start: set RUN_STOP
602af070: 046687e5  str  r6, [r7, #0x604]     ; write DCTL
602af07c: 0c0693e5  ldr  r0, [r3, #0x60c]     ; DSTS
602af088: 010500e2  and  r0, r0, #0x400000    ; DEVCTRLHLT
602af0a4: 016056e2  subs r6, r6, #1           ; 500 attempts
602af0f4: 6d00e0e3  mvn  r0, #0x6d            ; -ETIMEDOUT
```

The exact meaning of DCTL bits 17/19 (set on start, cleared with mask
`0x1e0000`) is **inference/undecoded**; they are not needed to control the
pull-up. A module must call `pullup()`/`run_stop()` rather than write DCTL
directly.

### 3.4 UDC core and the standard `soft_connect` sysfs ABI

`usb_gadget_probe_driver` (`0x602b4ba8`) takes the UDC mutex
(`_mutex_lock 0x603c6998` on `0x604e4e44`) and calls
`udc_bind_to_driver(udc, driver)` (`0x602b4af0`):

1. `udc->driver = driver`, `gadget->driver_data = driver+0x20`;
2. `driver->bind` (`driver+0x08`) — for gcw, `gcw_bind -> g_bind`;
3. `gadget->ops->udc_start` (`ops+0x20`) — `dwc3_gadget_start`;
4. `kobject_uevent`.

`usb_gadget_remove_driver` (`0x602b4a04`) does, in order:

1. `driver->disconnect` (`driver+0x14`);
2. `driver->unbind` (`driver+0x0c`);
3. `gadget->ops->udc_stop` (`ops+0x24`) — `dwc3_gadget_stop`;
4. clears `udc->driver`.

`dwc3_gadget_stop` (`0x602af334`) only clears `dwc+0x2b0` and frees the IRQ; it
does **not** write DCTL. Therefore **unregistering a gadget driver does not
lower D+**. Only `pullup(0)` does.

`usb_udc_softconn_store` (`0x602b4f6c`) is the standard sysfs
`soft_connect` attribute:

```text
602b4fa4: ldr  r1, [pc, #0x7c] ; "connect"
602b4fa8: bl   0x60260bcc      ; sysfs_streq
602b4fb0: beq  0x602b4fd0
602b4fc4: movne r1, #1
602b4ffc: blx  r2              ; ops->pullup(gadget, 1)
...
602b4fd4: ldr  r1, [pc, #0x50] ; "disconnect"
602b4ff8: mov  r1, r7          ; 0
602b4ffc: blx  r2              ; ops->pullup(gadget, 0)
```

It calls `gadget->ops+0x14` directly, with no gadgetcore lock. Writing
`disconnect`/`connect` to `/sys/class/udc/<name>/soft_connect` is therefore an
alternative ABI to ioctl `0xE204`/`0x400CE203`, but it does **not** clear
`gc+0x68` bit 2, stop interfaces, or free the tree. Do not use it as a
replacement for the gadgetcore stop sequence.

### 3.5 SET_CONFIGURATION / SET_INTERFACE handlers

`g_setup` (`0x602b8328`) is the UDC `driver->setup` callback:

```text
602b8334: 300080e2  add  r0, r0, #0x30
602b8338: 0140a0e1  mov  r4, r1
602b833c: 978bffeb  bl   0x6029b1a0   ; dev_get_drvdata(gadget+0x30)
602b8340: 683090e5  ldr  r3, [r0, #0x68]
602b8344: 5331e0e7  ubfx r3, r3, #2, #1
602b8348: 000053e3  cmp  r3, #0
602b834c: 0200000a  beq  0x602b835c   ; not started -> return 0
602b8350: 0410a0e1  mov  r1, r4
602b8354: 520400eb  bl   0x602b94a4   ; setup_req(gc, setup)
```

`setup_req` (`0x602b94a4`) dispatches standard requests; the relevant branches:

| bRequest | Handler | Address |
| --- | --- | --- |
| 6 GET_DESCRIPTOR | switch on `setup[3]` | `0x602b9528` |
| 9 SET_CONFIGURATION | config handler | `0x602b9650` |
| 11 SET_INTERFACE | interface handler | `0x602b9954` |
| class/vendor (`setup[0] & 0x60`) | registered driver callbacks `+0x2c`/`+0x30` | `0x602b9ffc` |

SET_CONFIGURATION (`0x602b9650`) with `wValue` in r6:

* `wValue == 0`: `stop_config(gc)`, `gc+0x74 = 0`.
* `wValue != 0`: `get_config_desc_from_config_num(gc, wValue)`; then an
  endpoint-admission scan over every interface/alternate/endpoint (see §6.8);
  on the successful scan path (`0x602ba42c..0x602ba440`) it stores the config
  value at `gc+0x74` (`strb sl,[r4,#0x74]`) and calls
  `make_alt_num_list(gc)` (`0x602bb774`), which allocates the `gc+0x70`
  `{ifnum, alt=0}` list (`cfg[2]*2` bytes); then per-interface
  `start_interface(gc, ifnum)`;
  `gc+0xc = setup_set_config_comp` (`0x602b939c`); `clear_halt_ep0(gc)`;
  `usb_gcw_setup_setconfig(gc+0x74)`.

```text
602b98c4: 043097e5  ldr  r3, [r7, #4]
602b98d0: 8611d3e7  ldrb r1, [r3, r6, lsl #3] ; group[0] interface number
602b98d4: 27feffeb  bl   0x602b9178      ; start_interface
602b98f4: 543b9fe5  ldr  r3, [pc, #0xb54] ; 0x602b939c setup_set_config_comp
602b98fc: 0c3084e5  str  r3, [r4, #0xc]   ; gc+0xc completion callback
602b9900: 9afdffeb  bl   0x602b8f70      ; clear_halt_ep0
602b9904: 7400d4e5  ldrb r0, [r4, #0x74]  ; active config value
602b9908: d00f00eb  bl   0x602bd850      ; usb_gcw_setup_setconfig(config)
```

SET_INTERFACE (`0x602b9954`) uses `get_alt_num`, `get_if_table_desc`,
`stop_interface`, `start_interface`, `set_alt_num`, stores the new
alternate/interface in `gc+0x10`/`gc+0x11`, sets `gc+0xc` to
`setup_set_interface_comp` (`0x602b93fc`), clears EP0 halt, and calls
`usb_gcw_setup_setinterface(gc+0x74)` (which is the same state adjustment as
SET_CONFIG).

`clear_halt_ep0` (`0x602b8f70`) just `gc+0x83 = 0`. `ep0_complete`
(`0x602b8f38`) calls `[gc?]->[0xc]` completion and clears it.

### 3.6 What happens to endpoints during disconnect

Two independent layers run:

**(a) DWC3 layer, unconditionally on `pullup(0)`:**

* `dwc3_stop_active_transfers(dwc)` (`0x602b04f4`) walks the controller's
  endpoint table and calls `dwc3_remove_requests()` for every active endpoint.
* `__dwc3_gadget_ep_disable(dwc->ep0_out)` and
  `__dwc3_gadget_ep_disable(dwc->ep0_in)` (`0x602b1a3c`) remove requests,
  optionally halt, clear the endpoint-enable bit in `DALEPENA`
  (`regs+0x620`), and clear endpoint software state.
* `dwc3_gadget_run_stop(dwc, 0)` clears DCTL.RUN_STOP.

**(b) gadgetcore layer, via the disconnect callback (only if
`gadget.speed != 0` before the stop):**

`dwc3_disconnect_gadget` → `gcw_disconnect` → `g_disconnect` →
`bus_disconnect` (`0x602bd264`):

```text
602b278: bl 0x602b6554   ; usb_otgcore_gadget_disconnect
602b280: bl 0x602b9464   ; setup_disconnect(gc)
602b28c: ldr r0,[r5]     ; node->driver
602b290: ldr r3,[r0,#0x28] ; driver->disconnect
602b29c: blx r3
...
602b2b8: ldr r2,[gc+0x14] ; registered event callback
602b2c4: ldr r1,[gc+0x24]
602b2e0: bl 0x602b5c14   ; usb_event_add_queue(event 3)
```

`setup_disconnect` (`0x602b9464`) takes the `gc+0x4c` lock and calls
`stop_config` + `clear_halt_ep0`. `stop_config` (`0x602b90cc`):

1. if `gc+0x74 == 0`, return 0 (nothing configured);
2. `get_config_desc_from_config_num(gc, gc+0x74)`;
3. `free_alt_num_list(gc)` (`gc+0x70`);
4. for every interface number in `config[4][i]`: `stop_interface(gc, ifnum)`;
5. `gc+0x74 = 0`, `gc+0x82 = 0`;
6. `gadget->ops->ioctl(gadget, 1, 0)` (DWC3 returns 0, no-op).

`stop_interface` (`0x602b8f8c`) walks the registered driver list `gc+0x78`:

* for every node whose driver matches the active config and interface and is
  active (`node+0x14 != 0`): clear the active flag, call `driver->STOP`
  (`driver+0x14`), then for each wrapper in `node+0x10[0..node+0xc-1]` call
  `ep_ctrl_delete_ep(gc, wrapper)` and `kfree(node+0x10)`;
* then walk the list again and call `driver+0x14` for wildcard nodes
  (`driver+4 == 0xffff`);
* finally `ep_ctrl_disable_ep(gc, ifnum)`.

`ep_ctrl_delete_ep` (`0x602ba968`) is just `kfree(wrapper)` +
`usb_gcw_register_ep_ops(0x604e5108)`. `ep_ctrl_disable_ep` (`0x602ba85c`)
finds the underlying `struct usb_ep` for that interface and calls
`usb_ep->ops->disable` — for DWC3 that is `dwc3_gadget_ep_disable`
(`0x602b1df8`) → `__dwc3_gadget_ep_disable` (`0x602b1a3c`).

Consequences:

* After `pullup(0)` returns and `setup_disconnect` has run, no
  interface-endpoint wrapper remains, no endpoint is enabled, EP0 is disabled,
  and `gc+0x74 == 0`. Only then may the descriptor tree be freed.
* If the host never issued SET_CONFIGURATION (`gc+0x74 == 0`), only the DWC3
  EP0/stop layer runs; there is no interface endpoint to stop.
* If a module swaps `gc+0x6c` **before** the disconnect callback runs,
  `stop_config`/`stop_interface` will traverse the new tree and stop the wrong
  interface numbers. Keep the old tree installed until after
  `pullup(0)`/`setup_disconnect` completes.

### 3.6.1 Function-driver registration object (for reference)

`usb_gadgetcore_register_driver` (`0x602b8610`) allocates a 0x18-byte list node
(`kmem_cache_alloc`, trace size 0x18) and links it at `gc+0x78`. The node:

| Node offset | Meaning |
| --- | --- |
| +0x00 | pointer to the caller's driver object |
| +0x04 | list next |
| +0x08 | list prev |
| +0x0c | endpoint-wrapper count (u8) |
| +0x10 | endpoint-wrapper array pointer |
| +0x14 | active flag (u8) |

The caller's driver object must have non-NULL `+0x10` (START) and `+0x14`
(STOP); register returns -EINVAL otherwise. Verified offsets used by the native
code:

| Driver offset | Callback |
| --- | --- |
| +0x04 | bConfigurationValue match |
| +0x05 | bInterfaceNumber match |
| +0x10 | START (`start_interface` calls it with the interface/alt context) |
| +0x14 | STOP (`stop_interface`, `stop_other_driver` call it) |
| +0x18 | standard-request setup callback |
| +0x20 | SUSPEND (`bus_suspend`) |
| +0x24 | RESUME (`bus_resume`) |
| +0x28 | DISCONNECT (`bus_disconnect`) |
| +0x2c | class-request callback |
| +0x30 | vendor-request callback |

`usb_gadgetcore_stop_other_driver(gc, keep_driver)` (`0x602b8744`) is the
"stop other function drivers" ABI: if `gc+0x68` bit 2 is clear it returns 0;
otherwise it locks `gc+0x30`, walks `gc+0x78`, and for every node whose
driver != `keep_driver` and whose active flag is set: clears active, calls
`driver->STOP` (+0x14), deletes each endpoint wrapper
(`ep_ctrl_delete_ep`), and `kfree`s the wrapper array. This is separate from
`usb_gcw_stop()` (state only) and from the ioctl stop (full UDC disconnect).

### 3.7 Clean re-enumeration order (verified call graph)

```text
 1. ensure app is idle; restore E0407a patches to stock (§4.5)
 2. test_and_clear_bit(2, gc+0x68)                 ; gate off
 3. gadget->ops->pullup(gadget, 0)                ; dwc3_gadget_pullup
       lock dwc+0x70
       gadget.speed = 0
       wait event-buffer bit0 clear (schedule if needed)
       dwc3_stop_active_transfers(dwc)
       __dwc3_gadget_ep_disable(dwc->ep0_out / ep0_in)
       if old gadget.speed != 0:
           dwc3_disconnect_gadget -> driver->disconnect (outside dwc lock)
               gcw_disconnect -> g_disconnect -> bus_disconnect
                   usb_otgcore_gadget_disconnect
                   setup_disconnect -> stop_config -> per-interface STOP,
                                       ep_ctrl_delete_ep, ep_ctrl_disable_ep
                   driver->disconnect (+0x28)
                   usb_event_add_queue(event 3)
       dwc3_gadget_run_stop(dwc,0): DCTL.bit31=0, poll DSTS.bit22
       unlock dwc+0x70
 4. setup_disconnect(gc)                           ; defensive; now a no-op
 5. usb_gcw_stop()                                 ; gcw state = 1
 6. free_desc_tbl(gc)                              ; old tree freed, gc+0x6c=0
 7. ---- descriptor change ----
    save_desc_tbl(gc, &hdr)                        ; deep copy, gc+0x6c=new
    (or: gc+0x6c = module-owned tree)
 8. usb_gcw_start(is_dual)                         ; 1 -> 2/3
 9. arm EP0 (shim-proven; native ioctl start does not do it):
       __dwc3_gadget_ep_enable(ep0_out, desc=0x604e4e24, 0, 0)
       __dwc3_gadget_ep_enable(ep0_in,  desc=0x604e4e24, 0, 0)
       *(u32*)(dwc+0x2e0) = 1                     ; EP0_SETUP_PHASE
       dwc3_ep0_out_start(dwc)
10. test_and_set_bit(2, gc+0x68)                  ; gate on before D+ high
11. gadget->ops->pullup(gadget, 1)                ; DCTL.bit31=1
```

Native ioctl start differs in ordering: it sets bit 2 at the very top, calls
`save_desc_tbl`, `usb_gcw_start`, then `pullup(1)`, and clears bit 2 on any
failure. The safe equivalent for a module is to set bit 2 after the tree is
installed and before `pullup(1)`; setting it only after `pullup(1)` (the shim
order) leaves a window where the host can send SETUP while `g_setup` still
returns 0.

The shim's `a6400_arm_ep0` is required after a manual `pullup(0)` /
`pullup(1)` cycle; the native start path does not call it, but the shim found
that after its own quiesce the EP0 setup TRB must be re-armed. Treat it as part
of the module's proven order, not as part of the ioctl ABI.

---

## 4. Locking and context rules

### 4.1 Lock inventory

| Lock | Address / field | Type | Protects | Acquired by |
| --- | --- | --- | --- | --- |
| gadgetcore driver lock | `gc+0x30` | `rt_spin_lock` (PREEMPT_RT sleeping lock) | driver list `gc+0x78`/`0x7c`, node fields, 28-byte object at `gc+0x14` | `usb_gadgetcore_register_driver`, `unregister_driver`, `stop_other_driver`, ioctl `0xE202`/`0x401CE201` |
| gadgetcore config lock | `gc+0x4c` | `rt_spin_lock` | active config/interface teardown (`gc+0x74`, `gc+0x82`) | `setup_disconnect` only |
| gcw lock | `*(u32*)(gcw+0x58)` (0x20-byte object) | `rt_mutex` + `rt_spin_lock` | gcw state `gcw+0x60`, MTP staging `gcw+0x64`/`+0x264` | `change/get_gcw_state`, `gcw_complete`, `gcw_queue` |
| DWC3 lock | `dwc+0x70` | `rt_spin_lock` | UDC/endpoint register state | `dwc3_thread_interrupt`, `dwc3_gadget_pullup`, ep enable/disable, etc. |
| UDC list mutex | `0x604e4e44` | `_mutex_lock` | `udc` list / bind/unbind | `usb_gadget_probe_driver`, `usb_gadget_unregister_driver` |
| address-limit / migration | `__migrate_disable` `0x6012c0ac`, `__migrate_enable` `0x6012bee0` | — | surrounds every `rt_spin_lock` in gadgetcore/gcw/DWC3 | as above |

Runtime lock functions: `rt_spin_lock` `0x603c68f4`, `rt_spin_unlock`
`0x603c691c`, `_mutex_lock` `0x603c6998`, `_mutex_unlock` `0x603c69c0`,
`schedule` `0x603c4e68`.

`gc+0x30` and `gc+0x4c` are initialized at gadgetcore module init
(`0x604a5860..0x604a58a4`) with `__rt_mutex_init` + `__rt_spin_lock_init`.
They are **sleeping** locks; they may not be taken from hardirq or atomic
context.

Lock-coverage gaps that matter for a module:

* `gc+0x4c` is taken only by `setup_disconnect`. `setup_req`'s
  SET_CONFIGURATION(0) path calls `stop_config` **without** it
  (`0x602b967c`), so the lock does not serialize config teardown against the
  setup path; the single threaded IRQ does.
* `gc+0x30` protects driver-list **mutations** (register/unregister/
  stop_other_driver/ioctl install), but `stop_interface` and `start_interface`
  walk `gc+0x78` without it. Driver-list mutation is additionally gated by
  `gc+0x68` bit 2: register/unregister return -EBUSY while started.
* The descriptor root has no lock at all (§4.3).

### 4.2 Context inventory

| Path | Context | Evidence |
| --- | --- | --- |
| gadgetcore module init / probe | process (initcall) | `usb_gcore_module_init 0x604a580c` calls `usb_gcw_register_driver` → `usb_gadget_probe_driver` |
| `/dev/gadgetcore` open/ioctl/start/stop | camera app process | cdev `file_operations` (`usb_gadgetcore_open 0x602b8814`, ioctl `0x602b8844`) |
| DWC3 gadget events: disconnect, reset, EP0 setup, endpoint completion | **threaded IRQ** kthread | `dwc3_gadget_start` calls `request_threaded_irq(irq, NULL, dwc3_thread_interrupt, 0x2080, name, dwc)` at `0x602af3e8`; handler = NULL, thread_fn = `0x602b1378`, flags contain `IRQF_ONESHOT` (0x2000) |
| `dwc3_thread_interrupt` | threaded IRQ; takes `dwc+0x70`, then calls `dwc3_ep0_interrupt`, `dwc3_endpoint_transfer_complete`, `dwc3_gadget_disconnect_interrupt`, `dwc3_gadget_reset_interrupt` | `0x602b139c rt_spin_lock`; BL targets at `0x602b1444`, `0x602b14b8`, `0x602b1584`, `0x602b1590` |
| `dwc3_ep0_delegate_req` → `driver->setup` | threaded IRQ, **dwc+0x70 dropped** around the callback | `0x602b2900 rt_spin_unlock` + `0x602b2904 __migrate_enable`; call `[dwc+0x2b0]+0x10` at `0x602b2918`; re-lock at `0x602b2928` |
| `g_setup`/`setup_req`/serializers | threaded IRQ, no gadgetcore lock | `g_setup` only tests `gc+0x68` bit2; no `rt_spin_lock` in `setup_req` |
| EP0 completion | threaded IRQ | `dwc3_endpoint_transfer_complete.clone.12 0x602b0c6c` is called from `dwc3_thread_interrupt` at `0x602b14b8`; request complete callback then runs |
| `dwc3_gadget_pullup` | process (ioctl) **or** threaded IRQ (e.g. softconn / internal calls); takes `dwc+0x70`, sleeps in the event-buffer wait | see §3.3 |
| `bus_disconnect` / `setup_disconnect` | threaded IRQ (via disconnect callback) **or** process (ioctl stop) | called from `dwc3_disconnect_gadget` (threaded IRQ, lock dropped) and from ioctl stop |
| `free_desc_tbl` | process (ioctl stop) or `save_desc_tbl` failure path | `0x602b8a98`, `0x602bcdac` |

There is **no gadgetcore path in hardirq/atomic context** on this kernel. The
DWC3 IRQ is requested as threaded-only (`handler == NULL`), so the
PREEMPT_RT sleeping locks are legal.

### 4.3 The root pointer is read locklessly

`gc+0x6c` is a plain pointer. The complete set of readers/writers in the
gadgetcore region (from `scan_gc.py`, 164 field hits filtered to `0x6c`):

| Function | Address(es) | Access |
| --- | --- | --- |
| `get_config_desc_from_config_num` | `0x602bb638` | read root, select speed record |
| `is_hnp_capable` | `0x602bb930` | read root |
| `make_device_desc` | `0x602bb9a8` | read root |
| `make_hid_desc` | `0x602bbaa8` | read root |
| `make_report_desc` | `0x602bbc08` | read root |
| `make_config_desc` | `0x602bbc78` | read root |
| `make_device_qualifier_desc` | `0x602bc00c` | read root |
| `make_string_desc` | `0x602bc0e4` | read root |
| `make_bos_desc` | `0x602bc280` | read root |
| `setup_req` (BOS bcdUSB check) | `0x602b9628` | read root |
| `save_desc_tbl` | `0x602bc5c8` (write), `0x602bc614/624/638/64c/6e0/8f8/cdc0` (read) | install/read |
| `free_desc_tbl` | `0x602bc3f4/40c/420/438/500/534/548` | read/free/null |

None of these take `gc+0x30`, `gc+0x4c`, or any other lock around the root
access. There is no RCU, no `rcu_dereference`, no refcount, and no
`synchronize_rcu`. The only native protections are:

1. `gc+0x68` bit 2: `g_setup` refuses to call `setup_req` when it is clear;
2. the single DWC3 threaded-IRQ kthread serializes all `setup_req` calls with
   each other;
3. the ioctl stop path clears bit 2 and pulls D+ low before freeing the tree.

**Race caveat (important):** `dwc3_ep0_delegate_req` drops `dwc+0x70` around
`driver->setup`. Therefore `pullup(0)` (which takes `dwc+0x70`) is **not** a
strict barrier against a `setup_req` that is already in flight in the threaded
IRQ. If the module needs a hard guarantee, it should obtain the UDC IRQ number
and call `synchronize_irq()` after `pullup(0)` and before freeing/swapping the
tree, or restrict the swap to a host-idle window. The native ioctl stop does not
perform such a synchronization; this is a latent native race, not a contrived
one.

### 4.4 Safe root-swap protocol

Use this order (addresses are the functions from §3):

1. **Quiesce the app:** no mode switch/reconfiguration in progress; `gc+0x68`
   bit 2 state known. Restore E0407a patches (§4.5).
2. `test_and_clear_bit(2, gc+0x68)` (`_test_and_clear_bit` `0x60259588`). If it
   was already 0, the UDC is already stopped; still run the remaining teardown
   defensively.
3. `gadget->ops->pullup(gadget, 0)` (`dwc3_gadget_pullup` `0x602b1d3c`) and
   optionally `synchronize_irq()`.
4. `setup_disconnect(gc)` (`0x602b9464`) — idempotent after the callback path.
5. `usb_gcw_stop()` (`0x602bd834`) — gcw state 1.
6. Free or detach the old tree:
   * kernel-owned root: `free_desc_tbl(gc)` (`0x602bc3e4`) → `gc+0x6c = 0`;
   * module-owned root currently in `gc+0x6c`: **do not** call
     `free_desc_tbl`; save the old kernel root first and restore it, or install
     the module root only after the old root has been detached and freed by its
     owner.
7. Install the new tree:
   * `save_desc_tbl(gc, &hdr12)` — gadgetcore allocates and owns a deep copy;
     the source may be freed after return; `hdr12` must be accessible to
     `__copy_from_user` (kernel module: temporarily set
     `current_thread_info()->addr_limit = KERNEL_DS`, the precedent in
     `tools/native_camera/uvc_composite_shim.c:686-688`), or
   * `*(void **)(gc+0x6c) = module_tree` — module owns lifetime; must remain
     valid and unchanged for the entire installed interval.
8. `usb_gcw_start(is_dual)` (`0x602bd7f8`).
9. Arm EP0 (`__dwc3_gadget_ep_enable` `0x602b05fc` for `dwc+0xd0`/`dwc+0xd4`
   with descriptor `0x604e4e24`, `*(u32*)(dwc+0x2e0)=1`,
   `dwc3_ep0_out_start` `0x602b2b40`) — required after a manual pull-down cycle
   per the shim.
10. `test_and_set_bit(2, gc+0x68)` — gate on before D+ high.
11. `pullup(gadget, 1)`.

Do **not** swap the root:
* while bit 2 is set;
* before `pullup(0)`/`setup_disconnect` completes (the disconnect callback reads
  the tree to find interfaces to stop);
* from an IRQ/atomic context;
* while a `GET_DESCRIPTOR`/`SET_CONFIGURATION` may be in flight (see race caveat).

### 4.5 The three E0407a patches and app-initiated reconfiguration

E0407a changed three volatile targets. Their current decoded meanings:

| Target | Address | Meaning | Interaction with app reconfiguration |
| --- | --- | --- | --- |
| OS string | `0x604e5130`, 18 bytes | `MSFT100` + vendor code 0x30; read by `make_string_desc` only for string index `0xEE` and only when `gc+0x84 != 0` (`0x602bc15c`) | static rodata, not overwritten by app; restore on unload and before allowing a mode change |
| `gc+0x84` | 1 byte | `is_dual` / mode: 0 = single-function (gcw state 2), 1 = dual-function (gcw state 3); also the MS OS 0xEE gate | **overwritten by every `save_desc_tbl` start** from header byte +9; stock is 0 |
| `gc+0x85` | 1 byte | `max_speed` from header byte +10; no reader found in the gadgetcore window | overwritten by start; stock observed 1 |
| bcdUSB | selected per-speed record `+0x00`, 2 bytes | device descriptor `bcdUSB` | the tree is **freed by app stop and rebuilt by app start**, so a patch is lost at the next start |

Therefore, before any app-initiated USB reconfiguration (mode switch, app
stop/start, liveview gadget recreate):

1. restore the OS string to stock `MSFT100`/0x30;
2. restore `gc+0x84 = 0` (stock single-function) — otherwise the app's
   `save_desc_tbl` may combine its own `is_dual` with the module's state
   expectations, and the 0xEE handler must not remain enabled;
3. restore the bcdUSB halfword (and note the correct record: `root+0x00` for
   HIGH, §6.2);
4. if the module owns `gc+0x6c`, restore the original kernel root before the
   app can call stop/`free_desc_tbl`.

After the app's reconfiguration completes, the module may re-apply its patches
and re-install its overlay only through the full safe protocol above.

---

## 5. Native descriptor tree: layout, allocation, ownership

### 5.1 Root — 88 bytes (`0x58`), `gc+0x6c`

Allocated by `save_desc_tbl` with `kmem_cache_alloc` + `kmalloc_add_trace(...,
0x58, ...)` at `0x602bc5a4..0x602bc5c8`; installed at `gc+0x6c` at
`0x602bc5c8`. A second `kmem_cache_alloc`/trace pair is not used for the root.

| Offset | Size | Field | Notes |
| --- | --- | --- | --- |
| +0x00 | 0x10 | per-speed record 0 | HIGH speed (speed 3) |
| +0x10 | 0x10 | per-speed record 1 | FULL speed (else) |
| +0x20 | 0x10 | per-speed record 2 | SUPER speed (speed 5) |
| +0x30 | 2 | idVendor | little-endian; live 0x054C |
| +0x32 | 2 | idProduct | live 0x0CAA / patched 0x0322 |
| +0x34 | 2 | bcdDevice | live 0x0100 |
| +0x36 | 1 | unknown/reserved | ZV-E10 template 0x80; not read by `make_device_desc` |
| +0x37 | 1 | iManufacturer | |
| +0x38 | 1 | iProduct | |
| +0x39 | 1 | iSerialNumber | `save_desc_tbl` searches the string table for this index and (re)assigns the serial bytes |
| +0x3a | 1 | language count | number of 8-byte language entries |
| +0x3b | 1 | pad | |
| +0x3c | 4 | language array pointer | array of `lang_count * 8` bytes |
| +0x40 | 2 | serial string length (tree copy) | `save_desc_tbl` deep-copies `root[0x40]` bytes from `root+0x44` into a new `root+0x44` buffer at `0x602bc66c` |
| +0x42 | 2 | pad | |
| +0x44 | 4 | serial string pointer (tree copy) | deep-copied buffer of `+0x40` bytes; the final iSerial string data comes from the ioctl header +4/+8 in the dedup pass |
| +0x48 | 4 | unused/reserved | not read or freed by the decoded code; template 0 |
| +0x4c | 4 | optional 4-byte blob pointer | `save_desc_tbl` deep-copies 4 bytes; `free_desc_tbl` frees |
| +0x50 | 4 | optional 8-byte blob pointer | deep-copies 8 bytes |
| +0x54 | 4 | optional 16-byte blob pointer | deep-copies 16 bytes |

The root itself is not a USB wire structure; it is Sony's internal per-speed
device table.

### 5.2 Per-speed record — 16 bytes (`0x10`)

| Offset | Size | Field | Used by |
| --- | --- | --- | --- |
| +0x00 | 2 | bcdUSB | `make_device_desc` out[2..3], qualifier out[2..3], BOS gate |
| +0x02 | 1 | bDeviceClass | `make_device_desc` out[4], qualifier out[4] |
| +0x03 | 1 | bDeviceSubClass | out[5] |
| +0x04 | 1 | bDeviceProtocol | out[6] |
| +0x05 | 1 | bNumConfigurations | `make_device_desc` out[17], qualifier out[8], config-array loop count |
| +0x06 | 1 | unknown/reserved | ZV-E10 template 0x00 |
| +0x07 | 1 | pad | |
| +0x08 | 4 | config array pointer | array of `bNumConfigurations * 24` bytes |
| +0x0c | 4 | unused | template 0 |

### 5.3 Configuration — 24 bytes (`0x18`)

Allocated by `save_config_desc` as `entry[5] * 0x18` and installed at
`record+0x08`.

| Offset | Size | Field | Used by |
| --- | --- | --- | --- |
| +0x00 | 1 | GET_DESCRIPTOR config index | `make_config_desc` matches `setup[2]` (wValue low); normally 0 |
| +0x01 | 1 | bConfigurationValue | `make_config_desc` out[5], `get_config_desc_from_config_num` match |
| +0x02 | 1 | bNumInterfaces | config descriptor out[4]; interface-array loop count |
| +0x03 | 1 | pad | |
| +0x04 | 4 | interface group array pointer | `bNumInterfaces * 8` bytes |
| +0x08 | 1 | iConfiguration | config descriptor out[6] |
| +0x09 | 1 | bmAttributes | out[7] (live 0xC0/0x80) |
| +0x0a | 1 | bMaxPower | out[8] (live 0x01 / 0xFA) |
| +0x0b | 1 | pad | |
| +0x0c | 4 | optional 1-byte blob pointer | if non-zero, `make_config_desc` emits 3 bytes `{0x03,0x09,*(u8*)ptr}` before the interfaces and adds 3 to `wTotalLength`; **not exercised by the live/ZV-E10 trees (0)**; semantics unproven |
| +0x10 | 1 | count of 6-byte records | `save_config_desc` allocates `count*6` at +0x14; **`make_config_desc` never reads it** |
| +0x14 | 4 | 6-byte record pointer | copied/owned but **not serialized**; bytes look like IAD payloads `{first,count,class,subclass,protocol,iFunction}` |

### 5.4 Interface group — 8 bytes

Allocated by `save_config_desc` as `cfg[2] * 8` at `cfg+0x04`.

| Offset | Size | Field | Used by |
| --- | --- | --- | --- |
| +0x00 | 1 | bInterfaceNumber | interface descriptor out[2], `get_interface_desc` match |
| +0x01 | 1 | alternate count | alternate-array loop count |
| +0x02 | 2 | pad | |
| +0x04 | 4 | alternate array pointer | `alt_count * 20` bytes |

### 5.5 Alternate setting — 20 bytes (`0x14`)

Allocated by `save_config_desc` as `grp[1] * 0x14` at `grp+0x04`.

| Offset | Size | Field | Used by |
| --- | --- | --- | --- |
| +0x00 | 1 | bAlternateSetting | interface descriptor out[3]; `get_if_table_desc` match |
| +0x01 | 1 | bNumEndpoints | interface descriptor out[4]; endpoint-array loop count |
| +0x02 | 2 | pad | |
| +0x04 | 4 | endpoint array pointer | `ep_count * 20` bytes |
| +0x08 | 1 | bInterfaceClass | out[5] |
| +0x09 | 1 | bInterfaceSubClass | out[6] |
| +0x0a | 1 | bInterfaceProtocol | out[7] |
| +0x0b | 1 | iInterface | out[8] |
| +0x0c | 4 | extra blob size | if non-zero, copied at +0x10; low 16 bits added to `wTotalLength`; bytes emitted verbatim after the 9-byte interface descriptor |
| +0x10 | 4 | extra blob pointer | |

### 5.6 Endpoint — 20 bytes (`0x14`)

Allocated by `save_config_desc` as `alt[1] * 0x14` at `alt+0x04`.

| Offset | Size | Field | Used by |
| --- | --- | --- | --- |
| +0x00 | 1 | bEndpointAddress | endpoint descriptor out[2] |
| +0x01 | 1 | bmAttributes | out[3] |
| +0x02 | 2 | wMaxPacketSize | out[4..5] |
| +0x04 | 1 | bInterval | out[6] |
| +0x05 | 3 | pad | |
| +0x08 | 4 | extra blob size | low 16 bits added to `wTotalLength`; bytes copied from +0x0c |
| +0x0c | 4 | extra blob pointer | |
| +0x10 | 4 | SuperSpeed companion pointer | if speed==5 and non-zero, 6-byte companion `{6,0x30,ptr[0..3]}` is emitted; `save_desc_tbl` deep-copies 4 bytes |

### 5.7 String tables

| Object | Layout |
| --- | --- |
| language entry (8 bytes) | +0x00 u16 language ID; +0x02 u8 string count; +0x03 pad; +0x04 pointer to `count * 8` string entries |
| string entry (8 bytes) | +0x00 u8 string index; +0x01 u8 byte length (capped at 0xFD by the serializer); +0x02 u16 pad; +0x04 pointer to `length` bytes (raw UTF-16LE for real strings) |

`save_desc_tbl` deep-copies: the language array (`root[0x3a] * 8`), each
language's string-entry array (`lang[2] * 8`), and each string's data
(`entry[1]` bytes). It then searches for the entry whose index equals
`root+0x39` (iSerialNumber); if absent it grows the string-entry array by one.
In both cases the serial data is taken from the 12-byte ioctl header's
`extra_ptr`/`extra_len` (header +4/+8), not from the copied string entry: the
existing entry data is freed and replaced (or the new entry is filled) with
`__copy_from_user(extra_ptr, extra_len)` at `0x602bcc54` (replace) or
`0x602bcd20` (grow). This dedup/replace pass is entered only when header
`extra_ptr` (+4) is non-zero (`0x602bcdbc..0x602bcdcc`); if it is zero the pass
is skipped. The tree's `root+0x40`/`root+0x44` serial bytes are separately
deep-copied at `0x602bc66c`.

### 5.8 Original allocation trace

Executed with the real `save_desc_tbl` bytes and a two-interface fixture
(interface 0 MSC with one endpoint, interface 1 zero-endpoint vendor). The
allocator stubs only return memory and record the requested sizes; every size
below is the value the original instruction passes to `__kmalloc` /
`kmalloc_add_trace`.

Per `save_config_desc` pass (three passes: root+0x00, +0x10, +0x20):

| Order | Original call | Requested size |
| --- | --- | --- |
| 1 | `__kmalloc` config array | `record[5] * 0x18` |
| 2 | `__kmalloc` interface array | `cfg[2] * 8` |
| 3 | `__kmalloc` alternate array (interface 0) | `grp[1] * 0x14` |
| 4 | `__kmalloc` endpoint array | `alt[1] * 0x14` |
| 5 | `kmem_cache_alloc` SS companion | 4 (trace size; only if `ep+0x10 != 0`) |
| 6 | `__kmalloc` alternate array (interface 1) | `grp[1] * 0x14` |
| — | `__kmalloc` alt extra | `alt[0xc]` (only if non-zero) |
| — | `__kmalloc` endpoint extra | `ep[8]` (only if non-zero) |
| — | `kmem_cache_alloc` config 1-byte blob | 4 (trace size 1; only if `cfg[0xc] != 0`) |
| — | `__kmalloc` config 6-byte array | `cfg[0x10] * 6` (only if non-zero) |

Root and tail:

| Order | Original call | Requested size |
| --- | --- | --- |
| 0 | `kmem_cache_alloc` root | 0x58 |
| after 3 passes | `__kmalloc` serial bytes | `root[0x40]` |
| | `__kmalloc` language array | `root[0x3a] * 8` |
| | `__kmalloc` string-entry array (per language) | `lang[2] * 8` |
| | `__kmalloc` string bytes (per entry) | `entry[1]` |
| | `kmem_cache_alloc` root+0x4c blob | 4 (trace size 4) |
| | `kmem_cache_alloc` root+0x50 blob | 8 (trace size 8) |
| | `kmem_cache_alloc` root+0x54 blob | 0x10 (trace size 16) |
| dedup | `__kmalloc` string-entry array grow | `(lang[2]+1) * 8` (if iSerial entry absent and header `extra_ptr != 0`) |
| dedup | `__kmalloc` serial bytes | header `extra_len` (+8), copied from header `extra_ptr` (+4) |

The executed fixture produced 25 allocations in this order (three passes of six
plus root + six tail allocations), confirming that the tree is a graph of
separate small allocations, not one block. See
`artifacts/analysis/e0407b1-work/verify/allocator-manifest.json`.

### 5.9 Free path and ownership

`free_desc_tbl(gc)` (`0x602bc3e4`):

1. if `gc+0x6c == 0`, return;
2. `free_config_desc(root+0x00)`;
3. `free_config_desc(root+0x10)`;
4. **does not call `free_config_desc(root+0x20)`** — the third (SuperSpeed)
   config tree is not freed (verified: the executed 25-allocation tree leaked
   exactly six allocations: config 24, iface 16, alt 20, ep 20, companion 4,
   alt 20);
5. `kfree(root+0x44)` serial bytes;
6. for each language: `kfree` each string's bytes, `kfree` the string-entry
   array; then `kfree(root+0x3c)` language array;
7. `kfree(root+0x4c)`, `kfree(root+0x50)`, `kfree(root+0x54)`;
8. `kfree(root)`, `gc+0x6c = 0`.

`free_config_desc` (`0x602bad58`) frees every config/interface/alt/ep array,
alt extras, ep extras, ep SS companions, config+0x0c blob, and config+0x14
6-byte array.

`save_desc_tbl` ownership rules:

* The caller's 12-byte header and 88-byte table/arrays are **only read**
  (`__copy_from_user`); the caller may free them after return.
* The new root is installed at `gc+0x6c` at `0x602bc5c8`; the **old root is not
  freed first**. Normal app flow avoids a leak because stop frees the old root
  before start; a module calling `save_desc_tbl` twice without an intervening
  `free_desc_tbl` leaks the first tree.
* On any failure, `save_desc_tbl` calls `free_desc_tbl(gc)` at `0x602bcdac`,
  which frees the partial new tree and sets `gc+0x6c = 0`. The old root, if any,
  was already overwritten and is leaked.
* No refcount exists. The UDC never frees or retains the tree. Only gadgetcore
  frees it, on ioctl stop or save failure.

**Module-owned tree rules:**

* If the module writes `gc+0x6c = module_tree`, the tree must stay valid for the
  entire interval until the module removes it. Serializers dereference its
  pointers lazily on every GET_DESCRIPTOR/SET_CONFIGURATION; there is no copy.
* The module must remove its pointer **before** any `free_desc_tbl` (app stop,
  app start, rmmod), otherwise gadgetcore `kfree()`s module memory → double
  free / arbitrary free.
* If the module installed via `save_desc_tbl`, gadgetcore owns a deep copy; the
  module source may be freed immediately. The module still must not call
  `free_desc_tbl` on a tree it does not own without restoring/using the
  GC-owned pointer.
* The existing shim demonstrates the safe static-bundle pattern: on restore it
  sets `gc+0x6c = 0`, restores the saved MSC root, and explicitly does not call
  `free_desc_tbl` for its static bundle
  (`tools/native_camera/uvc_composite_shim.c`, restore path).

### 5.10 Alignment

`kmalloc`/`kmem_cache_alloc` return at least 4-byte-aligned memory. No explicit
alignment is requested. All u16/u32 fields are at naturally aligned offsets:
root+0x30/0x32/0x34 (u16), record+0x00 (u16), config+0x04/0x0c/0x10/0x14 (u32,
24-byte stride), alternate+0x04/0x0c/0x10 (u32, 20-byte stride), endpoint
+0x02 (u16), +0x08/0x0c/0x10 (u32, 20-byte stride). A module must keep the root
and all sub-arrays 4-byte aligned; do not pack them.

---

## 6. Serializer traversal rules

### 6.1 Per-speed record selection

Verified by instruction bytes and by executing the real functions with
distinct per-record values:

| Function | speed 5 (SUPER) | speed 3 (HIGH) | other (FULL) |
| --- | --- | --- | --- |
| `make_device_desc` `0x602bb988` | `root+0x20` | `root+0x00` | `root+0x10` |
| `make_device_qualifier_desc` `0x602bbfec` | `root+0x20` | `root+0x10` (other speed) | `root+0x00` (other speed) |
| `make_config_desc` kind 2 (CONFIG) | `root+0x20` | `root+0x00` | `root+0x10` |
| `make_config_desc` kind 7 (OTHER_SPEED) | `root+0x00` | `root+0x10` | `root+0x00` |
| `get_config_desc_from_config_num` | `root+0x20` | `root+0x00` | `root+0x10` |
| `setup_req` BOS bcdUSB gate | allowed | reads `[root+0]` | reads `[root+0x10]` |

**Correction:** E0405ab/E0407a state `3 -> root+0x10` for the device descriptor.
That is inverted. The instruction sequence at `0x602bb9d8..0x602bb9e4` is:

```text
602bb9d8: 030053e3  cmp  r3, #3
602bb9dc: 0000a0e3  mov  r0, #0
602bb9e0: 0670a001  moveq r7, r6          ; speed==3 -> root+0x00
602bb9e4: 10708612  addne r7, r6, #0x10   ; else      -> root+0x10
```

Unicorn execution with `root+0x00` bcdUSB 0x0200 and `root+0x10` bcdUSB 0x0110
returned 0x0200 for speed 3 and 0x0110 for speed 2. Consequently E0407a's
physical module, which logged `speed=3` and patched `0x69567d30 =
root+0x10`, patched the FULL-speed record, not the HIGH-speed record served in
that state. The restore receipt remains valid; the patch did not affect the
descriptor the host read at HIGH speed. Implementer: select the record at
runtime exactly as the builder does, and patch `root+0x00` when speed==3.

### 6.2 `make_device_desc` (`0x602bb988`)

Output is built on the stack and copied to the caller buffer:

| Output | Source |
| --- | --- |
| `[0]=0x12` | constant bLength |
| `[1]=0x01` | constant DEVICE |
| `[2..3]` | selected record `+0x00` (bcdUSB) |
| `[4]` | record `+0x02` (class) |
| `[5]` | record `+0x03` (subclass) |
| `[6]` | record `+0x04` (protocol) |
| `[7]` | for speed 5: `log2(ep0->desc[4..5])`; otherwise low byte of `ep0->maxpacket` (`[gc+4]+0x14`) |
| `[8..9]` | `root+0x30` (idVendor) |
| `[10..11]` | `root+0x32` (idProduct) |
| `[12..13]` | `root+0x34` (bcdDevice) |
| `[14]` | `root+0x37` (iManufacturer) |
| `[15]` | `root+0x38` (iProduct) |
| `[16]` | `root+0x39` (iSerialNumber) |
| `[17]` | selected record `+0x05` (bNumConfigurations) — **not** `root+0x3a` |

The copy length is `min(wLength, 18)`; the full 18 bytes are built on the stack
regardless. `wLength = (setup[6]<<8)|setup[7]`.

This also supersedes E0405ab's **inferred** `out[16]/out[17]` mapping:
`out[16] = root+0x39` and `out[17] = selected record +0x05` are both directly
visible in the instructions at `0x602bba60..0x602bba6c`, not `root+0x39/+0x3a`.

### 6.3 `make_device_qualifier_desc` (`0x602bbfec`)

Builds 10 bytes: `{0x0a,0x06,bcdUSB(2),class,subclass,protocol,maxpacket0,
bNumConfigurations,0}` from the other-speed record selected above.
`setup_req` rejects the request when `gc+0x80 == 2` (`0x602b9594`).
Copy length `min(wLength, 10)`.

### 6.4 `make_config_desc` (`0x602bbc54`)

Signature in the original call: `make_config_desc(gc, setup, out, kind)` where
`kind = setup[3]` (2 = CONFIG, 7 = OTHER_SPEED).

Selection: see §6.1. It then finds the 24-byte config whose byte +0x00 equals
`setup[2]` (wValue low). If none, returns -1.

Generated bytes:

```text
config descriptor (9):
  [0] = 9
  [1] = kind (2 or 7)
  [2..3] = wTotalLength (computed u16)
  [4] = cfg[0x02]  bNumInterfaces
  [5] = cfg[0x01]  bConfigurationValue
  [6] = cfg[0x08]  iConfiguration
  [7] = cfg[0x09]  bmAttributes
  [8] = cfg[0x0a]  bMaxPower

optional 3-byte prefix (only if cfg[0x0c] != 0):
  [9..11] = {0x03, 0x09, *(u8*)cfg[0x0c]}

for each interface (cfg[0x02] entries, array order):
  9-byte interface descriptor:
    {9,4, grp[0], alt[0], alt[1], alt[8], alt[9], alt[10], alt[11]}
  if alt[0x0c] != 0: copy alt[0x0c] bytes from alt[0x10]
  for each endpoint (alt[1] entries, array order):
    7-byte endpoint descriptor:
      {7,5, ep[0], ep[1], ep[2..3], ep[4]}
    if speed==5 and ep[0x10] != 0:
      6-byte SuperSpeed companion: {6,0x30, payload[0..3]}
    if ep[0x08] != 0: copy ep[0x08] bytes from ep[0x0c]
```

`wTotalLength` is recomputed from scratch (`r5 = 9`, `+3`, `+9`, `+extra`,
`+7`, `+6`, `+extra`), stored with `uxth`, and written to `out[2..3]`. It is
**never read from the tree**. The builder writes the whole descriptor to `out`
before truncation; the return value is `min(wLength, total)` but bytes beyond
`wLength` (up to `total`) are still written. **The caller's output buffer must
be at least the computed `wTotalLength`**, not `wLength`. This is why the E0154
offline serializer passed a 1024-byte buffer for a 173-byte descriptor and why
`ep0` replies must be chunked from a full-size staging buffer.

The builder performs **no validation** of counts/pointers:
`interface_count`, `alternate_count`, `endpoint_count`, extra sizes and array
pointers are trusted. A malformed tree reads arbitrary memory. The module must
produce a self-consistent tree.

### 6.5 `make_string_desc` (`0x602bc0cc`)

* `index = setup[2]` (wValue low).
* `index == 0`: language descriptor. `out[1]=3`; for each of `root[0x3a]`
  languages, copy the u16 language ID from `root[0x3c][i*8]`; `out[0] = 2 +
  2*count`; return `min(wLength, built)`.
* `index == 0xEE`: if `gc+0x84 == 0` return -ENODEV (`0xFFFFFFEA`); else copy
  the 18-byte MS OS string from `0x604e5130`; return `min(wLength, 18)`.
  `gc+0x84` is the same `is_dual` byte the app supplies at start.
* other index: find the language entry matching `wIndex = setup[4] |
  setup[5]<<8`; then find the string entry whose byte +0x00 equals `index`; copy
  its bytes (length at +0x01, capped 0xFD) to `out+2`; `out[1]=3`, `out[0] =
  len+2`; return `min(wLength, built)`. Missing language/index -> -ENODEV.

Strings are read from the deep-copied tree buffers, not from user space, after
`save_desc_tbl` returns.

### 6.6 Lookup helpers and sentinels

| Function | Match rule | Count source |
| --- | --- | --- |
| `get_config_desc_from_config_num` `0x602bb628` | `cfg[1] == wValue` | selected record `+0x05`; array at `+0x08`, stride 0x18 |
| `get_interface_desc` `0x602bb694` | `grp[0] == ifnum` | `cfg[2]`; array at `cfg+0x04`, stride 8 |
| `get_if_table_desc` `0x602bb6f8` | `alt[0] == altnum` | `grp[1]`; array at `grp+0x04`, stride 0x14 |
| `make_alt_num_list` `0x602bb774` | builds `gc+0x70` list of `{ifnum, alt=0}` | `cfg[2]`; allocates `cfg[2]*2` |
| `set_alt_num`/`get_alt_num` | linear search in `gc+0x70` | `cfg[2]` |

Consequences:

* Interface numbers need **not** be contiguous for the serializer; each
  group's `+0x00` is emitted as `bInterfaceNumber`. But `make_alt_num_list`
  initializes one entry per array position and Windows composite expects
  `0..N-1`, so append interface 1 at the end.
* Alternate settings need not be contiguous; `alt[0]` is emitted and looked up.
  Alternate 0 must exist as the default.
* `gc+0x74` is the active `bConfigurationValue` (not the config index).
  `stop_config` uses it to find the config; `SET_CONFIGURATION(1)` writes 1.

### 6.7 Appended zero-endpoint interface 1 (actionable recipe)

To append interface 1 to a clone of the live High-speed config:

1. Deep-copy the selected speed record's config array, or build a new tree.
2. `cfg[2] += 1` (bNumInterfaces becomes old+1).
3. Reallocate the interface group array to `cfg[2] * 8` and append:
   `{ bInterfaceNumber=1, alternate_count=1, pad=0, alternate_ptr=&alt1 }`.
4. `alt1 = { bAlternateSetting=0, bNumEndpoints=0, pad=0, endpoints=NULL,
   class=0xFF, subclass=0xDB, protocol=0x01, iInterface=0,
   extra_size=0, extra_ptr=NULL }`.
5. Keep `cfg[0x00] = 0` (GET_DESCRIPTOR index), `cfg[0x01] = 1`
   (bConfigurationValue), `cfg[0x08]` = existing iConfiguration (or 0),
   `cfg[0x09]`/`cfg[0x0a]` unchanged.
6. `wTotalLength` is recomputed by the builder; the appended interface adds 9
   bytes.
7. If the config has an IAD array (`cfg[0x10]`/`cfg[0x14]`), it is **not
   serialized**; if Windows needs an IAD for the vendor function, append it by
   post-processing the serialized output (as the E0154 module did), not by
   filling `cfg[0x10]`.
8. Endpoint admission: the appended interface has zero endpoints, so the
   SET_CONFIGURATION duplicate-number scan is unaffected. If endpoints are
   added later, the low nibble of `bEndpointAddress` must be unique across all
   interfaces and alternates; the scan rejects duplicates (offline probe
   `probe_uvc_ptp_config_endpoints.py`: 0x84 accepted, 0x81/0x82/0x83
   conflicting with existing endpoints rejected).

Minimum sanity checks the module should enforce before install (the native
builder does not):

* `cfg[0x02]` equals the actual interface-array length and every pointer is
  non-NULL for a non-zero count;
* each `grp[1]` equals its alternate-array length; alt 0 exists;
* each `alt[1]` equals its endpoint-array length;
* all extra sizes match their buffers and fit in 16 bits for `wTotalLength`;
* total computed size fits the EP0 reply buffer and `wTotalLength` is < 65536;
* endpoint numbers unique;
* string indices referenced by the device/config/interface descriptors exist in
  the language table (the serializer returns -ENODEV otherwise).

### 6.8 SET_CONFIGURATION endpoint admission

The loop at `0x602b96e8..0x602b9878` scans every interface/alternate/endpoint in
the active config:

* it builds a 15-slot endpoint table (`r6 = 0..14`);
* for each endpoint it compares `(bEndpointAddress & 0x0f)` with the slot;
* a second occurrence of the same endpoint number takes the error path
  `0x602b9898` (stop the old config and fail);
* for each unique endpoint it records address / max packet / interval and calls
  `gadget->ops->ioctl(gadget, 2, &param)` (`dwc3_gadget_ioctl` cmd 2 returns 0,
  no-op on this core).

This is the only endpoint-uniqueness enforcement in the native path; the
serializer itself does not check uniqueness.

### 6.9 Optional fields the serializer ignores

* `cfg+0x10` / `cfg+0x14` (6-byte records) are copied and freed but never
  emitted; dynamic test set `cfg[0x10]=1`, `cfg[0x14]=IAD payload` and the
  output contained no `0x0B` descriptor and the same `wTotalLength`.
* `cfg+0x0c` (1-byte blob) is the only optional pre-interface emission; the
  live/ZV-E10 trees have 0. Its 3-byte `{0x03,0x09,byte}` semantics are
  **unproven**; leave it 0 for the appended interface.
* `root+0x48` is neither copied nor freed; leave 0.
* `root+0x36` is not read by `make_device_desc`; leave the template value.

---

## 7. Actionable constraints for the C module

### Do

1. Read the live `gc` from `0x6051b17c`; verify non-NULL.
2. Read `gadget = *(void **)gc`, `dwc = gadget - 0x150`,
   `root = *(void **)(gc + 0x6c)`.
3. Use the **correct** device record selection (§6.1): HIGH `root+0x00`,
   SUPER `root+0x20`, FULL `root+0x10`. Re-evaluate `[gadget+0x20]` at runtime.
4. Deep-copy the full graph (root, all three config trees, strings, extras) if
   you need independence; or build a fresh tree matching the layouts in §5.
5. Keep every allocation 4-byte aligned and all counts consistent.
6. Quiesce with the native stop sequence: clear `gc+0x68` bit 2 →
   `pullup(0)` → `setup_disconnect` → `usb_gcw_stop` → detach/free old tree.
7. If you use `save_desc_tbl`, pass a 12-byte header with `is_dual`/`max_speed`
   and a user-accessible tree; remember it deep-copies and installs.
8. If you own the root, keep it alive for the whole installed interval and
   remove it before any app stop/start or `rmmod`.
9. Arm EP0 after installing the tree and before `pullup(1)` if you performed a
   manual pull-down (shim-proven sequence).
10. Restore the three E0407a patches before app reconfiguration and before
    unload.

### Don't

1. Don't write DCTL directly; call `gadget->ops->pullup` (`ops+0x14`).
2. Don't assume `save_desc_tbl` frees the old root; it does not.
3. Don't call `free_desc_tbl` while `gc+0x6c` points at module memory.
4. Don't leave a dangling `gc+0x6c` after app stop/start (the tree is freed).
5. Don't swap the root while `gc+0x68` bit 2 is set, before `pullup(0)` /
   `setup_disconnect` completes, or from IRQ/atomic context.
6. Don't rely on `pullup(0)` as a strict barrier against an in-flight
   `setup_req`; `dwc3_ep0_delegate_req` drops `dwc+0x70` around the setup
   callback. Use `synchronize_irq` or a guaranteed idle window if needed.
7. Don't expect `free_desc_tbl` to free `root+0x20` (SS) — it does not.
8. Don't expect the builder to emit IADs from `cfg+0x10/+0x14`; post-process
   the serialized bytes.
9. Don't pass a buffer smaller than the computed `wTotalLength` to
   `make_config_desc`; it writes the full tree even when `wLength` is smaller.
10. Don't patch `root+0x10` for HIGH-speed bcdUSB; that is the FULL record.
11. Don't unregister the gadget driver expecting D+ to drop; only `pullup(0)`
    does that.
12. Don't take `gc+0x30`, `gc+0x4c`, gcw or DWC3 `rt_spin_lock`s in hardirq;
    they are PREEMPT_RT sleeping locks.

---

## 8. Verified facts vs inference vs unproven

### Verified by instruction decode

* All function addresses, call orders, field offsets and allocation-size
  expressions in §3–§6.
* `gc+0x6c` root readers take no lock (§4.3).
* `free_desc_tbl` frees only `root+0x00` and `root+0x10` config trees.
* `save_desc_tbl` overwrites `gc+0x6c` without freeing the old root; on failure
  calls `free_desc_tbl`.
* `usb_gcw_start` only changes state from 1 to 2/3; it does not touch hardware.
* `dwc3_gadget_run_stop` writes `regs+0x604` bit 31 and polls `regs+0x60c`
  bit 22.
* DWC3 IRQ is `request_threaded_irq(irq, NULL, dwc3_thread_interrupt, 0x2080,
  ...)`; `dwc3_ep0_delegate_req` drops `dwc+0x70` around `driver->setup`.
* IOCTL numbers and start/stop sequences.

### Verified by executing original bytes under Unicorn

* Device/qualifier/config/other-speed record selection for speeds 3, 2, 5.
* Device descriptor bytes and `min(wLength,18)` truncation.
* Config descriptor bytes for a two-interface tree, `wTotalLength=34`
  (`0x22`), bNumInterfaces=2, appended zero-endpoint interface 1, full output
  written beyond `wLength`.
* Language/string serialization and the `0xEE` gate.
* Config+0xc 3-byte prefix; absence of native IAD emission from
  cfg+0x10/+0x14.
* gcw state transitions and `usb_gcw_setup_setconfig` expected-state table.
* 25-allocation order/sizes for a two-interface tree; six-allocation SS leak in
  `free_desc_tbl`.

### Inference (marked, not proven)

* DCTL bit 31 = `RUN_STOP`, bit 30 = `CSFT`: supported by the set/clear
  semantics, the probe's `0x40000000` soft-reset write, and the DSTS bit-22
  halt poll; the register names come from the DWC3 programming model, not from
  a provided databook.
* DCTL bits 17/19 set on start (mask `0xa0000`) are not decoded; do not write
  them manually.
* gcw state names (single/dual/configured) are inferred from values and call
  sites.
* `cfg+0x0c` 3-byte prefix semantics are unknown; it is zero in the live
  ZV-E10/MSC templates.
* `dwc+0xcc` is an event-buffer pointer cell; the wait is on its object's +0x10
  bit 0.

### Unproven / not claimed

* No live camera tree was re-read in this increment; all tree examples are the
  retained ZV-E10 templates/fixtures or the E0404 live read.
* The exact native allocator call `kmem_cache_alloc` cache identity is not
  resolved; only the requested trace size (`0x58`) is proven.
* No real concurrency test of the root-swap race; the `synchronize_irq`
  recommendation is a design conclusion from the lock drop.
* E0407a's physical bcdUSB patch efficacy is contradicted by the static decode;
  no new hardware test was run (and none is claimed).
* Whether Windows requires an IAD for the vendor interface is host-side
  behaviour, not proven here.

---

## 9. Remaining boundary

1. **IRQ-thread synchronization.** The native stop path does not
   `synchronize_irq`; a module that swaps/frees the tree should obtain the UDC
   IRQ (or otherwise guarantee host-idle) before the swap. The IRQ number is
   not stored in `dwc`; it is obtained by `platform_get_irq(pdev, 0)` in
   `dwc3_gadget_start`. Deriving it safely from a module is an open
   implementation detail.
2. **SuperSpeed tree free omission.** `free_desc_tbl` leaks `root+0x20`'s
   config tree. If the module builds an SS record, it must free that tree
   itself, or avoid allocating it. Whether the native SS record is ever used on
   the a6400 boot is unproven.
3. **`cfg+0x0c` prefix.** The 3-byte `{0x03,0x09,x}` emission is real code but
   has no known wire meaning and is zero in the retained trees. Keep it zero.
4. **`cfg+0x10/+0x14` 6-byte records.** They look like IAD payloads but are not
   serialized by `make_config_desc`. A native IAD path may exist elsewhere
   (another builder/version); not found in this image.
5. **E0407a record correction.** The physical E0407a receipt patched
   `root+0x10` at speed 3. Static decode says the served record is `root+0x00`.
   The host-visible effect of the E0407a patch is therefore not established;
   a corrected bcdUSB patch should target `root+0x00` in HIGH speed and be
   re-tested only under a separate authorized hardware gate.
6. **`gc+0x14` 28-byte object.** Its role as an event/callback registration is
   inferred from `bus_disconnect`/`is_ep_alive`; its full layout is not needed
   for the tree work and is not decoded.
7. **DCTL bits 17/19.** Start-only speed/test bits; semantics undecoded.
8. **Live tree identity.** The last verified live read (E0404) showed
   `root=0x69567d20`, speed 3, one MSC config. The ZV-E10 tree layout is used
   for field offsets; an a6400 PC-Remote/UVC live tree could differ in optional
   fields (extras/strings), though the core layouts are shared by the same
   gadgetcore code.

---

## Appendix A — per-function disassembly excerpts

All bytes are little-endian instruction words as printed by Capstone; the
`; ...` comments are decoded meanings or BL targets.

### A.1 gcw state (`0x602bd414`, `0x602bd450`, `0x602bd7f8`, `0x602bd834`)

```text
602bd414: 0dc0a0e1  mov  ip, sp
602bd418: 30d82de9  push {r4, r5, fp, ip, lr, pc}
602bd41c: 04b04ce2  sub  fp, ip, #4
602bd420: 24409fe5  ldr  r4, [pc, #0x24]   ; 0x6051b24c = gcw
602bd424: 0050a0e1  mov  r5, r0
602bd428: 1fbbf9eb  bl   0x6012c0ac       ; __migrate_disable
602bd42c: 580094e5  ldr  r0, [r4, #0x58]
602bd430: 2f2504eb  bl   0x603c68f4       ; rt_spin_lock
602bd434: 580094e5  ldr  r0, [r4, #0x58]
602bd438: 605084e5  str  r5, [r4, #0x60]   ; gcw state
602bd43c: 362504eb  bl   0x603c691c       ; rt_spin_unlock
602bd440: a6baf9eb  bl   0x6012bee0       ; __migrate_enable
602bd444: 0100a0e3  mov  r0, #1
602bd448: 30a89de8  ldm  sp, {r4, r5, fp, sp, pc}
```

```text
602bd808: 10ffffeb  bl   0x602bd450   ; get_gcw_state
602bd80c: 010050e3  cmp  r0, #1
602bd810: 0500001a  bne  0x602bd82c
602bd814: 010054e3  cmp  r4, #1
602bd818: 02008002  addeq r0, r0, #2
602bd81c: 0200a013  movne r0, #2
602bd820: fbfeffeb  bl   0x602bd414   ; change_gcw_state
602bd824: 0000a0e3  mov  r0, #0
```

### A.2 DWC3 pull-up (`0x602b1d3c`)

```text
602b1d48: 154e40e2  sub  r4, r0, #0x150
602b1d5c: 707194e5  ldr  r7, [r4, #0x170]  ; gadget.speed
602b1d60: d1e8f9eb  bl   0x6012c0ac
602b1d68: e15204eb  bl   0x603c68f4      ; lock dwc+0x70
602b1d70: 70818405  streq r8, [r4, #0x170] ; stop -> speed 0
602b1dac: 0400a0e1  mov  r0, r4
602b1db0: cff9ffeb  bl   0x602b04f4      ; stop active transfers
602b1db4: 800016e5  ldr  r0, [r6, #-0x80] ; ep0_out
602b1db8: 1fffffeb  bl   0x602b1a3c      ; disable ep0_out
602b1dc0: 1dffffeb  bl   0x602b1a3c      ; disable ep0_in
602b1dd0: def4ffeb  bl   0x602af150      ; disconnect callback (if speed)
602b1ddc: 86f4ffeb  bl   0x602aeffc      ; run_stop(is_on)
```

### A.3 DWC3 DCTL write (`0x602aeffc`)

```text
602af008: b43290e5  ldr  r3, [r0, #0x2b4]   ; regs
602af014: 043693e5  ldr  r3, [r3, #0x604]   ; DCTL
602af020: 0261c303  biceq r6, r3, #0x80000000
602af044: 026183e3  orr  r6, r3, #0x80000000
602af070: 046687e5  str  r6, [r7, #0x604]   ; DCTL write
602af07c: 0c0693e5  ldr  r0, [r3, #0x60c]   ; DSTS
602af088: 010500e2  and  r0, r0, #0x400000   ; DEVCTRLHLT
```

### A.4 Setup lock drop (`0x602b28e4`)

```text
602b28f4: 705080e2  add  r5, r0, #0x70
602b28f8: 0500a0e1  mov  r0, r5
602b2900: 055004eb  bl   0x603c691c   ; rt_spin_unlock(dwc+0x70)
602b2904: 75e5f9eb  bl   0x6012bee0   ; __migrate_enable
602b2908: b03294e5  ldr  r3, [r4, #0x2b0] ; dwc->gadget_driver
602b2910: 150e84e2  add  r0, r4, #0x150   ; gadget
602b2914: 103093e5  ldr  r3, [r3, #0x10]  ; driver->setup
602b2918: 33ff2fe1  blx  r3
602b2920: e1e5f9eb  bl   0x6012c0ac      ; __migrate_disable
602b2928: f14f04eb  bl   0x603c68f4      ; re-lock
```

### A.5 Start gate (`0x602b8328`)

```text
602b8334: 300080e2  add  r0, r0, #0x30
602b833c: 978bffeb  bl   0x6029b1a0   ; dev_get_drvdata
602b8340: 683090e5  ldr  r3, [r0, #0x68]
602b8344: 5331e0e7  ubfx r3, r3, #2, #1
602b8348: 000053e3  cmp  r3, #0
602b834c: 0200000a  beq  0x602b835c
602b8354: 520400eb  bl   0x602b94a4   ; setup_req
```

### A.6 `save_desc_tbl` root install (`0x602bc550`)

```text
602bc5a4: 38389fe5  ldr  r3, [pc, #0x838]
602bc5a8: d010a0e3  mov  r1, #0xd0
602bc5ac: 140093e5  ldr  r0, [r3, #0x14]
602bc5b0: a5d1fbeb  bl   0x601b0c4c   ; kmem_cache_alloc
602bc5b4: 5810a0e3  mov  r1, #0x58
602bc5b8: d020a0e3  mov  r2, #0xd0
602bc5bc: 0040a0e1  mov  r4, r0
602bc5c0: 17f0faeb  bl   0x60178624   ; kmalloc_add_trace(ptr,0x58,...)
602bc5c4: 000054e3  cmp  r4, #0
602bc5c8: 6c4087e5  str  r4, [r7, #0x6c] ; install new root (old not freed)
602bc614: 6c0097e5  ldr  r0, [r7, #0x6c]
602bc618: 6cfaffeb  bl   0x602bafd0   ; save_config_desc(root+0)
602bc624: 6c0097e5  ldr  r0, [r7, #0x6c]
602bc628: 100080e2  add  r0, r0, #0x10
602bc62c: 67faffeb  bl   0x602bafd0   ; save_config_desc(root+0x10)
602bc638: 6c0097e5  ldr  r0, [r7, #0x6c]
602bc63c: 200080e2  add  r0, r0, #0x20
602bc640: 62faffeb  bl   0x602bafd0   ; save_config_desc(root+0x20)
602bcd84: 2f305be5  ldrb r3, [fp, #-0x2f]
602bcd88: 8430c7e5  strb r3, [r7, #0x84] ; is_dual
602bcd8c: 2e305be5  ldrb r3, [fp, #-0x2e]
602bcd90: 8530c7e5  strb r3, [r7, #0x85] ; max_speed
602bcdac: 8cfdffeb  bl   0x602bc3e4      ; failure: free_desc_tbl
```

### A.7 `save_config_desc` allocation expressions (`0x602bafd0`)

```text
602bafe4: 0500d0e5  ldrb r0, [r0, #5]      ; config count
602baff0: 1860a0e3  mov  r6, #0x18
602baff8: 960000e0  mul  r0, r6, r0
602baffc: 94d6fbeb  bl   0x601b0a54       ; __kmalloc(count*0x18)
602bb094: 0200d7e5  ldrb r0, [r7, #2]      ; interface count
602bb0a4: 8001a0e1  lsl  r0, r0, #3
602bb0ac: 68d6fbeb  bl   0x601b0a54       ; __kmalloc(n*8)
602bb140: 0100d6e5  ldrb r0, [r6, #1]      ; alternate count
602bb14c: 1440a0e3  mov  r4, #0x14
602bb158: 3dd6fbeb  bl   0x601b0a54       ; __kmalloc(n*0x14)
602bb280: 0100d5e5  ldrb r0, [r5, #1]      ; endpoint count
602bb28c: 1440a0e3  mov  r4, #0x14
602bb298: edd5fbeb  bl   0x601b0a54       ; __kmalloc(n*0x14)
602bb328: 10309ae5  ldr  r3, [sl, #0x10]   ; SS companion pointer
602bb340: 41d6fbeb  bl   0x601b0c4c       ; kmem_cache_alloc(4)
602bb4b8: 0c3095e5  ldr  r3, [r5, #0xc]    ; config 1-byte blob
602bb4d0: ddd5fbeb  bl   0x601b0c4c       ; kmem_cache_alloc(1)
602bb568: 1000d5e5  ldrb r0, [r5, #0x10]   ; 6-byte record count
602bb574: 0670a0e3  mov  r7, #6
602bb580: 33d5fbeb  bl   0x601b0a54       ; __kmalloc(n*6)
```

### A.8 `free_desc_tbl` SS omission (`0x602bc3e4`)

```text
602bc3f4: 6c0090e5  ldr  r0, [r0, #0x6c]
602bc3f8: 000050e3  cmp  r0, #0
602bc3fc: 4c00000a  beq  0x602bc534
602bc400: 54faffeb  bl   0x602bad58   ; free_config_desc(root+0x00)
602bc40c: 6c0094e5  ldr  r0, [r4, #0x6c]
602bc410: 100080e2  add  r0, r0, #0x10
602bc414: 4ffaffeb  bl   0x602bad58   ; free_config_desc(root+0x10)
602bc420: 6c5094e5  ldr  r5, [r4, #0x6c]
602bc424: 440095e5  ldr  r0, [r5, #0x44]
602bc430: 8bd4fbeb  bl   0x601b1664   ; kfree(serial)
...
602bc534: 6c0094e5  ldr  r0, [r4, #0x6c]
602bc540: 47d4fbeb  bl   0x601b1664   ; kfree(root)
602bc544: 0030a0e3  mov  r3, #0
602bc548: 6c3084e5  str  r3, [r4, #0x6c] ; root = NULL
```

No third `free_config_desc(root+0x20)` exists.

### A.9 Device record selection (`0x602bb988`)

```text
602bb9a8: 6c6090e5  ldr  r6, [r0, #0x6c]  ; root
602bb9ac: 203093e5  ldr  r3, [r3, #0x20]  ; gadget->speed
602bb9b0: 050053e3  cmp  r3, #5
602bb9b4: 0700001a  bne  0x602bb9d8
602bb9b8: 043090e5  ldr  r3, [r0, #4]
602bb9bc: 207086e2  add  r7, r6, #0x20    ; SUPER -> root+0x20
602bb9d8: 030053e3  cmp  r3, #3
602bb9dc: 0000a0e3  mov  r0, #0
602bb9e0: 0670a001  moveq r7, r6          ; HIGH -> root+0x00
602bb9e4: 10708612  addne r7, r6, #0x10   ; FULL -> root+0x10
```

### A.10 `make_config_desc` total and interface (`0x602bbc54`)

```text
602bbd20: 0950a0e3  mov  r5, #9           ; wTotalLength = 9
602bbd54: 2f305be5  ldrb r3, [fp, #-0x2f]
602bbd58: 055083e0  add  r5, r3, r5       ; + optional 3-byte prefix
602bbd9c: 0400a0e3  mov  r0, #4
602bbda0: 46004be5  strb r0, [fp, #-0x46] ; interface bLength = 9
602bbdb0: 0920a0e3  mov  r2, #9
602bbdb4: 47204be5  strb r2, [fp, #-0x47] ; interface type = 4
602bbdd4: 0130d6e5  ldrb r3, [r6, #1]     ; alt[1] bNumEndpoints
602bbdfc: 5f73feeb  bl   0x60258b80      ; copy 9-byte interface descriptor
602bbe00: 0c2096e5  ldr  r2, [r6, #0xc]    ; alt extra size
602bbe24: bc30d6e1  ldrh r3, [r6, #0xc]
602bbe28: 035085e0  add  r5, r5, r3
602bbe44: 0720a0e3  mov  r2, #7
602bbe48: 0500a0e3  mov  r0, #5
602bbe50: 4f004be5  strb r0, [fp, #-0x4f] ; endpoint bLength = 7
602bbe54: 50204be5  strb r2, [fp, #-0x50] ; endpoint type = 5
602bbe84: 3d73feeb  bl   0x60258b80      ; copy 7-byte endpoint descriptor
602bbe88: 50305be5  ldrb r3, [fp, #-0x50]
602bbe8c: 035085e0  add  r5, r5, r3
602bbf84: 3e204be5  strb r2, [fp, #-0x3e] ; config bLength = 9 (r2=9 at 0x602bbf7c)
602bbf88: bc534be1  strh r5, [fp, #-0x3c] ; wTotalLength
602bbf90: 3da04be5  strb sl, [fp, #-0x3d] ; config bDescriptorType = kind
602bbfd0: 000483e1  orr  r0, r3, r0, lsl #8
602bbfd4: 050050e1  cmp  r0, r5
602bbfd8: 0500a021  movhs r0, r5         ; return min(wLength,total)
```

### A.11 `make_string_desc` 0xEE gate (`0x602bc0cc`)

```text
602bc148: ee005ce3  cmp  ip, #0xee
602bc15c: 8430d0e5  ldrb r3, [r0, #0x84]  ; is_dual / mode
602bc160: 000053e3  cmp  r3, #0
602bc164: 3c00000a  beq  0x602bc25c      ; -ENODEV
602bc168: 0400a0e1  mov  r0, r4
602bc16c: f8109fe5  ldr  r1, [pc, #0xf8]  ; 0x604e5130 MSFT100
602bc170: 1220a0e3  mov  r2, #0x12
602bc174: 1260a0e3  mov  r6, #0x12
602bc178: 8072feeb  bl   0x60258b80      ; memcpy
```

### A.12 `setup_disconnect` / `stop_config` / `stop_interface`

```text
602b9464: 0dc0a0e1  mov  ip, sp
602b9474: 0ccbf9eb  bl   0x6012c0ac   ; __migrate_disable
602b9478: 4c5084e2  add  r5, r4, #0x4c
602b947c: 0500a0e1  mov  r0, r5
602b9480: 1b3504eb  bl   0x603c68f4   ; rt_spin_lock(gc+0x4c)
602b9484: 0400a0e1  mov  r0, r4
602b9488: 0fffffeb  bl   0x602b90cc   ; stop_config
602b9490: b6feffeb  bl   0x602b8f70   ; clear_halt_ep0
602b9498: 1f3504eb  bl   0x603c691c   ; rt_spin_unlock
```

```text
602b90d8: 7410d0e5  ldrb r1, [r0, #0x74]  ; active config
602b90e0: 000051e3  cmp  r1, #0
602b90e4: 0100a001  moveq r0, r1
602b90e8: 78a89d08  ldmeq sp, {r3, r4, r5, r6, fp, sp, pc}
602b90ec: 4d0900eb  bl   0x602bb628      ; get_config_desc...
602b9100: f00900eb  bl   0x602bb8c8      ; free_alt_num_list
602b9114: 9cffffeb  bl   0x602b8f8c      ; stop_interface
602b9134: 000094e5  ldr  r0, [r4]
602b9138: 0020a0e3  mov  r2, #0
602b913c: 7420c4e5  strb r2, [r4, #0x74]
602b9140: 8220c4e5  strb r2, [r4, #0x82]
602b9158: 33ff2fe1  blx  r3              ; gadget->ops->ioctl(gadget,1,0)
```

```text
602b8fe0: 787094e5  ldr  r7, [r4, #0x78]  ; driver list
602b8ff4: 0420d0e5  ldrb r2, [r0, #4]     ; driver config
602b9000: 0520d0e5  ldrb r2, [r0, #5]     ; driver interface
602b900c: 1420d7e5  ldrb r2, [r7, #0x14] ; node active
602b9020: 143090e5  ldr  r3, [r0, #0x14] ; driver->stop
602b9024: 33ff2fe1  blx  r3
602b9038: 4a0600eb  bl   0x602ba968     ; ep_ctrl_delete_ep
602b90c4: e40500eb  bl   0x602ba85c     ; ep_ctrl_disable_ep
```

### A.13 `gcw_register_driver` callback installation (`0x602bd66c`)

```text
602bd6bc: 586084e5  str  r6, [r4, #0x58]  ; lock object
602bd6f8: 206dfeeb  bl   0x60258b80     ; copy 0x58 driver
602bd708: 1c6dfeeb  bl   0x60258b80     ; copy 0x58 to +0x268
602bd714: 743284e5  str  r3, [r4, #0x274] ; gcw_unbind
602bd71c: 783284e5  str  r3, [r4, #0x278] ; gcw_setup
602bd724: 7c3284e5  str  r3, [r4, #0x27c] ; gcw_disconnect
602bd72c: 803284e5  str  r3, [r4, #0x280] ; gcw_suspend
602bd734: 843284e5  str  r3, [r4, #0x284] ; gcw_resume
602bd740: 33ffffeb  bl   0x602bd414    ; state = 1
602bd748: 16ddffeb  bl   0x602b4ba8    ; usb_gadget_probe_driver
```

### A.14 UDC remove order (`0x602b4a04`)

```text
602b4a20: 003094e5  ldr  r3, [r4]        ; driver
602b4a24: 040094e5  ldr  r0, [r4, #4]    ; gadget
602b4a28: 143093e5  ldr  r3, [r3, #0x14] ; driver->disconnect
602b4a2c: 33ff2fe1  blx  r3
602b4a30: 003094e5  ldr  r3, [r4]
602b4a34: 040094e5  ldr  r0, [r4, #4]
602b4a38: 0c3093e5  ldr  r3, [r3, #0xc]  ; driver->unbind
602b4a3c: 33ff2fe1  blx  r3
602b4a40: 040094e5  ldr  r0, [r4, #4]    ; gadget
602b4a44: 0010a0e3  mov  r1, #0
602b4a48: 103090e5  ldr  r3, [r0, #0x10] ; ops
602b4a4c: 243093e5  ldr  r3, [r3, #0x24] ; udc_stop
602b4a50: 33ff2fe1  blx  r3
```

---

## Appendix B — raw data reads that anchor the layouts

```text
root+0x30 template (ZV-E10): 4c 05 22 03 00 01 80 01 02 00 01 00 90 ca 01 00
  idVendor=0x054c idProduct=0x0322 bcdDevice=0x0100 +0x36=0x80
  iMan=1 iProd=2 iSerial=0 lang_count=1 pad=0 lang_ptr=0x1ca90

config 24-byte template:
00 01 04 00 20 00 00 00 00 c0 01 00 00 00 00 00 02 00 00 00 8c 25 01 00
  index=0 value=1 num_ifaces=4 pad iface_ptr=0x20
  iConfiguration=0 bmAttributes=0xc0 bMaxPower=1 pad
  cfg+0x0c=0  cfg+0x10=2 (six-byte records)  cfg+0x14=0x1258c

interface group: 00 01 00 00 90 cd 01 00   (number 0, 1 alt, alt ptr)
alternate: 00 00 00 00 00 00 00 00 0e 01 00 00 28 00 00 00 98 25 01 00
  alt=0 ep_count=0 class=0x0e subclass=1 protocol=0 iInterface=0
  extra_size=0x28 extra_ptr=0x12598

endpoint: 81 02 40 00 02 02 00 00 00 00 00 00 00 00 00 00 00 00 00 00
  addr=0x81 attr=2 maxpkt=0x40 interval=2 extra=0 ss_companion=0

language entry: 09 04 03 00 d4 e3 01 00  (langid 0x0409, 3 strings)
string entry:   index, length, pad(2), data pointer (8 bytes)

gcw expected-state table at 0x603dfe30/0x603dfe34 = 3 / 4
gcw global 0x6051b24c; gc slot 0x6051b17c; MSFT table 0x604e5130
```

---

## Appendix C — reproducibility caveats

* The original `save_desc_tbl`/`free_desc_tbl` were executed with stubbed
  `__copy_from_user`, `kmem_cache_alloc`, `__kmalloc`, `kfree`, `memcpy`,
  `__memzero` and `printk`. The **call order and requested sizes** are original;
  the actual cache identity, physical addresses and concurrency are not.
* The serializer harness executes the original `make_*` bytes with a stubbed
  `memcpy`; the code paths that use `log2` (SuperSpeed device descriptor) were
  exercised with a synthetic 512-byte EP0 descriptor.
* No camera state, live tree or `/proc/kallsyms` was re-read for this document.
  The live values quoted (`gc=0x68aa4ec0`, `root=0x69567d20`, mode 0, max_speed
  1) are from the retained E0404/E0407a receipts, not new observations.
* The E0407a bcdUSB correction is a static/Unicorn result; no hardware test was
  performed or is claimed.

---

# E0407b1 parts 2+3 — implementation, build and execution verification

Date: 2026-11-12. **Strictly offline.** No camera access, no USB or camera tool,
no `insmod`/`rmmod`, no `/setting` or any device write, no module staging, no
git push. Everything below is local file work, a WSL cross-compile and local
Python/Unicorn execution of the compiled ARM bytes.

## 10. Implementation

### 10.1 Files

| Path | Role |
| --- | --- |
| `tools/native_camera/a6400_dbg_tree.c` | Freestanding ARMv7 kernel C building block (56,192 B source) |
| `tools/research/build_debug_patch_module.py` | Carrier ELF surgery + static audit; new `--tree-source`, `--emit-tree-test-payload`, tree audit, source/payload receipts |
| `tools/research/build_debug_patch_module.ps1` | Additive parameters (`-Source/-Object/-OutDir/-Name/-Tree`); default E0403 behaviour unchanged |
| `src/a6400/debug/tree_deepcopy_model.py` | Unicorn model: compiled tree code + original `make_*` serializer bytes |
| `tests/test_tree_deepcopy_model.py` | 21 tests (3 static + 18 Unicorn execution) |
| `artifacts/native/e0407b1-tree/**` | Objects, linked test image, carrier copy, `.ko`, manifests, build log |
| `artifacts/tests/e0407b1-tree/**` | Extracted Unicorn payload + full-suite log |

The C file compiles in two modes from the same source. Production binds the
service layer to exported kernel symbols; `-DA6400_TREE_TEST` binds the same
slots to `tree_*` stubs so Unicorn can execute the compiled logic:

| Service | Production binding | Test binding |
| --- | --- | --- |
| alloc / free | `__kmalloc(size, 0xd0)` / `kfree` | `tree_alloc` / `tree_kfree` (host arena) |
| copy / zero | `memcpy` / `memset` | `tree_memcpy` / `tree_memset` |
| reads / writes | `probe_kernel_read` / `probe_kernel_write` | `tree_probe_read` / `tree_probe_write` |
| log | `printk` | `tree_log` |
| D+ pull-up | `gadget->ops->pullup` read from `gadget+0x10`/`ops+0x14` | same indirect call to a stub |
| `setup_disconnect` / `usb_gcw_stop` | fixed text VAs `0x602b9464` / `0x602bd834` | `tree_stop_disconnect` / `tree_gcw_stop` stubs |

The two teardown helpers are not `EXPORT_SYMBOL`'ed (verified in
`artifacts/analysis/e0401-kallsyms-now.txt`: no `__ksymtab_setup_disconnect` /
`__ksymtab_usb_gcw_stop`), so production reaches them by the decoded image VA.
This assumes the same fixed image base (`0x60108000`) already relied on by the
E0407a module's `0x604e5130` and `0x6051b17c` targets; it is called out as a
residual boundary in §13. All tree/patch/swap/free logic is ordinary C without
libc, floats, VLAs or unbounded loops.

### 10.2 State and shape

`struct a6400_tree_state` (52 bytes, module `.bss`) holds: `gc`, `orig_root`,
`module_root`, `bcdusb_addr`, `saved_os_crc`, `saved_bcdusb`, latched `speed`,
`saved_mode`, the three `patched_*` flags, `root_installed`, `quiesced` and the
18 saved OS-string bytes. Entry points are `init_module`/`cleanup_module`
(production audit values `init=0x5348`, `cleanup=0x572c`).

The pure functions are `noinline,noipa` so the compiled symbols stay callable
and the executed bytes are the same in both modes: `tree_deepcopy`,
`tree_append_vendor_interface`, `tree_validate`, `tree_free`,
`tree_apply_patches`, `tree_restore_patches`, `tree_quiesce`,
`tree_install_root`, `tree_restore_root`, `tree_unload`.

Every node is a separate allocation with the native logical size: root `0x58`,
config array `n*0x18`, interface array `n*8`, alternate array `n*0x14`,
endpoint array `n*0x14`, alternate/endpoint extras `size`, SuperSpeed companion
4, config 1-byte blob 4 (native cache object), config 6-byte records `n*6`,
serial `len`, language array `n*8`, string-entry array `n*8`, string bytes
`len`, root blobs 4/8/16. Counts are bounded by
`A6400_MAX_{CONFIGS,INTERFACES,ALTS,ENDPOINTS,LANGS,STRINGS}` (8/16/8/16/8/32),
extras by 4096 bytes, strings by 255 bytes and a computed descriptor by 60000
bytes. Every source/destination pointer is checked against kernel RAM
`0x60000000..0x6fffffff` before any probe/memcpy. A pointer field is never
copied before its allocation succeeds: local buffers have pointer slots zeroed
before the raw write, so a partially copied node can always be freed safely.

`tree_deepcopy` copies the whole 0x58 root, all three per-speed config trees
(`root+0x00/+0x10/+0x20`), serial bytes, language/string tables and the
4/8/16-byte root blobs. `tree_append_vendor_interface` appends
`{number = old count, alt_count 1, alt0 = 0 endpoints, class FF, subclass DB,
protocol 01}` to **every config of every per-speed record** (so the active speed
always serves it); it reallocates the interface array to `(n+1)*8`, writes the
new pointer, then the new count, then frees the replaced array. It fails closed
if an interface number already equals the array position (`-EINVAL`).

`tree_free` frees all three records, unlike native `free_desc_tbl`, which omits
`root+0x20` (verified native leak). A module-owned root is never passed to
`free_desc_tbl`.

### 10.3 Patch protocol

Three targets, pre-checked and read back:

1. OS string `0x604e5130` (18 bytes): reads the current bytes, requires the
   stock array (`CRC32 6e795789`), saves the exact bytes, writes
   `MSFT20`/vendor `0x02` (`CRC32 fdadfcba`) and verifies by CRC.
2. `gc+0x84` mode gate: requires 0, saves 0, writes 1, verifies.
3. `bcdUSB`: `speed` is latched from `[gadget+0x20]` **before** quiesce; the
   offset is `speed==5 ? 0x20 : speed==3 ? 0x00 : 0x10` (the corrected mapping).
   The halfword is read and must be `0x0200`, then `0x0210` is written to the
   **module clone's** record and the clone is read back. The kernel-owned tree
   is not modified at all.

The `speed` latch is required by the ABI, not a convenience: `pullup(0)` writes
`gadget.speed = 0` (§3.3), so reading `[gadget+0x20]` after quiesce would select
`root+0x10` (FULL) regardless of the host speed. The test
`test_patch_record_selection_follows_runtime_speed` proves the offset for speeds
2/3/5 by executing the compiled code and the original `make_device_desc`.

Each patch marks its `patched_*` flag **before** the write, so a failed or
partially completed probe write is still reverted by the failure path
(`tree_restore_patches`, up to 3 attempts, each target read back). On the error
path the patches are restored before the clone is freed; on `rmmod` the order is
restore patches → restore `gc+0x6c` → free the clone (§4.5 order).

### 10.4 Swap / unload protocol

`init_module` order:

1. Refuse if `g_state.module_root` is already set (`-EBUSY`).
2. Preflight: `gc = *0x6051b17c`, `gadget = *[gc]`, `root = *[gc+0x6c]` non-NULL
   and in range, mode 0, selected record `bcdUSB == 0x0200`, OS string stock.
3. Quiesce if the started gate (`gc+0x68` bit 2) is set or `gc+0x74 != 0`:
   clear bit 2, `pullup(gadget, 0)`, `setup_disconnect(gc)`, `usb_gcw_stop()`,
   then require `gc+0x74 == 0`. If the pull-down cannot be proven, abort with
   `-EIO` before allocating anything; the UDC is left disconnected.
4. `tree_deepcopy(orig_root)`, append, `tree_validate`.
5. Verify `gc+0x6c` is still `orig_root` (host idle).
6. Apply the three patches; install `gc+0x6c = module_root` and read it back;
   verify the clone's selected record reads `0x0210` through `gc+0x6c`, exactly
   as the serializer would.
7. Return 0. **The UDC is left disconnected** (gate clear, D+ low, gcw state 1).
   The carrier/app owns the re-start; a native app start rebuilds the tree and
   therefore loses the overlay/bcdUSB patch, which is why start/stop must move
   to the carrier in E0407c.

`cleanup_module`/every error path (`tree_unload`):

* If `gc+0x6c` no longer equals the module root (app replaced it), the module
  does not touch the pointer; it restores the patches and frees its clone.
* If it is still installed, re-read the UDC state; if started or configured,
  run the same quiesce and require `gc+0x74 == 0` and gate clear. If that cannot
  be proven, **restore the patches and deliberately leak the module tree**,
  logging `A6400TREE LEAK ...`; it never `kfree`s memory a live UDC may still
  read.
* Otherwise restore the patches, restore `orig_root`, verify the read-back and
  free the clone. Failure of the root read/write verification also leaks rather
  than freeing a possibly installed tree.
* `init_module` failure after any allocation calls the same unload, so all
  allocation/probe faults unwind to zero leaks and stock patches.

**Why an app stop cannot kfree the module tree in this design.** The native stop
ioctl first executes `_test_and_clear_bit(2, gc+0x68)` (`0x602b8a48`) and
returns 0 immediately when the bit was already clear (`0x602b8a4c..0x602b8a50`,
`beq 0x602b8aa4`); `free_desc_tbl` is only reached after it cleared the bit
itself. `init_module` clears bit 2 during quiesce and installs the clone and
returns with bit 2 **clear**. A plain app stop therefore takes the early-return
path and cannot `kfree` module memory. The only native path that can free our
clone is an app start that sets bit 2 and then a stop: start sets bit 2
(`0x602b899c`) *before* `save_desc_tbl` replaces `gc+0x6c` (`0x602b89b8`), so
after a completed start `gc+0x6c` is the app's own tree and the stop frees that
tree, not ours. Unload treats both detached forms (`gc+0x6c` = app tree, or
`gc+0x6c` = 0 after the app's stop) as "not ours", does not touch the pointer,
and frees the detached clone; it only restores `orig_root` when `gc+0x6c` still
equals the module root. The residual window is a concurrent app start that sets
bit 2 between our quiesce and our own root write; the carrier must serialize
start/stop against module load/unload (see §13).

The `gc+0x68` bit-2 clear is a read-modify-write through
`probe_kernel_read`/`probe_kernel_write`, not the native atomic
`_test_and_clear_bit` (not exported). It runs only in process context with the
module's own entry point; the residual non-atomic window is stated in §13.

## 11. Build and static audit

### 11.1 Toolchain

| Tool | Version |
| --- | --- |
| WSL `arm-linux-gnueabi-gcc` | 15.2.0 (Ubuntu 15.2.0-16ubuntu1) |
| WSL `arm-linux-gnueabi-ld` | GNU ld 2.46 |
| Python | 3.14.6 (`venv`) |
| Unicorn | 2.1.4 |
| pyelftools | 0.33 |

### 11.2 Exact commands

```powershell
# Full tree build: test object + linked Unicorn image + payload, production
# object, carrier surgery, final .ko, static audit.  -Tree selects
# tools/native_camera/a6400_dbg_tree.c, artifacts/native/e0407b1-tree and the
# a6400_dbg_tree module name; explicit -Source/-Object/-OutDir/-Name also work.
powershell -NoProfile -ExecutionPolicy Bypass -File `
  .\tools\research\build_debug_patch_module.ps1 -Tree

# Audit only (E0407b1 tree mode), also run as the final check.
.\venv\Scripts\python.exe -m tools.research.build_debug_patch_module `
  --tree-source tools/native_camera/a6400_dbg_tree.c --audit-only

# Default E0403 audit regression (unchanged path).
.\venv\Scripts\python.exe -m tools.research.build_debug_patch_module --audit-only

# Unicorn execution tests, then the full suite.
.\venv\Scripts\python.exe -m unittest tests.test_tree_deepcopy_model -q
.\venv\Scripts\python.exe -m unittest discover -s tests -q
```

`-ExecutionPolicy Bypass` is required only because this host's Windows
PowerShell refuses unsigned `.ps1` files; the default (no arguments) invocation
still builds the E0403 helper exactly as before. The compile flags are the
existing carrier flags plus `-DA6400_TREE_TEST` for the test object
(`-std=gnu11 -marm -march=armv7-a -mfloat-abi=softfp -O2 -Wall -Wextra -Werror
-ffreestanding -fno-builtin -fno-pic -fno-pie -fno-stack-protector -fno-common
-fno-tree-loop-distribute-patterns`).

The test image is linked at fixed addresses (`0x10010000` text, `0x10020000`
rodata, `0x10022000` bss) with the ten service symbols at `0x10030000+0x10*i`;
`artifacts/native/e0407b1-tree/test/tree_test.ld` is regenerated by the wrapper.
`--emit-tree-test-payload` extracts every `SHF_ALLOC` section and the symbol
table into `artifacts/tests/e0407b1-tree/tree_test_payload.json`. **The payload
carries `source_sha256`; the test suite fails if the C source changed without a
rebuild.**

### 11.3 Identities (SHA-256)

| Artifact | Bytes | SHA-256 |
| --- | --- | --- |
| `tools/native_camera/a6400_dbg_tree.c` | 56,192 | `4565b1aa6adb5ddf7d4158e0d3a2127a721f90139a6f35dfa9a5b267c8b43c58` |
| `artifacts/native/e0407b1-tree/a6400_dbg_tree.o` (production) | 16,772 | `b185a5c2fa80e4f6c96b90857bf6062303a0f69b1e1bff1c9c486ed77592542e` |
| `artifacts/native/e0407b1-tree/a6400_dbg_tree_test.o` (test) | 16,892 | `54f3b119fad3540b807b5e260064de274125e1d5c11c62d07f6b628fd517f474` |
| `artifacts/native/e0407b1-tree/test/tree_test.elf` | 133,912 | `21dd583f3f474148bd423874c23f3e3d210471e2d0c1021f5e14c246cda17df1` |
| `artifacts/tests/e0407b1-tree/tree_test_payload.json` | — | `3c66ea01f95a73e60c11a3c34e0d96a796bce16ed58c71ed28cfdf5cecf28c8e` |
| `artifacts/native/e0407b1-tree/final/a6400_dbg_tree.ko` | 36,640 | `e91157e1e41a18b527fd78644916651f2df7fd6857940924201018f35f2d8b39` |
| `artifacts/native/e0407b1-tree/carrier_redirected.ko` | 23,826 | (same carrier surgery as E0403/E0407a) |
| `artifacts/tests/e0407b1-tree/full-suite.log` | — | `b1f35929fe2b4beb191805b2c90e9bbb2f65ea0c418c7e8824228f5232d0e0bb` |
| preserved `vmlinux.bin` (input) | 4,085,888 | `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707` |
| E0407a module (untouched) | 24,904 | `9bd85e1956887a3e0dde85a980098f1e6b96128c25d162d06465ad2b36702e67` |

Module name `a6400_dbg_tree`; vermagic
`3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7 `; license `GPL`; `init=0x5348`,
`cleanup=0x572c`.

### 11.4 Static audit result

`manifest.json` → `audit: ok`, `tree_audit: ok`. Checks:

* little-endian ARM `ET_REL`; `.gnu.linkonce.this_module` exactly 316 bytes and
  named `a6400_dbg_tree`; vermagic identical to the pinned carrier; `license=GPL`
  present in `.modinfo`.
* `init_module`/`cleanup_module` are defined functions; the carrier entry points
  are renamed `carrier_init_module`/`carrier_cleanup_module`.
* Required tree imports present: `__kmalloc`, `kfree`, `memcpy`, `memset`,
  `printk`, `probe_kernel_read`, `probe_kernel_write`.
* Import-set delta against `carrier_redirected.ko`'s own 44 undefined symbols is
  exactly `{printk, probe_kernel_read, probe_kernel_write}` (the other four are
  already carrier imports); no unexpected new import.
* Every undefined symbol still exists in the retained live kallsyms export
  snapshot (`artifacts/analysis/e0401-kallsyms-now.txt`).
* Relocation-level check: 548 relocations with 102 distinct targets, every target
  either defined in the linked module (including local `.LC*`/`.LANCHOR*`
  literal-pool labels), present in the carrier's undefined set, or one of the
  seven allowlisted imports; 0 unknown targets.
* The object defines none of `save_desc_tbl`, `free_desc_tbl`,
  `make_config_desc`, `make_device_desc`, `usb_gadgetcore_ioctl` — it cannot
  duplicate or replace the native serializer/free path.

The default E0403 audit was rerun after the additive changes and is still
`audit: ok` with its original 23,560-byte module. The E0407a module and its
manifest were not rebuilt or overwritten.

## 12. Unicorn execution verification

### 12.1 Machine

`TreeEngine` maps the extracted test image at its linked addresses, a 1 MiB
kernel-RAM arena at `0x60000000` (fixture `gc/gadget/ep0` at
`0x60000000..0x600003ff`, synthetic source tree at `0x60001000`, allocator from
`0x60010000`, output buffers at `0x60080000`, stack at `0x600f0000`), the
preserved `vmlinux.bin` at `0x60108000` (so `0x604e5130` is the real rodata
OS-string bytes) and the `gc` global page at `0x6051b000`. The ten service
addresses are mapped to `bx lr` and intercepted; `memcpy` inside the original
kernel image (`0x60258b80`) is stubbed the same way. `g_state` (`.bss`) is zeroed
on every reset. The fixture is a two-endpoint Mass Storage config per record
(interface 0, alternate 0, endpoints `0x81`/`0x02`, 512-byte max packet,
iSerial 3, one language `0x0409`, three strings) with distinct record values:
HIGH `0x0200`/class 0, FULL `0x0110`/class `EF 02 01`, SUPER `0x0320`/class
`EF 02 01`, plus a 4-byte SuperSpeed companion in the SUPER record only.

### 12.2 Allocation accounting (executed compiled code)

| Step | Allocations | Bytes | Frees | Live |
| --- | --- | --- | --- | --- |
| `tree_deepcopy` | 23 | 444 | 0 | 23 nodes / 444 B |
| append to 3 configs | +6 | +108 | 3 replaced interface arrays (24 B) | 26 nodes / 528 B |
| total for install | **29** | **552** | 3 | 26 |
| `cleanup_module` | — | — | +26 | 0 |
| totals | 29 | 552 | **29** | **0 leaks, 0 double, 0 unknown** |

Size multiset: `root 88`; per record `config 24, iface 8, alt 20, ep-array 40` ×3;
SS companion 4; serial 4; lang 8; string array 24; three string data 4; blobs
4/8/16; three appended interface arrays 16; three appended alternates 20. Every
free matches an allocation made by the same run; nothing is handed to native
`free_desc_tbl`.

### 12.3 Tests (21 new; full suite 1,406)

Static (no Unicorn):

| Test | Proves |
| --- | --- |
| `test_payload_matches_current_source` | extracted payload is from the current C source; required symbols present |
| `test_source_keeps_corrected_speed_mapping_and_three_record_free` | source contains the corrected `5→+0x20, 3→+0x00, else→+0x10` mapping, frees all three records, bounds/CRC/GPL/probe tokens |
| `test_module_receipt_is_audited` | manifest SHA, vermagic, GPL, imports, tree audit status |

Unicorn execution of the compiled object (plus the original `make_*` bytes):

| Test | Proves |
| --- | --- |
| `test_deepcopy_is_byte_identical_and_shares_no_pointer` | full field-value equality with the source tree, zero shared pointer values, every clone pointer in the module arena, 23/23 alloc/free |
| `test_deepcopy_rejects_corrupt_counts_without_leaks` | `bNumConfigurations=9` → `-34`; invalid serial pointer → `-14`; no leak |
| `test_append_adds_vendor_interface_to_every_record` | each record's config has `bNumInterfaces=2`, interface 1 = `{1, 1 alt, FF/DB/01, 0 endpoints, no extra}`, source untouched, validate passes, 29/29 clean |
| `test_append_rejects_used_interface_number` | duplicate number fails closed, full init unwinds with zero live allocations |
| `test_three_patches_apply_and_restore_exact_bytes` | OS bytes/CRC `6e795789 → fdadfcba → 6e795789`, mode `0→1→0`, clone record `0200→0210→0200`, kernel tree stays `0x0200` |
| `test_patch_prechecks_reject_nonstock_state` | mode 1 → `-EBUSY`; unknown OS string → `-EIO` (and unchanged); `bcdUSB=0x0210` → `-EINVAL`; nothing allocated and no patch |
| `test_patch_record_selection_follows_runtime_speed` | speed 2 patches `+0x10`, speed 3 serves `0x0200`; speed 5 patches `+0x20`; state address matches |
| `test_root_swap_state_and_restore` | `gc+0x6c` becomes the state's module root, `bcdusb_addr`, saved bytes/flags, and returns to the saved kernel root |
| `test_restore_root_does_not_overwrite_app_tree` | an app-replaced `gc+0x6c` is left untouched; a later app start+stop (`gc+0x6c = 0`) frees only the detached clone and the module never resurrects the old root |
| `test_quiesce_order_and_gate_clear` | exact order `pullup(gadget,0)` → `stop_disconnect(gc)` → `gcw_stop()`, bit 2 cleared, `gc+0x74` 0 |
| `test_quiesce_failure_aborts_before_install` | failed pull-down leaves the module uninstalled with stock patches and no allocations |
| `test_allocation_failure_at_every_step_unwinds` | 29/29 allocation indices fail the load, each with zero leaks and no persistent patch |
| `test_write_failure_at_every_copy_and_patch_step_unwinds` | 61/61 probe-write indices (copy, append, OS/mode/bcd, root install) unwind cleanly |
| `test_double_init_and_double_cleanup_are_safe` | second init `-EBUSY` with the first tree intact; second cleanup is a no-op |
| `test_unsafe_unload_leaks_instead_of_freeing` | a live/configured UDC that cannot be quiesced leaves the root module-owned and leaks 26 nodes, restores patches, logs `LEAK` |
| `test_served_device_descriptor_uses_corrected_record` | original `make_device_desc` at speed 3 reads the clone's `root+0x00` → `bcdUSB 0x0210`; speed 2 → `0x0110`; speed 5 → `0x0320`; VID/PID/class preserved |
| `test_served_config_grows_by_exactly_nine` | original `make_config_desc`: 32 → 41 bytes, `bNumInterfaces 1→2`, interface 0 + endpoints byte-identical, interface 1 exactly `09 04 01 00 00 ff db 01 00`, no endpoint follows |
| `test_string_descriptors_preserved_and_ms_os_gate` | original `make_string_desc`: indices 1/3 identical before/after deep copy; `0xEE` refused before the mode patch and returns the 18-byte patched MS OS string after it |

Executed bytes for the served config (baseline → module-owned tree):

```text
32 B: 09 02 20 00 01 01 00 80 fa 09 04 00 00 02 08 06 50 00
      07 05 81 02 00 02 00 07 05 02 02 00 02 00
41 B: 09 02 29 00 02 01 00 80 fa 09 04 00 00 02 08 06 50 00
      07 05 81 02 00 02 00 07 05 02 02 00 02 00
      09 04 01 00 00 ff db 01 00
```

Device descriptor served at the latched HIGH speed:
`12 01 10 02 00 00 00 40 4c 05 aa 0c 00 01 01 02 03 01`
(`bcdUSB=0x0210`, `idVendor=0x054c`, `idProduct=0x0caa`, iSerial 3, 1 config).

### 12.4 Results

* `python -m unittest tests.test_tree_deepcopy_model -q`: **21 tests OK**.
* `python -m unittest discover -s tests -q`: **Ran 1406 tests in 22.953s — OK**
  (log: `artifacts/tests/e0407b1-tree/full-suite.log`; suite grew from the
  previous recorded 1,385 by these 21 tests).
* Tree audit-only: `audit: ok`, `tree_audit: ok`, added imports
  `[printk, probe_kernel_read, probe_kernel_write]`.

No hardware, USB, camera, `insmod`, `/setting` or device write was performed in
this increment. The executed ARM bytes are the compiled tree logic (test
service binding) and the preserved original serializer bytes only.

## 13. Residual boundary

1. **No hardware claim.** This increment did not touch the camera and did not
   load the module. Whether Windows binds WinUSB to interface 1, whether the
   a6400 enumerates with this overlay, and whether the live tree matches the
   fixture in optional fields are E0407c questions. The live tree was not
   re-read.
2. **Enumeration not performed / UDC left stopped.** `init_module` leaves
   `gc+0x68` bit 2 clear and D+ low after installing the overlay; it does not
   arm EP0, call `usb_gcw_start` or pull up. The carrier must own start/stop and
   call `tree_restore_patches` before any app-initiated stop/start; an app start
   runs `save_desc_tbl`, replaces `gc+0x6c` and loses the bcdUSB overlay (and
   the module clone becomes detached, which unload handles). The carrier must
   also serialize app start/stop against module load/unload: start sets bit 2
   before it replaces the root, so a start racing the module's install/restore
   window is the only path that could hand module memory to native
   `free_desc_tbl`. With the control plane quiesced, a plain app stop is an
   early-return no-op and cannot free the clone (§10.4).
3. **Root-swap race.** `dwc3_ep0_delegate_req` drops `dwc+0x70` around
   `driver->setup`, so `pullup(0)` is not a strict barrier against an in-flight
   `setup_req`. The module relies on a host-idle window: it checks `gc+0x74 == 0`
   and clears bit 2, but does not call `synchronize_irq` (the IRQ number is not
   stored in `dwc`; only `synchronize_irq` itself is exported, not the IRQ
   value). Freeing after the swap-back therefore assumes no in-flight setup
   still holds the module pointer.
4. **Non-atomic gate clear.** `gc+0x68` bit 2 is cleared by
   `probe_kernel_read`+`probe_kernel_write` because `_test_and_clear_bit` is not
   exported. A concurrent native start/stop could interleave; the module assumes
   it owns the process-context control plane (documented in §10.4).
5. **Two absolute internal calls.** `setup_disconnect` (`0x602b9464`) and
   `usb_gcw_stop` (`0x602bd834`) are reached by decoded image VA, not resolved
   imports, and assume this exact fixed-base image. If the image base or build
   changes, the teardown path must be re-verified.
6. **Only the latched record is patched.** `bcdUSB=0x0210` is written to the
   module clone's record selected for the speed observed at install. If the host
   later re-negotiates a different speed, the other record serves its stock
   value. This mirrors E0407a's single-target scope.
7. **Optional tree fields not exercised.** The fixture has no alternate/endpoint
   extras, no `cfg+0x0c` 1-byte blob, no `cfg+0x10/+0x14` 6-byte records and no
   multi-config record. The copy/validate/free code handles them and bounds
   them, but only the SuperSpeed companion and the standard string table are
   exercised by execution.
8. **Append numbering rule.** The appended interface number is the pre-append
   count; the append fails closed if an existing interface already uses that
   number. Non-contiguous live interface numbers therefore reject the overlay
   rather than renumber.
9. **Unsafe-unload leak.** If the UDC is live and the pull-down/disconnect
   cannot be proven, the module intentionally leaks the clone and returns 0
   after restoring the three targets. That is a deliberate trade-off, not a
   clean free; the log line is `A6400TREE LEAK ...`.
10. **E0407a discrepancy recorded, not retro-fixed.** E0407a patched
    `root+0x10` while logging `speed=3`; §6.1/§A.9 decode and this increment's
    `make_device_desc` execution both show `speed 3 → root+0x00`. The E0407a
    receipt remains as issued; its host-visible bcdUSB effect is not
    established. This implementation uses `root+0x00` for HIGH and applies the
    patch to the module clone, and the served descriptor is proven to carry
    `0x0210` at speed 3.
11. **Documentation status refresh.** The full suite was red before this
    increment because `docs/evidence/` already contained E0407, E0407a, E0407b1
    and E0408 while the status snapshot pinned E0406 and 1,385 tests. Per the
    milestone's minimal-update rule, `tools/research/a6400_status_data.py`
    (latest E0408, 1,406 tests), the README evidence bullet/test counts and
    `docs/images/research-status.svg` were refreshed together; the sync tests
    are green. No other narrative was changed.

