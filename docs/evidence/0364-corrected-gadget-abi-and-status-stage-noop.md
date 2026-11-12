# E0364 — Corrected gadget ABI: giveback calls `complete(ep,req)`; data stage completes in ~150 µs; the status ZLP silently no-ops in `dwc3_ep0_start_trans`

Date: 2026-11-11. **Strictly offline.** No camera run in this record (Run B9 held). Re-analysis
of the Run B8 crash plus the preserved a6400 `vmlinux.bin` (SHA `12eeec82…`,
`file_off = VA − 0x60108000`). Corrects the E0358 interpretation of `uvc_ep0_comp`.

## 1. The completion ABI — confirmed in disassembly and Unicorn

Linux gadget ABI (this build, confirmed inside `dwc3_gadget_giveback`):
`void (*complete)(struct usb_ep *ep, struct usb_request *req);`

`dwc3_gadget_giveback @ 0x602affb8`:
```
602affc8  mov  r5, r0            ; r5 = ep
602affcc  mov  r4, r1            ; r4 = req
602affd0  ldr  r6, [r0, #0x48]   ; r6 = ep->dwc  (dwc3)
...
602b00d8  mov  r0, r5            ; arg0 = ep
602b00dc  ldr  r3, [r4, #0x1c]   ; req->complete (offset 0x1C == 28)
602b00e0  mov  r1, r4            ; arg1 = req
602b00e4  blx  r3                ; complete(ep, req)
```
**Unicorn proof with the real bytes**:
`artifacts/analysis/e0363-runb8/giveback-abi-unicorn.json` — loading
`/ 0x602affb8..` from vmlinux and synthetic ep/req with `req->complete` at `+0x1C`:
`called = [(0x70000000, 0x70001000)]`, `error=null`, **pass=true**. So the Run B8 crash
was exactly the 1-argument thunk: r0 was `ep0=68a1c9c0`, r1 was the request; the thunk
read `status/actual` off ep0 and called `uvc_ep0_comp(ep0)` → `free_request(ep0,ep0)`
→ reboot. Offset 28 was the right slot.

`uvc_ep0_comp @ 0x1a74` under the correct `(ep, req)` convention:
```
1a84  cmp  r1, #0
1a88  bne  0x1ab4              ; req != NULL -> free the request
1a8c..1ab0  build 8-byte message; bl 0x958   ; req == NULL: log only
1ab4  ldr  r3, [r0, #8]        ; ep->ops
1ab8  ldr  r3, [r3, #0xC]      ; ops->free_request (queue is at +0x10)
1abc  blx  r3                  ; free_request(ep, req)
```
So completion **frees the request** and performs no status queueing and no secondary
worker wake. The 150 µs firing time from Run B8 is therefore the real data-stage
completion, not a status action.

## 2. Control status stage — exact path and the silent failure

`dwc3_ep0_interrupt @ 0x602b2c68` (XferComplete and XferNotReady are inline):
- XferComplete gives the request back: `... 602b3338 ldr r0,[fp,#-0x40]; 602b333c mov r1,r5;
  602b3340 mov r2,sb; 602b3344 bl 0x602affb8 (giveback)` then returns — **no status start
  from the completion path**.
- XferNotReady (Status) at `0x602b3448`:
  ```
  602b3448  ldr  r3, [r0, #0x2dc]     ; ep0_next_event
  602b344c  cmp  r3, #3
  602b3450  bne  exit                  ; only if next==3 (status)
  602b3454  str  r3, [r0, #0x2e0]      ; dwc->ep0_event = 3
  602b3458  ldrb r3, [r0, #0x2d8]
  602b345c  and  r3, r3, #0x20         ; DEFERRED_STATUS
  602b3464  cmp  r3, #0
  602b346c  beq  0x602b34a4            ; DEFERRED_STATUS clear -> do_control_status
  ```
  In Run B8 the completion-time bytes were `state=8d next=3 event=2` (GET) and
  `state=89 next=3 event=2` (SET): `next==3` and bit5 (`0x20`) clear, so the
  **immediate do_control_status path is the one taken** (DEFERRED_STATUS is not the
  blocker).
- `__dwc3_ep0_do_control_status @ 0x602b253c`:
  ```
  602b254c  ldrb r3,[r0,#0x2d8]; and #0x40 ...    ; resize TX fifos if bit6
  602b2578  ldr  r0,[r5,#0x48]                     ; dep
  602b2584  tst  r3,#1 ; moveq r2,#0x30 ; movne r2,#0x40   ; TRB ctrl for status
  602b25a0  ldr  r2,[r0,#0x10]
  602b25a4  bl   0x602b2424                        ; dwc3_ep0_start_trans
  602b25a8  cmp  r0,#0
  602b25b8  bl   warn_slowpath_null                ; failure is only a WARNING
  ```
- `dwc3_ep0_start_trans @ 0x602b2424`:
  ```
  602b2440  ldr  r4,[r6,#0x4c]      ; dep->flags
  602b2444  ands r4,r4,#0x10        ; DWC3_EP_BUSY
  602b2448  movne r0,#0             ; BUSY set -> return 0, NO TRB ARMED
  602b244c  bne  exit
  ... build TRB: ctrl = [fp+4] | 0xC00 | 3 ; length; DEPCMD type 6
  602b24ec  bl   0x602b0220         ; dwc3_send_gadget_ep_cmd(type 6, DEPSTRTXFER)
  602b24f4  blt  exit               ; command failure -> negative
  ... on success: dep->flags |= 0x10 (BUSY); dwc->[0x2dc] = 1
  ```
  Therefore the status ZLP can fail **silently** in two ways: (a) `dep->flags` still has
  `0x10` BUSY when the status starts → `start_trans` returns 0 without arming anything;
  (b) the DEPCMD is rejected → negative return, ignored by the caller. Either way the
  host sees no status stage and times out after 5 s; the next SETUP aborts the request
  (which is exactly when the giveback completion ran in B8).

## 3. Consequence for the branch decision

The Run B8 thunk (once its ABI is corrected) already showed the **DATA stage completed in
~150 µs** with `next==3`; the 5 s timeout is the **Control Status Stage**. This is
**Branch A**, with the concrete silent point now identified: `dwc3_ep0_start_trans`'s
`dep->flags & DWC3_EP_BUSY` early return and/or the ignored DEPCMD result. DEFERRED_STATUS
(`0x2d8` bit5) is clear in the captured completion state, so it is not the blocker.

## 4. Corrected instrumentation (Run B9 candidate, not yet run)

`uvc_callback_bridge.c`: completion thunk corrected to
`void thunk(struct usb_ep *ep, struct usb_request *req)`; logs
`EP0 complete ep=… req=… status=… actual=… state=… next=… event=… dep0=… dep1=…`
(dep0/dep1 = `eps[0]/eps[1]->flags` at completion, so the BUSY early-return can be
confirmed) and calls the original `complete` with `(ep,req)` untouched.
Module: `artifacts/native/uvc-transport-e0366-statusprobe/usbg_video_a6400_shared_candidate.ko`,
**81,716 B**, SHA-256 `aec24ce512c7534012eebc345ff06b8a3d5b1baa790d786ed493e4fcb8dee435`,
transport audit `offline_module_audit_passed` (**117/8/0**).

## 5. Remaining offline work before Run B9

- Full Unicorn emulation of the XferComplete → XferNotReady(Status) →
  do_control_status → start_trans chain is the next step; only the giveback ABI has been
  stepped in Unicorn so far (real bytes, pass).
- The precise silent branch (BUSY early-return vs DEPCMD error) will be identified from
  the B9 `dep0/dep1` flags at completion (if the status dep still has `0x10` BUSY, the
  early-return is proven and the fix is to clear/avoid that BUSY state before the status
  start; if not, the DEPCMD error is the target and needs the command result logged via a
  safe observation point).

## 6. Correction to prior records

E0358's table described `uvc_ep0_comp` completion with a one-argument `(request)`
interpretation; the correct ABI in this build is `complete(ep, req)` (proven above). The
E0363 crash is fully explained by that mismatch; offset 28 remains correct.
