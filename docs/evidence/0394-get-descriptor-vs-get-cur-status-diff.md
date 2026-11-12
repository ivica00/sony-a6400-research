# E0394 — GET_DESCRIPTOR (3.5 ms) vs GET_CUR (5.011 s): request-flag and setup_req-tail differential

Date: 2026-11-12. Offline only. No camera run.

## 1. The differential

Both are short (<64 B) 3-stage Control IN transfers on the same ep0. Standard
`GET_DESCRIPTOR` completes data + status in 3.3–3.8 ms (B18 ETL t=23.88/27.89).
`GET_CUR` completes data in 0.95 ms (ring 128.1208→128.1218) but the status OUT waits
5.011 s. ETL: GET_CUR t=35.200491 lasts 5.011510 s SUCCESS; SET_CUR t=40.212017 lasts
5.004151 s CANCELED; then XACT_ERROR retries.

### GET_DESCRIPTOR path (`setup_req` 0x9f64..0x9fe0)
```
9f64 ldr r3,[r4,#8]          ; request
9f68 ldr r2,[pc,#0x4e8]      ; completion literal
9f6c str r6,[r3,#4]          ; request->length = r6
9f70 ldr r3,[r4,#8]
9f74 str r2,[r3,#0x1c]       ; request->complete = generic completion
9f78..9fa8 compare r6 with wLength; compute r1
9fb0 ldrb r3,[r7,#0x1a]      ; request flags byte
9fb4 mov r2,#0x20
9fb8 bfi r3,r1,#1,#1         ; set/clear flag bit1
9fbc strb r3,[r7,#0x1a]
9fc0 ldr r3,[r4,#4]
9fc4 str r4,[r3]
9fc8 ldr r0,[r4,#4]
9fcc ldr r1,[r4,#8]
9fd0 ldr r3,[r0,#8]
9fd4 ldr r3,[r3,#0x10]
9fd8 blx r3                  ; queue through gadgetcore request
9fdc mov r6,r0
9fe0 ldrb r3,[r4,#0x81]      ; gadgetcore flag
9fe4 cmp #0
9fe8 beq return
9fec..9ff4 call 0x602b8ac8(gc, wIndex low)   ; standard setup-tail state handling
```

### GET_CUR path (`core_cb_class` 0x17b0 → helper 0x11bc → 0x1318)
```
12d8 ldrb r3,[r4,#0x1a]      ; request flags
12dc ldr r2,[pc,#0xa8]       ; complete=uvc_ep0_comp
12e0 mov r0,r5
12e4 str r6,[r4,#4]          ; length
12e8 and r3,r3,#0xfc         ; CLEAR bits 0 and 1
12ec mov r6,#0
12f0 str r7,[r4]             ; buf/ep0 buffer
12f4 str r2,[r4,#0x1c]       ; complete
12f8 bfi r3,r6,#2,#1         ; bit2 = 0
12fc str r6,[r4,#8]
1304 strb r3,[r4,#0x1a]
1310 ldr r3,[r5,#8]
1314 ldr r3,[r3,#0x10]
1318 blx r3                  ; ep0->ops->queue
...
setup_req 0x602ba090: subs r6,r0,#0; beq 0x602ba3f0
0x602ba3f0 mov r0,r4; bl clear_halt_ep0 (gc+0x83=0); return
```
So the class path:
- clears **bits 0 and 1** of the request flag byte at `req+0x1a`, and sets bit2=0;
- never sets the standard-path bit1 (which setup_req computes from length vs wLength);
- uses `uvc_ep0_comp` completion;
- after return 0, takes `clear_halt_ep0` and **skips the 0x9fe0..0x9ff4 standard setup tail** (`gc+0x81` check + `0x602b8ac8(gc,wIndex)`).

`clear_halt_ep0` is only `strb 0,[gc+0x83]`; it does not arm a status TRB and does not
queue anything. `dwc3_gadget_ep0_queue 0x602b2ad0` just locks and calls
`__dwc3_gadget_ep0_queue 0x602b26ec`; it does not set the request flags.

The concrete differential to test is therefore the **request flag byte at req+0x1a
(bit1 cleared by class path, set conditionally by the standard path)** plus the skipped
standard setup tail. The GET data path itself is otherwise the same: both queue one
short IN request via `ep0->ops->queue`, and both complete data.

### `req` field offsets
`req+0`/`req+4` in RR2 are the request list links (kernel text pointers
`60157a00/601396ac`), not buf/length. The bytes used by the paths are `req+4` (length),
`req+0x1a` (flags), `req+0x1c` (complete), and dwc3 writes status/actual at
`req+0x2c`/`req+0x30`. The ring's `b0/b1` were recorded from `req+0/+4`, so they are
not payload.

## 2. MSC teardown in B18

The RAM ring dumped at 134.295 on the first STOP (host session stopped). The final MSC
switch was attempted **without `rmmod`/descriptor restore first** because the debugger
is unreachable in PC Remote; the module still held the UVC configuration, so the
switch hung and required a battery pull. B17 succeeded because MSC was reached first
and `rmmod` then restored descriptors. Correct order: stop daemon → `rmmod`/restore →
MSC.

## 3. Proposed C fix (verify in Unicorn before hardware)

In `tools/native_camera/uvc_callback_bridge.c`, use the silent queue wrapper for
class IN requests and set the standard flag bit before calling the original queue:
```c
/* before g_ep0_queue_orig(ep, req, gfp) for CLASS GET_CUR/GET_MIN/... (dir IN) */
if (!g_class_dir_out && req && a6400_uvc_kernel_ptr((uvc_u32)req)) {
    uvc_u8 flags = a6400_uvc_rd8((uvc_u32)req + 0x1a);
    *(volatile uvc_u8 *)((uvc_u32)req + 0x1a) = (uvc_u8)(flags | 0x02);
}
```
This matches the standard path’s `bfi r3,r1,#1,#1` for class IN; no printk. Test in
Unicorn with the reference-class harness: compare `req+0x1a` before/after queue for
GET_CUR vs GET_DESCRIPTOR and assert the status path; then one bounded hardware run
with full ETW before enumeration. If the status wait disappears, the flag/standard-tail
differential is confirmed; if not, the skipped `gc+0x81`/`0x602b8ac8` tail is next.

No camera run or build for E0394.
