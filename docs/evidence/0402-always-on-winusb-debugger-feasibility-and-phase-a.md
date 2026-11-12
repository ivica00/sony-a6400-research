# E0402 — Always-on WinUSB debugger: ABI audit, offline contracts and Phase A delivery

Date: 2026-11-12. Offline ABI/contract work plus safe physical verification of the
Phase A daemon only. No composite descriptor was deployed, no gadget module was
loaded, no kernel text was written, and no UVC/`VS_PROBE`/`ffmpeg` code was
touched. The camera stayed in Mass Storage and remained responsive throughout.

The requested end state — a vendor-specific WinUSB interface reachable inside PC
Remote — is **not implemented on hardware**. This record documents exactly what
now exists, what the verified gadgetcore ABI says, and the concrete gap that
must be closed before a hardware module can be written without guessing.

## 1. Why a host-side workaround cannot exist

E0401 measured PC Remote `054C:0CAA` exposing only PTP
`0x1001-0x100A/0x101B/0x9201/0x9202/0x9205/0x9207/0x9209`; `SonyDiExtCmd` and
`SonyReqReconnect` are absent and the WPD MTP-extension requests are refused
(`0x8007001F`, `0x800700AA`). The debugger therefore needs an independent
transport in the USB configuration itself. That is kernel/gadget work; E0402
Phase A prepares its contracts.

## 2. Verified gadgetcore function-driver ABI (audit)

Sources: preserved a6400 `vmlinux.bin` SHA-256 `12eeec82…43707`, the pinned
ZV-E10 `usbg_video.ko` SHA-256 `d385a051…4fb`, the live `kallsyms` capture
`artifacts/analysis/e0401-kallsyms-now.txt`, and prior E0357–E0399 evidence.
Disassembly receipts: `artifacts/analysis/e0402-abi/`.

### 2.1 Registration

`usb_gadgetcore_register_driver` (VA `0x602b8610`):

- rejects a NULL driver object, and rejects `driver+0x10 == 0` or
  `driver+0x14 == 0` (two required callback slots);
- allocates a `0xd0`-byte record, stores `record[0] = driver`, links the record
  into `gadgetcore+0x78/0x7c`, and returns 0; `-ENODEV` on failure paths.
- `usb_gadgetcore_unregister_driver` (VA `0x602b8560`) unlinks the matching
  record under the gadgetcore lock.

The driver object we control is the 0x34-byte `struct uvc_old_descriptor`
already used by the E0200-series bridge:

```
+0x00 name             +0x04 config      +0x05 interface_number
+0x0c alternate        +0x10 callback[9]
```

with the verified callback order `START, STOP, SET_HALT, CLEAR_HALT, SUSPEND,
RESUME, DISCONNECT, CLASS, VENDOR` (`uvc_callback_bridge.c` enum and ABI
asserts). Dispatch (E0377): standard requests call `driver+0x18`; class
requests call `class_object+0x2c`; vendor interface requests call
`class_object+0x30`. Registration can be repeated per interface; the proven
composite bridge registers two shadows and reaches `active=1` on hardware.

### 2.2 Descriptor tree and ownership

The native descriptor model is the `a6400_candidate_*` tree
(`tools/native_camera/uvc_ptp_descriptors.h`):

- `device`: three 16-byte per-speed entries plus 40 metadata bytes (88 total);
- `config` → `interface[]` → `alternate[]` → `endpoint[]`, plus `extra`
  descriptor blobs, an `otg` pointer, `associations`, and a language/string
  table;
- `a6400_descriptor_install` operates on the live root at `gadgetcore+0x6c`
  with `{table, extra, extra_len, is_dual, max_speed, pad}` and requires
  `max_speed==1`, no `extra`, and `is_dual==0`; it saves via a native
  `save(gc,arg)` and restores via the matching `free(gc)`.
- The E0399 module installs a fixed ZV-E10-derived PC-Remote tree at INIT. It
  does **not** clone the live stock tree, so it is mode-specific.

For E0402 the mode-independent design is to clone the live root tree (MSC and
PTP configurations are created by the stock app) and append one interface +
two endpoints + the MS-OS string, instead of shipping fixed descriptors. This
is feasible with the struct layouts above but is not implemented yet.

### 2.3 Character device and data path

- `usbg_cmn_reg` is not gadget registration: it is
  `register_chrdev_region` + `cdev_init` + `cdev_add`, driven by a device-node
  descriptor at `this+0x3c`. This is the same 12-byte node-table mechanism
  used to create `/dev/usb/video` (248:33), so a `/dev/a6400_dbg` node has a
  verified precedent.
- Bulk data in the reference module is IN-only: `usbg_video_get_ep(index)`
  reads the per-device endpoint list at `this+0xb4`, built by
  `usbg_cmn_make_ep_list(this, index, count, array)`, and frames are pushed
  with `dma330_mem_transfer_async` over buffers from
  `usb_sync_alloc_phys_buffer`.
- Kernel exports available to a module (live kallsyms):
  `usb_gadgetcore_register_driver`, `_unregister_driver`,
  `_stop_other_driver`, `_is_ep_alive`, `_ep_align_maybe`, and
  `usb_gcw_{register,unregister}_driver`, `usb_gcw_{start,stop}`,
  `usb_gcw_setup_{setconfig,setinterface}`,
  `usb_gcw_{register,unregister}_ep_ops`.

### 2.4 Stock Microsoft OS descriptor support (decoded, changes the plan)

The camera kernel already implements Microsoft OS descriptors, and that changes
which unknown is actually on the critical path.

- **OS string 0xEE is hardcoded.** The string-descriptor builder at
  `0x602bc0cc` special-cases index `0xEE`: when `gadgetcore+0x84 != 0` it copies
  18 bytes from fixed VA `0x604E5130` and otherwise returns `-ENODEV`. Those
  bytes are `12 03` + UTF-16 `MSFT100` + vendor code `0x30` + pad `0`.
- **Compat ID 0x30/4 is hardcoded.** The device-recipient vendor branch at
  `0x602ba1d0` handles `bmRequestType=0xC0, bRequest=0x30, wValue=0,
  wIndex=4` by copying `min(wLength, 0x28)` bytes from fixed VA `0x604E5142`.
  That 40-byte descriptor is `dwLength=0x28`, `wIndex=4`, `bCount=1`, one
  function for interface 0 with compatible ID **`MTP`** and zero sub-ID — i.e.
  the stock WPD/MTP binding, and there is no room in 40 bytes for a second
  function section.
- **Other device-recipient vendor requests reach drivers.** For any other
  vendor request (`bmRequestType=0xC0`, request not `0x30`/index 4) the same
  branch falls through to `0x602ba3c4` and calls every registered driver's
  `+0x30` callback with the setup packet. A module can therefore serve a
  Microsoft OS **2.0** descriptor set (`bRequest = vendor code`,
  `wIndex = 0x0007`) with a `WINUSB` compatible-ID feature without any kernel
  text hook.
- **The one write it needs.** To make Windows ask for MS OS 2.0, the 18-byte
  OS string must say `MSFT20` + vendor code `0x02`. `probe_kernel_write` is an
  exported kernel symbol (live kallsyms `0x60180020`); the buffer sits at
  physical `0x4E5130`, inside `/proc/iomem` `Kernel data`
  (`0x004bc000-0x0051f613`), not `Kernel text`. A save/verify/restore of exactly
  18 bytes is the bounded candidate, and it is a data patch that needs its own
  explicit approval gate — not a text patch.
- **A control-only transport avoids the undecoded bulk OUT ABI.** A vendor
  interface needs no endpoints for WinUSB control transfers; the daemon protocol
  can run as vendor interface requests (OUT data phase carries the request,
  IN data phase returns the response) through EP0. The bridge already proves
  class/vendor EP0 reply queueing on hardware; the 4096-byte transfer and MS OS
  2.0 descriptor set still need validation, and bulk IN/OUT remains future work.

**Current plan impact:** the bulk OUT queue/completion contract is no longer
required for a first always-on milestone. The open items are now (1) EP0
4096-byte vendor request/response handling, (2) whether the device descriptor
reports `bcdUSB >= 0x0210` (an MS OS 2.0 requirement), and (3) the approved
18-byte OS-string data patch. Item (2) can be addressed in the *installed
descriptor tree* (device-field edit), not by a kernel patch, if needed.

## 3. What was delivered (Phase A)

### 3.1 Descriptor / MS OS 1.0 contract (`src/a6400/usb_debug_descriptors.py`)

- Vendor interface `bInterfaceClass=0xFF`, `bInterfaceSubClass=0xDB`,
  `bInterfaceProtocol=0x01`, Bulk IN `0x85`, Bulk OUT `0x05`, HS max packet
  512, installed as the next free interface number.
- `merge_vendor_interface` parses a captured/synthetic configuration, updates
  `wTotalLength`/`bNumInterfaces`, refuses endpoint or interface collisions,
  refuses inconsistent `bNumInterfaces` and truncated descriptors.
- Microsoft OS 1.0 String Descriptor: 18 bytes, `MSFT100`, vendor code `0x01`;
  Extended Compat ID: 40 bytes, `wIndex=0x0004`, one function,
  `WINUSB` + zero sub-ID.
- `ep0_reply` models `GET_DESCRIPTOR(String 0xEE)` and the compat-ID vendor
  request; everything else is explicitly unhandled.
- Microsoft OS 2.0 contracts for the control-only design: 18-byte
  `MSFT20` + vendor code `0x02` string descriptor, the 30-byte device-level
  descriptor set with a `WINUSB` compatible-ID feature (`wIndex=0x0007`), the
  vendor-request reply model, and a binding validator that enforces
  `bcdUSB >= 0x0210`, set length/type consistency and a zero sub-ID.
- Tests: 20 passing (`tests/test_usb_debug_descriptors.py`,
  `tests/test_winusb_transport.py`), including golden byte layouts and
  tamper/collision rejections.

### 3.2 Host WinUSB transport (`src/a6400/winusb_transport.py`)

- PyUSB/libsub discovery of the `0xff/0xdb/0x01` interface with one bulk IN and
  one bulk OUT endpoint, using the bundled `Sony-PMCA-RE/libusb-1.0.dll`.
- `WinUsbExchange` moves exactly one 4096-byte protocol frame per
  request/response, rejects short transfers and wrong frame sizes, and reports
  `TransportUnavailable` when the interface is absent.
- `tools/camera_debugger.py` now has `--transport auto|extcmd|winusb`; `auto`
  prefers WinUSB and falls back to the ext-command channel. On the current
  camera `--transport winusb` fails closed with
  `no Sony vendor debugger interface (0xff/0xdb/0x01)`.

### 3.3 Daemon v2.1 with dual transport (hardware verified)

- New `ping` operation (op 13) echoing a nonce; new `/dev/a6400_dbg` service
  loop in `a6400_usb_debugd.c`: non-blocking poll, frame read/dispatch/write,
  retry-open once per second, and a 100 ms ext-command receive slice while the
  bulk transport is active (never blocking the fallback).
- `usb_state` reports `transports=usb_extcmd,a6400_dbg`,
  `transport.dbg_node=present|absent`, `transport.dbg_active=yes|no`.
- Binary: 20,692 bytes, SHA-256
  `bca936af75123db5bb9b0e8d8c08ec3bdb39d1bc892eb33af09a069def40db19`,
  static audit clean (ARM `ET_EXEC`, only `libc.so.6`, 45 undefined symbols all
  resolved by the pinned Sony libc, no W+X segment/textrel).
- Staged upgrade v2→v2.1 preserved the rollback copy and the same daemon pid
  continuity; `/setting/a6400_usb_debugd.elf` upgraded with read-back equality.
  Receipts: `artifacts/hardware/e0401-debugger-upgrade/`.

## 4. Hardware receipts (Phase A only)

`artifacts/hardware/e0401-debugger-v2/` unless noted:

- `ping` over the ext-command transport:
  `PONG protocol=2 nonce=0xa6400001 pid=1056 transport=usb_extcmd`.
- `usb-state`: `transports=usb_extcmd,a6400_dbg`,
  `transport.dbg_node=absent`, klog ring valid
  (`0x035a5000/0x20000`, `crc32=0xa856c2bc`).
- `dump-ring` after the upgrade: 33,705-byte capture, 2 boots, CRC verified.
- `--transport winusb ping`: fail-closed "no Sony vendor debugger interface".
- Camera uptime continuous, no reboot, no battery pull; UVC untouched.

## 5. Boundaries

1. **No always-on debugger yet.** Inside PC Remote the camera still exposes only
   the stock PTP function; the composite vendor interface exists only as an
   offline contract.
2. No module was built, loaded or tested; no descriptor tree was installed; no
   `/dev/a6400_dbg` node exists on the camera.
3. The daemon's `/dev/a6400_dbg` loop is compiled and statically audited but has
   never executed against a real module.
4. No kernel text was patched; `MS OS` interception remains a design.
5. Phase 2 hook wiring is untouched (still Unicorn-only, no hardware install).

## 6. Next gates (Phase B — revised for the control-only MS OS 2.0 design)

1. **B1a (offline):** validate EP0 multi-packet vendor control transfers
   (4096-byte request/response) against the decoded gadgetcore EP0 contract and
   the existing Unicorn EP0 models; decide frame chunking if the limit is lower.
2. **B1b (offline):** read the stock device descriptor (or its native tree
   fields in `usbg_storage.ko`/gadgetcore data) to establish `bcdUSB`; if it is
   below `0x0210`, set it in the installed descriptor tree and record the host
   impact before touching hardware.
3. **B1c (bounded data patch):** implement save/CRC/verify/restore of the
   18-byte OS string at `0x604E5130` using exported `probe_kernel_write`, with
   the original bytes and a restore receipt; require explicit approval for this
   one non-text kernel-data write before it runs on hardware.
4. **B2 (offline):** add the zero-endpoint vendor interface to the mode-specific
   descriptor tree (MSC and PC Remote), register the vendor `old_descriptor`
   with START/STOP/VENDOR callbacks, serve MS OS 2.0 for `wIndex=7`, add a
   `/dev/a6400_dbg` char node; static audit plus Unicorn EP0 proof.
5. **B3 (hardware):** load in Mass Storage only; verify Windows binds WinUSB,
   `ping`/`usb_state` over vendor control transfers, and clean unload with the
   18 bytes restored. No PC Remote until MSC enumeration and rollback pass.
6. **B4 (hardware):** PC Remote always-on (`ping`, `usb_state`, `dmesg`,
   `dump-ring`) and in-band recover to `054C:0CAA`, zero battery pulls.
7. **B5:** only then wire `hook_add`/`hook_list`/`hook_clear` to the
   Unicorn-proven trampoline. Bulk IN/OUT (and the associated OUT queue ABI)
   is a later optimisation; control-only is the interim transport.

## 7. Commands / tests

```
.\venv\Scripts\python.exe tools\camera_debugger.py ping
.\venv\Scripts\python.exe tools\camera_debugger.py usb-state
.\venv\Scripts\python.exe tools\camera_debugger.py --transport winusb ping
.\venv\Scripts\python.exe -m unittest tests.test_usb_debug_descriptors tests.test_winusb_transport tests.test_camera_debugger_protocol
```

Full suite: **1,367 tests OK** (21.3 s).
