# E0377 — Resolved: class requests never pass `setup_req 0x9b64`; they dispatch from the class/vendor branch `0x602b9ffc` via `[class_obj+0x2c]`

Date: 2026-11-12. Offline only (`usbg_video.ko`, `vmlinux`). No camera, no probe run.

## 1. `setup_req 0x602b94a4` branch map

Entry:
```
94b4 ldrb r3,[ctrl]        ; bmRequestType
94c4 ands r2,r3,#0x60
94c8 bne  0x602b9ffc       ; CLASS(0x20) or VENDOR(0x40) branch
94cc ldrb r2,[ctrl+1]      ; bRequest
94d0 cmp  r2,#0xb ; ldrls pc,[pc,r2,lsl#2]  ; STANDARD request switch
```
So **standard requests** go through `0x94cc` and the driver-table loop at
`0x9b34..0x9b8c`; **class/vendor requests go straight to `0x602b9ffc`** and never
execute `0x9b34`/`0x9b64`.

Standard driver loop (only for standard requests):
```
9b34 ldr r1,[r2,r5,lsl#2]
9b38 ldr r3,[r1,#0x24] ; ldr r3,[r3]
9b40 ldrb r0,[r3] ; ... compare [r3+2] with r6
9b58 ldr r0,[r8]           ; registered driver object
9b5c ldr r3,[r0,#0x18]     ; driver->+0x18 (start/setup entry)
9b64 blx r3
9b6c cmp r0,#0 -> beq 9dac (handled -> delegated request at 9f64/9fd8)
9b74 cmp r0,#1 -> beq 9db8 (exit/error)
```
This loop is the `SET_CONFIGURATION`/`SET_INTERFACE`/start path. Its `0` return leads
to `0x9dac → 0x9f64 → 0x9fd8`, the delegated **status** request — exactly the
`lr=0x602b9fdc` calls seen only at `756.x` (SET_CONFIGURATION, descriptors). It is not
the class GET/SET path.

## 2. Class/vendor branch `0x602b9ffc`

```
9ffc cmp r2,#0x20 ; a000 bne 0xa1d0        ; r2 = bmRequestType & 0x60
a004 and r3,r3,#0x1f                        ; recipient
a008 cmp r3,#1  ; a00c bne a0bc             ; interface recipient
a010 ldrb sl,[ctrl+4]                       ; wIndex low byte
a014 ldrb r8,[gadgetcore+0x74]              ; current interface
a018 bl 0x602bd450 (get current alt/interface)
a054 ldr r7,[gadgetcore+0x78]               ; class-driver list head
a05c ldr r0,[r7]                            ; class object
a060 ldrb r3,[r0,#4]  ; compare interface
a06c ldrb r3,[r0,#5]  ; compare alternate
a078 ldr r3,[r0,#0x2c]                      ; <-- CLASS CALLBACK SLOT
a07c cmp r3,#0 ; a080 beq next
a084 mov r1,r5 ; a088 ldr r2,[gadgetcore+4]
a08c blx r3                                ; class/interface handler
a090 subs r6,r0 ; a094 beq 0xa3f0 (handled)
a098 cmp r6,#1 ; a09c beq 0xa41c (exit)
```
- Endpoint recipient (`recipient==2`, `0xa0bc`) and SETUP-style paths also call
  `[class_obj+0x2c]` (`a144`, `a298`).
- Vendor (`0x40`, `0xa1d0`) calls `[class_obj+0x30]` for interface recipient.
- The **class callback slot is `+0x2c`**, not `+0x34`. `+0x34` (`core_cb_class` at
  module `0x17b0`) is never used by this branch; it is not the class slot in this
  registry.

Runtime reconciliation:
- `GET_CUR`/`SET_CUR` (`bmRequestType=0xa1/0x21`, `(type&0x60)=0x20`, recipient
  interface=1) enter `0x9ffc → 0xa004 → 0xa054.. → 0xa08c`, call the class object's
  `+0x2c` callback; that is where our bridge CLASS hook executes (`GET pre`/`SET pre`
  logs at 618/623).
- No `0x9b64` and therefore no `0x9dac/0x9fd8` occur for class requests. The
  `lr=602b9fdc` queues at `756.x` come from the standard request branch (SET_CONFIGURATION
  start callback returning 0), and are required for enumeration.
- So `core_cb_start 0x10f0` is the **standard start/interface activation callback**
  (`+0x18` in the standard driver loop), not a per-SETUP class handler. Its
  `0x1318 ep0->ops->queue` is the interface/start data path (it allocates an EP0
  buffer and queues it), and its return-0 success is what produces the delegated status
  queue at `0x9fd8`. It is not invoked for GET_CUR/SET_CUR.
- `core_cb_class 0x17b0` is reached through the class object's `+0x2c` callback
  (`0xa08c`), separate from `core_cb_start`; the two functions do not share a tail
  (`core_cb_start` ends at `0x17ac`; `core_cb_class` starts at `0x17b0`).

## 3. Registration structs

- Module `usbg_video_core_ioctl` builds a driver/class object at `this+0x38` and calls
  `usb_gadgetcore_register_driver` at module `0x1fe4` with `r0 = this+0x38`.
- `usb_gadgetcore_register_driver 0x602b8610` allocates a 0xd0-byte record, stores
  `[record]=r0` (`0x602b8684`), and inserts it into the list head
  `gadgetcore+0x78`/`+0x7c` (`0x602b86e4..0x8700`).
- `setup_req`'s standard loop reads `[record]=driver` and calls
  `[driver+0x18]`; the class branch reads the same registered object list and calls
  `[object+0x2c]`.
- Module object fields at `this+0x50..`: `+0x50 core_cb_start`, `+0x54 core_cb_stop`,
  `+0x58 core_cb_set_halt`, `+0x5c core_cb_clear_halt`, `+0x60/+0x64/+0x68 nop`,
  `+0x6c core_cb_class`. The class callback used by gadgetcore (`+0x2c` from the class
  object) resolves to `core_cb_class` for the class object (base `this+0x40`), which is
  consistent with the runtime class path; the standard `+0x18` slot resolves to
  `core_cb_start` for the driver object.
- Exact base difference: both views are different registered objects/aliases of the
  same `this+0x38` allocation; the offsets are resolved by the gadgetcore list element
  (`[record]`) and the callback slot (`+0x18` standard, `+0x2c` class). No `+0x34`
  callback is used anywhere.

## 4. Decision

The contradiction is resolved **without a camera run**:
- class requests → `0x9ffc` → `[class_obj+0x2c]` → `core_cb_class` (our bridge CLASS
  hook), no `0x9fd8`;
- standard config/interface → `0x9b64` → `[driver+0x18]` = `core_cb_start`, return 0 →
  `0x9fd8` delegated status queue (enumeration only).

Therefore the read-only `e0377-ctrlreq-roprobe` can be built next with the corrected
offsets (`ctrl_req` `[dwc+0]`/`[dwc+0x10]`, single `ep0_trb` `[dwc+4]`/`[dwc+0x14]`,
bounce `[dwc+8]`/`[dwc+0x18]`, `ev_buffs` `[dwc+0xcc]`, `GEVNTCOUNT0 regs+0xc30c`,
`ep0state [dwc+0x2e0]`, flags `[dwc+0x2d8]`), with no ops shadows, no `lr` filtering,
and no status kick. It must log class pre/queue/complete, ctrl_req bytes, TRB slot,
bounce DMA, evt lpos/count vs GEVNTCOUNT0, ep0state/flags — to explain the 5 s gap and
the `0x2a4/0x2a8/0x2ac/0x2b0` pre-queue sequence.
