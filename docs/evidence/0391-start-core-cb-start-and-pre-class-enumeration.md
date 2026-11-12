# E0391 — START/core_cb_start re-check: no EP0 queue in core_cb_start; the 0x1318 queue belongs to the GET probe helper; standard delegated queues at lr=602b9fdc are one per request in the logs

Date: 2026-11-12. Offline only. No camera run.

## 1. B12–B16 logs around START → first CLASS

B12 (e0372) chosen cycle:
```
[129.690698] reference START entry iface=2 count=1
[129.690811] reference START returned iface=2 count=1
[141.742183] CLASS translated wire_iface=2 idx=0002 -> native idx=0001
[141.742337] CLASS entry rt=a1 req=81 val=0100 idx=0002 len=001a
[141.742455] CLASS ep0-pre ep0=68a1c9c0 no-udc-ep
```
B14/B15/B16 show the same START→first-CLASS shape; B16 (clean, trace off) has
START/STOP lines only. There are **no `EP0 queue`/`EP0 complete`/`GCRO queue` lines
between START and the first CLASS** in these cycles. That is expected: the bridge
queue wrapper is installed only at the first CLASS, so standard enumeration queues
before that are not logged by the bridge.

The only pre-CLASS delegated queues in the retained logs are the B13/B14
`GC_EP0 queue ... lr=602b9fdc` lines at 756.x, after a STOP/re-enumeration:
```
756.419335 GC_EP0 queue ep=68a1c9c0 req=68a84da0 len=18 lr=602b9fdc
756.434312 GC_EP0 queue ep=68a1c9c0 req=68a84da0 len=18 lr=602b9fdc
756.439311 GC_EP0 queue ep=68a1c9c0 req=68a84da0 len=39 lr=602b9fdc
756.443299 GC_EP0 queue ep=68a1c9c0 req=68a84da0 len=26 lr=602b9fdc
756.447304 GC_EP0 queue ep=68a1c9c0 req=68a84da0 len=4  lr=602b9fdc
756.451299 GC_EP0 queue ep=68a1c9c0 req=68a84da0 len=20 lr=602b9fdc
756.510321 GC_EP0 queue ep=68a1c9c0 req=68a84da0 len=18 lr=602b9fdc
756.514305 GC_EP0 queue ep=68a1c9c0 req=68a84da0 len=9  lr=602b9fdc
756.518451 GC_EP0 queue ep=68a1c9c0 req=68a84da0 len=39 lr=602b9fdc
756.526478 GC_EP0 queue ep=68a1c9c0 req=68a84da0 len=0  lr=602b9fdc
```
These are the standard setup-delegated status queues (GET_DESCRIPTOR lengths 18/39/26/
20/9 etc.), one GC_EP0 queue per request; the log does **not** show the same request
queued twice. The bridge cannot see the first standard queue before the wrapper is
installed, so “double queue during START” is not demonstrated by B12–B16.

## 2. core_cb_start disassembly

`core_cb_start` is symbol 0x10f0 and ends at 0x11ac (0xbc bytes):
```
10f0 mov ip,sp; push...; 1100 sub r4,fp,#0x2c; mov r7,r1; stm r4,{r2,r3}
110c bl usbg_video_get_this
1114 bl usbg_video_get_this_ex
1118 strb r7,[r0,#0x9c]
1120 bl usbg_video_get_this_ex
1124 add r0,r0,#0x3c
1128 bl _mutex_lock
1138 bl usbg_cmn_make_ep_list
...
1168 ldr r3,[r6,#0xb4]; ... ; 119c strb 0...
11a8 sub sp,fp,#0x1c; 11ac pop...
```
Relocations at 0x110c/0x1114/0x1120/0x1128/0x1138 are exactly
`usbg_video_get_this`, `usbg_video_get_this_ex`, `_mutex_lock`,
`usbg_cmn_make_ep_list`. **There is no `ep0->ops->queue`, no request allocation, and
no ep0 TRB/queue call in core_cb_start.**

The `0x1318 blx [ep->ops+0x10]` queue is inside the **GET probe helper 0x11bc**, not
core_cb_start:
- 0x11bc start; 0x11d4..0x11e4 memcpy 26-byte rodata template to `fp-0x46`;
- interval patch from `this_ex+0xA8`; 0x1238 alloc request;
- 0x12d8..0x1318 fills req (`buf`, `length`, `complete=uvc_ep0_comp`) and queues at
  0x1318;
- 0x131c..0x1380 giveback/error.
So the E0376/E0378 statement “core_cb_start queues EP0 at 0x1318” is a misattribution:
0x1318 is the GET_CUR reply queue, not the start callback.

The standard `setup_req` delegated queue at `lr=0x602b9fdc` is a separate
gadgetcore path; the logs show one queue per standard request, not a duplicate for
the same request. No log evidence supports the double queue as the initial-enumeration
wedge.

## 3. Next test plan (full ETW + silent RAM ring, print once at STOP)

1. **Start ETW before plug-in / before switching the camera to PC Remote**, so the
   initial enumeration `GET_DESCRIPTOR`/`SET_CONFIGURATION`/`SET_INTERFACE` and the
   first `GET_CUR` are in the capture. B17 started too late (rundown only).
2. **In-RAM ring, no hot-path printk:**
   ```c
   struct rec { u32 t; u16 hook; u8 bRequest,wValue_hi,wValue_lo,wIndex_lo;
                u32 lpos,cnt,ep0state,next,fl,trb_ctl,trb_sz,actual,status,req; };
   static struct rec g_ring[256]; static unsigned g_ri;
   #define REC(...) (g_ring[g_ri++ & 255] = (struct rec){...})
   ```
   Record at START, first CLASS, each `ep0->ops->queue`, each completion, and
   standard/delegated queue paths (including `lr`), with `lpos/cnt/ep0state/next/fl`
   and the request pointer. No printk in any of these paths.
3. **Dump the table once in STOP** (`for i ... printk`) plus one-line counters:
   `class_call_count`, `get_cur_count`, `set_cur_count`, `queue_count`,
   `complete_count`, `start_count`. This gives 100% visibility with zero IRQ latency.
4. Acceptance: ETW must show the initial enumeration GET_CUR/SET_CUR; the ring must
   show whether `core_cb_start`/`setup_req` ever issues two queue records for one
   request (same request pointer or same setup), and whether the first GET_CUR status
   stage is armed before the host token.

Until then, the initial-enumeration wedge remains unexplained; `printk` latency is
ruled out by e0388 (zero hot-path printk, still wedge). No camera run/build for E0391.
