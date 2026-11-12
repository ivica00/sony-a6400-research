# E0385 — the reference `req->complete` is a single `free_request` (kfree); the 4.997 s is not inside it

Date: 2026-11-12. **OFFLINE ONLY** (vmlinux `12eeec82…`, module `usbg_video.ko`
`d385a051…`, B12/B14 logs). No camera, no USB, no module build/load.

> Publishable copy of the text requested for `docs/evidence/0385-uvc-ep0-complete-orig-disasm-and-fix.md`.
> It was produced inside `artifacts/analysis/e0384-kernel-disasm/` because that task's scope forbids
> edits under `docs/`. The A–E re-examination that supersedes two statements below is in
> `report.md` §7 / `e0386-claims.json`.

## 1. What the probe calls as `g_req_complete_orig`

Reference module: `firmware/extracted_zve10_v203_linuxnames/firmware.tar_unpacked/0700_part_image/
dev/nflasha15_unpacked/kmod/usbg_video.ko`, SHA-256
`d385a051bf01b0e5ea37412623ae85cfe3cda76ab0d11e61d111994ca9fbf4fb`, 20,668 B.

Both class transfers install the same completion pointer:

| path | install | then |
|---|---|---|
| SET_CUR (`bRequest 0x01`) | `core_cb_class+0x17b0`: `0x18e0 ldr r1,[pc,#0x188]` (literal `.text+0x1a70`, R_ARM_ABS32 `&uvc_ep0_comp`), `0x18f4 str r1,[r6,#0x1c]` | `0x1914 blx r3` (`ep->ops->queue`, `ops+0x10`) |
| GET_CUR (`bRequest 0x81`) | helper `module+0x1390`: `0x1490`/`0x14a8` and `0x15a0`/`0x15b8` (literal `.text+0x17a8`) | `0x14cc` / `0x15dc` `blx r3` |

Runtime identity: the probe log line `CLASS ep0-post pending … complete=5f564a74` equals
module base `0x5f563000` + **`0x1a74`** = `uvc_ep0_comp`. Exactly one `ops->queue` per class
request in every logged cycle.

## 2. `uvc_ep0_comp` (module `+0x1a74`, 0x54 B)

```
0x1a84  cmp  r1, #0                  ; req
0x1a88  bne  0x1ab4
0x1aac  bl   0x958                   ; req == NULL: 12-byte stack record + module log helper
0x1ab4  ldr  r3, [r0, #8]            ; r3 = ep->ops
0x1ab8  ldr  r3, [r3, #0xc]          ; r3 = ops->free_request
0x1abc  blx  r3                      ; free_request(ep, req)
0x1ac0  return
```

`ops+0xc` in the vmlinux ep0 ops table `0x603dfb88` is **`dwc3_gadget_ep_free_request 0x602af31c`**
= `mov r0,r1 ; bl kfree 0x601b1664` (`ops+0x00` enable `602aeb98`, `+0x08` alloc `602af8e4`,
`+0x10` queue `602b2ad0`).

**Non-blocking, no queue, no `set_halt`, no `ep0state`/`ep0_trb` access.** It cannot explain a
4.997 s gap and cannot create an extra `ep0_trb` arm.

## 3. The giveback lock window (confirmed)

`dwc3_gadget_giveback 0x602affb8`:
```
0x602b00c8  add  r6, r6, #0x70        ; dwc->lock
0x602b00d0  bl   rt_spin_unlock
0x602b00d4  bl   __migrate_enable
0x602b00dc  ldr  r3, [r4, #0x1c]      ; req->complete
0x602b00e4  blx  r3                   ; runs UNLOCKED
0x602b00e8  bl   __migrate_disable
0x602b00f0  bl   rt_spin_lock
```
The IRQ is `IRQF_SHARED|IRQF_ONESHOT` (`0x602af3e0 mov r3,#0x2080`), so `dwc3_thread_interrupt`
cannot re-enter while unlocked; `lpos`/`count` accounting is unaffected.

## 4. Consequence: the status arm is prompt

`0x298` (data completion) and `0x29c` (NRDY STATUS) are the 2nd and 3rd events of one batch
(`[0x294,0x298,0x29c]`, B12; `[0x2fc,0x300,0x304]`, B14). With a `kfree`-only callback the loop
advances in microseconds, so `__dwc3_ep0_do_control_status` arms `0x0c43 / 64 / ctrl_req` at
≈141.4246 s (B12) / ≈140.6786 s (B14) — **not** 5 s later. E0383's "the 4.997 s starts inside
the completion callback" is falsified.

## 5. What is abnormal (corrected by E0386)

The NAK that precedes the arm (`0x29c` = `0x20c0`) is **stock behaviour**: `complete_data`
(`0x602b30a8..0x3348`) never arms the status TRB, and the only arms are the NRDY(STATUS) path
(`0x602b34b0`) and the queue delayed-status path (`0x602b27f0`). The host therefore NAKs its
first status token on every control transfer; only its ~5 s retry latency is abnormal. An
earlier draft of this note blamed the probe's completion-thunk logging — that claim is
withdrawn (see E0386 claim A4).

## 6. Unresolved after this note

The third ep0 `XFERCOMPLETE` (`0x2ac`/`0x314`) has no software-visible TRB completion; the only
in-flight arm (bounce `0x0c53`) still reads `HWO=1, size=0x40` before and after it, and no fourth
arm exists. It is a controller-side duplicate of a control-phase completion on the single shared
`ep0_trb` at `0x089ff000`; which fetch duplicated is not derivable statically. `complete_data`
performs no HWO/ownership check (`0x602b30e8..0x3110`), so it consumes the duplicate as the data
completion and gives the SET request back with `actual=0`.

## 7. Files

`e0385_ko_complete.py`, `e0385_ko_disasm.py`, `e0385_clip.py`;
`e0385-uvc-ep0-comp.disasm.txt`, `e0385-giveback-free-request.disasm.txt`,
`e0385-uvc-ep0-comp.json`; corrections in `report.md` §6/§7 and `e0386-claims.json`.


---

**Superseded note (E0386):** the ?NAK plausibly probe-induced? conclusion is retracted:
`complete_data` never arms a status TRB and `do_control_status`?s only callers are the
NRDY-STATUS and queue delayed-status paths, so stock code NAKs the first status token too.
Only the host ~5.01 s retry latency is abnormal. See
[E0386](0386-retraction-probe-induced-nak-and-vendor-status-path.md).
