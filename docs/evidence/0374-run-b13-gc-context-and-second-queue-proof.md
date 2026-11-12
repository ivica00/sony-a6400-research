# E0374 — Run B13-probe: gadgetcore ep0 IS the class ep0, and `0x9fd8` really queues a second EP0 request (caller LR `602b9fdc`); camera rebooted after teardown

Date: 2026-11-12. Physical Run B13-probe with module `b8905afe…` (GC-context +
second-queue probe, 84,668 B, audit 117/8/0, exact-object Unicorn overall_pass=true),
daemon `99047575…`, `--dmesg-sd --sd-log --sd-mount`. Reset after teardown — see §4.

## 1. GC context / gc_ep0 identity

First UVC CLASS entry (GET_CUR, t=618.111):
```
GCW gc=68aa4ec0 gc_ep=68a1c9c0 ops=603dfb4c class_ep=68a1c9c0 eq=1
EP0 queue lr=5f5734d0 dir=IN req=609d08a0 buf=689805dc dma=00000000 len=26 mapped=0
GC_EP0 queue ep=68a1c9c0 req=609d08a0 len=26 lr=5f576a04
GC_EP0 queue exit ret=0
CLASS exit result=0
EP0 complete ep=68a1c9c0 req=609d08a0 status=0 actual=26 state=8d next=3 event=2
```
- `gc = *( *(dwc+0x150+0x34) + 0x5c ) = 68aa4ec0` (the `g_setup` context).
- `gc_ep0 = [gc+4] = 68a1c9c0` — **the same ep0 object** the CLASS hook passes
  (`eq=1`), with `ops=603dfb4c` (original UDC ops) at install time. So there is no
  separate ep0 object; the reason the earlier single-queue log missed the second queue
  was the **ops/shadow nesting order**, not a different ep.

SET_CUR (t=623.122):
```
CLASS entry rt=21 ...
EP0 queue lr=5f573918 dir=OUT req=609d08a0 ... len=26 mapped=1
GC_EP0 queue ep=68a1c9c0 req=609d08a0 len=26 lr=5f5768d8
CLASS exit result=0
EP0 complete ... actual=0 state=89 next=3 event=2   (bounce TRB HWO=1, E0369)
```
The GC line here is the **nested wrapper** (our EP0 shadow -> GC shadow -> original),
not a second queue; it repeats the same request/length.

## 2. Proof that `setup_req 0x9fd8` really queues a second request

Later control traffic (t=756.x, after the UVC phase; MSC/PTP-style requests) shows
direct GC-queue calls with the **setup_req return address** and a **different request**:
```
GC_EP0 queue ep=68a1c9c0 req=68a84da0 len=18 lr=602b9fdc
GC_EP0 queue ep=68a1c9c0 req=68a84da0 len=39 lr=602b9fdc
GC_EP0 queue ep=68a1c9c0 req=68a84da0 len=26 lr=602b9fdc
GC_EP0 queue ep=68a1c9c0 req=68a84da0 len=4  lr=602b9fdc
GC_EP0 queue ep=68a1c9c0 req=68a84da0 len=20 lr=602b9fdc
GC_EP0 queue ep=68a1c9c0 req=68a84da0 len=9  lr=602b9fdc
GC_EP0 queue ep=68a1c9c0 req=68a84da0 len=0  lr=602b9fdc
```
- `lr=602b9fdc` is the instruction right after **`0x602b9fd8`**, i.e. the
  `setup_req` delegated `ep0->ops->queue(ep0, [gadgetcore+8])` call.
- It targets the **same ep0 (68a1c9c0)**, with a different request (`68a84da0`), while no
  `EP0 queue` line appears (the ops at that moment is the GC shadow, not the EP0
  shadow) — so the second queue is real and was previously invisible.
- The request length at queue time is **not 0** (18/39/26/4/20/9/0), despite
  `0x9f6c` storing 0: the request object is reused/its length is rewritten before the
  queue call, so the delegated request is not a harmless zero-length no-op.

**Conclusion:** Possibility B is real — `setup_req` queues an additional request on the
same ep0 after the function-driver setup returns 0. This is the extra ep0 transfer
whose `XferComplete ep0` (`0x2ac` in B12) is misprocessed against our armed bounce TRB,
producing `actual=0` while the host data/status was accepted by the other request
resource.

## 3. Request-list and caller LR instrumentation

`EP0 list pre e0=68a1c9c0/68a1c9e4->68a1c9e4 e1=68a1c3c0/68a1c3e4->68a1c3e4` was
captured at completion (before giveback): both lists empty at that instant; the first
`EP0 queue lr` values were `5f5734d0` (GET) and `5f573918` (SET), inside the reference
module's queue call path (not `602b9fdc`), confirming the class hook's own queue is
separate from the delegated queue.

## 4. Camera reset after teardown

The daemon receipt was clean (`stop_verified=1`, `teardown_verified=1`, `status=clean`)
and the camera returned to native `054C:0CAA`/MSC without a battery pull. During the
post-run cleanup the debugger lost the device (`Errno 19`); the camera had **rebooted**
(uptime reset to ~28 s, 42 modules, no `usbg_video`, `/tmp_bt` cleared). It recovered by
itself into MSC. So this probe changed teardown stability — likely the nested ops
wrapping (EP0 shadow + GC shadow on the same object) or the delegated-queue
interaction; eWRA must treat this run as **clean receipt but post-run reset risk**.

## 5. Fix direction (offline, not yet applied)

The exact fix is now identifiable without guessing: the GC queue wrapper sees
`__builtin_return_address(0) == 0x602b9fdc` for the delegated queue from `setup_req`.
A bridge-side guard can **drop only that call** (log and return 0 without forwarding to
the original queue), while still forwarding the class hook's own queue. That removes the
second ep0 request while leaving the UDC's `g_setup` return-0 status handling intact.
This must be proven in Unicorn first (call the GC wrapper with LR = `0x602b9fdc`: original
queue stub must NOT be called, while a normal caller must forward), then audited and
run as B14.
