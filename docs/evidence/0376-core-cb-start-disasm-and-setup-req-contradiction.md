# E0376 — `core_cb_start` (driver+0x18) is an EP0 class handler; it can return 0 after queueing, which contradicts the missing `0x9fd8` during GET/SET — resolve list order before any probe

Date: 2026-11-12. Offline only (`usbg_video.ko`, `vmlinux`). No camera.

## 1. `core_cb_start 0x10f0..0x17b0` (the `[driver+0x18]` callback)

Key path (module offsets):
```
10f0 entry: save r1..r3; r7=r1; r4=fp-0x2c; stm r4,{r2,r3}
110c bl usbg_video_get_this            ; r6=this
1114 bl usbg_video_get_this_ex         ; r5=this_ex; [this_ex+0x9c]=r7
1128 _mutex_lock
1138 bl usbg_cmn_make_ep_list(r6,r7,r2,r3)
1144..1164 error path -> return? (returns via 1380/137c)
1168..1198 sets endpoint list/state; unlock
11e0..1234 builds a request/descriptor context in r4
1238 ldr r3,[r5,#8]        ; this_ex->ep0
124c blx r3 ([ep0->ops]+8) ; alloc_request(this_ex, 32)
1280 bl usbg_video_get_ep0_buffer
12cc..1310 fills request: buf=r7, length=r6, dma, complete, context
1318 blx [[r5+8]+8]+0x10   ; ep0->ops->queue(ep0, req)
131c subs r7,r0
1320 moveq r0,r7 ; beq 1380  ; success -> return 0
137c mov r0,#1               ; some paths return 1
```
So `core_cb_start` **does queue an EP0 request directly** (`ep0->ops->queue` at
`0x1318`) and **returns 0 on a successful queue**. If `setup_req`'s callback at
`0x9b64` were this function, `setup_req` would take `0x9dac → 0x9f64 → 0x9fd8` and
queue the delegated request. But Run B13 shows **no `lr=0x602b9fdc`** during GET/SET
(only at 756.x standard enumeration). Therefore one of these must be true:
1. the class request is **not** reaching `core_cb_start` (another driver earlier in the
   `setup_req` list returns 0/1 first), or
2. the driver-struct base/offset mapping used above is wrong (the registered pointer is
   not `this+0x38`, or `[driver+0x18]` is not this function).

That contradiction must be resolved before any probe design.

## 2. Event/TRB struct offsets (corrections to the proposed probe)

Verified from `dwc3_event_buffers_setup 0x602ae5d8`, `dwc3_thread_interrupt 0x602b1378`:
- `dwc+0xcc` = `ev_buffs[]` pointer array; `dwc+0x2c8` = number of buffers.
- `struct dwc3_event_buffer`: `+0 buf`, `+4 length`, `+8 lpos`, `+0xc count`,
  `+0x10 flags`. `evt->lpos` is the **currently executing** event; incremented after
  the entry returns.
- GEVNT registers: `GEVNTADR0 = regs+0xc300`, `GEVNTSIZ0 = 0xc308`,
  **`GEVNTCOUNT0 = 0xc30c`** (the code uses `r8=0x30c` on `dwc->regs`), not `0xc40c`.
- EP0 TRB: `[dwc+4]` = `ep0_trb` CPU virtual (single 16-byte TRB), `[dwc+0x14]` =
  `ep0_trb_addr` DMA, `[dwc+8]` = `ep0_bounce` virtual, `[dwc+0x18]` =
  `ep0_bounce_addr` DMA. There is **no separate `ep0_trb[0]/[1]` array at
  `[dwc+0x20]`** in this kernel; the same TRB slot is reused for setup/data/status.
- `dwc+0x2d8` flags: bit0 three_stage_setup, bit1 ep0_bounced, bit2 ep0_expect_in,
  bit3 start_config_issued, bit4 setup_packet_pending, bit5 delayed_status,
  bit6 resize_fifos, bit7 pullups. `dwc+0x2dc` = ep0_next_event,
  `dwc+0x2e0` = ep0state.

## 3. Event words seen in B12 (decode)

`type=(w>>6)&0xf` (1=XferComplete, 3=XferNotReady); `epnum=(w>>1)&0x1f`;
NRDY subtype = byte1 bits4–7 (1=DATA, 2=STATUS).
- `0000c040` = XferComplete ep0; `0000c042` = XferComplete ep1.
- `000020c0` = XferNotReady(STATUS) ep0; `000020c2` = XferNotReady(STATUS) ep1;
  `000010c0` = XferNotReady(DATA) ep0; `000010c2` = XferNotReady(DATA) ep1.

B12 batch facts:
- GET complete: `lpos=0x298 cnt=0xc` → current event 0x298 (data complete); 0x29c
  (status NRDY) and 0x2a0 (status complete) pending.
- SET pre/queue: `lpos=0x2a4 cnt=0xc` → 0x2a4, 0x2a8, 0x2ac already in the batch
  before the class hook queues anything; 0x2b0 changes 0x10c4→0x10c0 (NRDY DATA ep0)
  during the queue. `cnt` is the cached `evt->count` copied from `GEVNTCOUNT` in the
  hard IRQ; the hardware count register can already be larger.

## 4. Next offline check (no camera, no probe yet)

1. Resolve the contradiction in §1: verify the **actual registered driver pointer**
   (`usb_gadgetcore_register_driver` argument at module `0x1fe4`) and the **list order**
   in `gadgetcore+0x78`; identify which driver `setup_req` reaches first for
   `bmRequestType=0x21/0xA1, bRequest=0x01, wIndex=2` and the exact return value at
   `0x9b6c`.
2. Only then decide whether `core_cb_start` is the class setup path or a different
   driver handles it; if `core_cb_start` is reached, its 0 return explains a delegated
   queue and must be prevented without breaking standard enumeration.
3. The read-only `e0376-ctrlreq-roprobe` (ctrl_req 8 bytes, `[dwc+4]/[dwc+0x14]` TRB,
   `[dwc+0x18]` bounce DMA, `evt->lpos/count`, GEVNTCOUNT0, ep0state/flags) is
   **on hold until §4.1 is resolved**, because its interpretation depends on whether
   the class path is `core_cb_start` or another registered driver.
