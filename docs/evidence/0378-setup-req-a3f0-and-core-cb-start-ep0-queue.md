# E0378 — `setup_req` standard-request dispatch, `0xa3f0` class-return path, and `core_cb_start` EP0 queue branch

Date: 2026-11-12. Offline only (`vmlinux`, `usbg_video.ko`). No camera, no probe run.

## 1. `setup_req` bRequest switch (VA 0x602b94d4 table)

`setup_req` branches on `bmRequestType & 0x60`: class/vendor (`0x20/0x40`) goes to
`0x602b9ffc`; standard requests (`0x00/0x80`) use the bRequest jump table at
`0x602b94dc`:
```
bRequest 0x00 GET_STATUS       -> 0x602b9dc0
bRequest 0x01 CLEAR_FEATURE    -> 0x602b9c40
bRequest 0x02 (reserved)       -> 0x602ba448 (-EINVAL)
bRequest 0x03 SET_FEATURE      -> 0x602b9a54
bRequest 0x04/0x05             -> 0x602ba448
bRequest 0x06 GET_DESCRIPTOR   -> 0x602b950c
bRequest 0x07 SET_DESCRIPTOR   -> 0x602ba448
bRequest 0x08 GET_CONFIGURATION-> 0x602b9918
bRequest 0x09 SET_CONFIGURATION-> 0x602b9650
bRequest 0x0a GET_INTERFACE    -> 0x602b9a14
bRequest 0x0b SET_INTERFACE    -> 0x602b9954
```
The driver-table loop at `0x9b34..0x9b8c` (calling `[driver+0x18]` at `0x9b64`) is the
`SET_CONFIGURATION`/`SET_INTERFACE` interface-start path (`0x9650`/`0x9954`): it walks
the endpoint/interface table (`[r2,r5,lsl#2]`), matches interface/alt, and calls the
start callback. Return 0 → `0x9dac → 0x9f64 → 0x9fd8` (delegated zero-length status
queue). That is standard enumeration (`lr=0x602b9fdc` at 756.x), not class GET/SET.

## 2. Class-branch return path `0xa08c` → `0xa3f0`

```
a084 mov r1,r5 ; a088 ldr r2,[gadgetcore+4]
a08c blx r3                     ; class callback (core_cb_class)
a090 subs r6,r0
a094 beq 0xa3f0                 ; handled
a098 cmp r6,#1 ; a09c beq 0xa41c (exit)
...
a3f0 mov r0,r4
a3f4 bl 0x602b8f70              ; clear_halt_ep0
a3f8 b  0xa420                  ; epilogue, return clear_halt_ep0's r0
...
a420 mov r0,r6 ; a424 sub sp,fp... ; return
```
So when the class callback returns 0, `setup_req` calls `clear_halt_ep0` and returns
**without** touching `0x9dac`/`0x9fd8`. The class path has no delegated queue.
`core_cb_class 0x17b0` itself queues the class reply through the reference EP0 path
(our logged `EP0 queue lr=5f5734d0/5f573918`).

## 3. `core_cb_start` queue branch (`0x1318`)

`core_cb_start` is the standard start/interface callback, distinct from
`core_cb_class` (ends at `0x17ac`; `core_cb_class` begins at `0x17b0`). Its queue call
is **not** unconditional:
```
10f0 entry
1138 make_ep_list(this, interface, ep_list...)
1168..1198 validate/update interface state
11e0..1234 build request context
1238 ldr r3,[this_ex,#8]          ; ep0
1240..124c ep0->ops->alloc_request
1280 usbg_video_get_ep0_buffer
12cc..1310 fill request: buf=r7, length=r6, dma, complete, context
1318 ep0->ops->queue(ep0, req)
131c subs r7,r0 ; 1320 moveq r0,#0 -> return 0 (success)
```
`r6` (the request length) is the length derived from the start path's endpoint/EP0
buffer (the class/interface start transfer), not the SETUP `wLength`; the queue happens
only on this start branch after `make_ep_list` succeeds. For `SET_INTERFACE` with
`wLength==0`, this can queue a zero-length EP0 request; `setup_req` then also queues the
delegated zero-length status at `0x9fd8` on return 0. That is a **standard-request
double-queue path** (SET_CONFIGURATION/SET_INTERFACE), but it does not apply to class
GET_CUR/SET_CUR (those return through `0xa3f0`).

## 4. Consequence for the 5 s gap / 0x2a4..0x2b0

B12 timeline: GET data+status complete at `0x298/0x29c/0x2a0`; the next ring batch
already holds `0x2a4/0x2a8/0x2ac` at SET pre (`cnt=0xc`), and `0x2b0` changes to
`NRDY(DATA) ep0` during the class queue. `0x2a4` (`XferComplete ep0`) followed by
`0x2a8` (`NRDY STATUS ep1`) is the signature of a **zero-length standard control
transfer** (SET_INTERFACE/SET_CONFIGURATION: data phase absent → hardware goes straight
to status IN on ep1). That transfer is processed by `setup_req`'s standard branch
(`0x9650/0x9954`), whose `core_cb_start` queue at `0x1318` plus the delegated status at
`0x9fd8` can double-queue EP0 and leave the control pipe out of sync. While the IRQ
thread was delayed, the host timed out (Windows `USB_CTRL_*_TIMEOUT` = 5000 ms), then sent
`SET_CUR`; by the time the CPU processed event `0x2a4`, the single `[dwc+0]` ctrl_req
buffer had been overwritten by the later SET_CUR Setup DMA, so `dwc3_ep0_inspect_setup`
read SET_CUR for the older event. That is the working explanation for the 5 s gap and
the `0x2a4/0x2a8/0x2ac/0x2b0` sequence.

## 5. Decision

The offline check is complete and the probe field list is verified. The read-only
`e0378-ctrlreq-roprobe` (ctrl_req `[dwc+0]`/`[dwc+0x10]`, single `ep0_trb`
`[dwc+4]`/`[dwc+0x14]`, bounce `[dwc+8]`/`[dwc+0x18]`, `ev_buffs [dwc+0xcc]`,
`GEVNTCOUNT0 regs+0xc30c`, `ep0state [dwc+0x2e0]`, flags `[dwc+0x2d8]`, plus a read-only
standard-request/start log) is the next build. Hardware run follows only after audit and
Unicorn; success = identifying the exact transfer at `0x2a4` and proving ctrl_req
overwrite vs. the `0x1318`/`0x9fd8` double-queue.
