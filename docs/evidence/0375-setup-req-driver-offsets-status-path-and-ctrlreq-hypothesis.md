# E0375 — `setup_req` has NO `[driver+0x34]` call site; `[driver+0x18]` is `core_cb_start`; status-complete path and `do_control_status`

Date: 2026-11-12. Strictly offline (`vmlinux`, `usbg_video.ko`, captured B12/B13 logs).
No camera run. The second GC ops shadow was removed (read-only GC logging module
`3d4d04cd…`, 84,024 B, audit 117/8/0); `lr=0x602b9fdc` is never filtered.

## 1. The `[driver+0x34]` claim is not present in `setup_req`

A full scan of `setup_req 0x602b94a4..0x602ba060` finds **five indirect calls**:
`0x602b96c8`, `0x602b9864`, `0x602b98bc` — all `ldr r3,[r0,#0x10]; ldr r3,[r3,#0x18]`
(bind/config/start-style callbacks), and **`0x602b9b64`** — the only driver-table
callback: `ldr r0,[r8]`; `ldr r3,[r0,#0x18]`; `blx r3`.
There is **no `ldr r3,[rX,#0x34]` + `blx` anywhere in `setup_req`**. The driver table
built in `usbg_video_core_ioctl` and registered at module `0x1fe4` is `this+0x38`:
```
+0x18 core_cb_start (module 0x10f0)   +0x1c core_cb_stop (0x744)
+0x20 core_cb_set_halt (0x68c)        +0x24 core_cb_clear_halt (0x6ec)
+0x28 core_cb_nop (0x67c)             +0x2c/0x30 core_cb_nop
+0x34 core_cb_class (0x17b0)
```
So `[driver+0x34]` **is** `core_cb_class`, but `setup_req` never calls it; it calls
`[driver+0x18] = core_cb_start`. `core_cb_start` is therefore the function that must
reach the reference class handler (our bridge CLASS callback) internally; it returns
**1** on its handled path (`0x179c mov r0,#1`). Runtime confirms this: at `[618.111]`
and `[623.122]` no `lr=0x602b9fdc` queue occurs, i.e. `0x9b6c` saw non-zero and skipped
`0x9dac → 0x9fd8`. The delegated queue (`lr=602b9fdc`) appears only for the standard
enumeration requests at `[756.x]` (Device Descriptor 18, Config Descriptor 39,
SET_CONFIGURATION 0, …), exactly the `return 0` path.

## 2. `ep0state == 3` status completion and `do_control_status`

```
0x602b334c  ldr r0,[dwc+0xd0]          ; eps0
0x602b3350  mov r3,r0
0x602b3354  ldr r1,[r3,#0x24]!         ; eps0 request_list head
0x602b3358  cmp r1,r3
0x602b335c  beq 0x602b3368
0x602b3360  sub r1,r1,#0x34
0x602b3364  bl dwc3_gadget_giveback    ; give back any pending eps0 request
0x602b3368  mov r3,#1
0x602b336c  mov r0,r4
0x602b3370  str r3,[dwc+0x2e0]         ; ep0state = SETUP (1)
0x602b3374  bl dwc3_ep0_out_start      ; arm next SETUP TRB
0x602b3378  b 0x602b34b4               ; return
```
`do_control_status 0x602b253c`:
```
0x254c ldrb r3,[dwc+0x2d8] ; and #0x40 ; if set -> resize tx fifos
0x2578 r0=[dep+0x48] (dwc) ; r1=dep->number
0x2580 ldrb r3,[dwc+0x2d8] ; tst #1 -> r2=0x30/0x40 (three_stage_setup)
0x2590 tst r1,#1 ; odd dep -> len 0 ; even dep -> ldrh r3,[dep+0x14] (maxpacket)
0x2598 str r2,[sp] (trb ctrl)
0x25a0 ldr r2,[dwc+0x10]   ; ctrl_req DMA buffer
0x25a4 bl dwc3_ep0_start_trans(dwc, epnum, buf, len, trb_ctrl)
0x25a8..0x25b8  error -> warn_slowpath only (return ignored)
```
At `0x29c` (NRDY STATUS ep0, after `next=3`) this armed the status TRB
(`trb_ctrl=0x40`, `buf=ctrl_req`, OUT status len=64 because dep 0 is even), and the
hardware completed it at `0x2a0=0000c040`. The `0x334c` path then set `ep0state=1` and
called `out_start`, re-arming the next SETUP TRB.

## 3. The 5 s gap and `cnt=0xc` at SET pre

Raw B12 lines (already in E0372) show:
- GET complete: `lpos=0x298 cnt=0xc` → the current batch contains `0x298` (data
  complete) plus **`0x29c` (status NRDY)** and `0x2a0` (status complete), i.e. the CPU
  had not yet processed them when the thunk logged.
- SET pre/queue: `lpos=0x2a4 cnt=0xc` → the batch already holds **three** events:
  `0x2a4=0xc040` (XferComplete ep0), `0x2a8=0x20c2` (NRDY STATUS ep1),
  `0x2ac=0xc040` (XferComplete ep0). `0x2b0` was `0x10c4` at pre and changed to
  `0x10c0` (NRDY DATA ep0) during the queue call.
This means the hardware event write pointer was **ahead of the CPU's `lpos`**, and the
IRQ thread was delayed while hardware accumulated events. The exact `0x2a8/0x2ac`
generation cannot be explained by the software-armed SET data TRB (it did not exist yet
at `SET pre`); the evidence is consistent with the **`dwc->ctrl_req` overwrite /
delayed-IRQ** scenario: by the time the CPU processes event `0x2a4`, the single 8-byte
setup buffer (`[dwc+0]`, DMA `[dwc+0x10]`) can already contain a newer SETUP packet
(next setup DMA), so `dwc3_ep0_inspect_setup` reads SET_CUR even though that event's
hardware transfer belonged to an earlier setup/status sequence. Proving this needs a
read-only snapshot of `[dwc+0..8]` and the event DMA (not available in the current
probe), and must not be approximated by dropping queue calls.

## 4. Consequences

- Do **not** filter `lr=0x602b9fdc`: the UVC class path never generates it; only
  standard enumeration does, and those delegated queues are required for GET_DESCRIPTOR/
  SET_CONFIGURATION.
- The nested GC ops shadow was removed (the camera reboot after B13 is consistent with
  a dangling `ep0->ops` from two shadows on the same `68a1c9c0`).
- Next probe (read-only): snapshot `[dwc+0]` (8-byte ctrl_req) and `[dwc+0x10]` at
  CLASS pre/queue, plus event DMA, to confirm the overwrite/delayed-IRQ sequence behind
  the `cnt=0xc` batch; no queue filtering and no second shadow.
