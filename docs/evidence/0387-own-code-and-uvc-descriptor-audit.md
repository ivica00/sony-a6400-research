# E0387 — Own-code and UVC descriptor audit: instrumentation in the EP0 hot path, probe-payload/endpoint mismatch, and why STOP hung the MSC switch

Date: 2026-11-12. Offline source/descriptor audit only. No camera, no build, no
`vmlinux`/DWC3 disassembly. This supersedes the “host xHC bug” reading of E0386-runb16.

## 1. Our own bridge code

### 1a. `class_cb` / `invoke` and the wire-interface translation

`class_cb` (module 0x6498) is a thin wrapper:
```c
static uvc_u32 class_cb(...) { return invoke(d, CLASS, a1, a2, a3); }
```
`invoke()` (`uvc_callback_bridge.c:514`) translates the **setup packet into a local
8-byte copy**, not into `dwc->ctrl_req`:
```c
uvc_u8 translated[8];
uvc_u32 forward_a1=a1;
if (which==CLASS && a1 && d->interface_number!=primary) {
    const uvc_u8 *wire=(const uvc_u8 *)a1;
    if (a6400_uvc_ptp_translate_setup(wire,d->interface_number,translated)==0) {
        forward_a1=(uvc_u32)translated;
        printk("CLASS translated wire_iface=%u idx=%04x -> native idx=%04x\n",...);
    }
}
...
target=...; result=target(b->reference,forward_a1,a2,a3);
```
`a6400_uvc_ptp_translate_setup` (`uvc_ptp_adapter.c:12`) also copies to `native[8]` and
only changes `native[4] = wire_interface-1`; it never writes the caller's
`ffdfe000` ctrl buffer and the original `wIndex` is left untouched for `setup_req`.
So the `[163.241685] CLASS translated` line is **not** an in-place mutation of
`dwc->ctrl_req`; translation is safe on that point.

### 1b. `ep0->ops` shadow and queue wrapper

At the first CLASS request the bridge replaces the endpoint ops table
(`uvc_callback_bridge.c:410..420`):
```c
ops = *(uvc_u32 *)((uvc_u32)ep + 8u);
for (i=0;i<16;i++) g_ep0_ops_shadow[i]=rd32(ops+4*i);
g_ep0_queue_orig = g_ep0_ops_shadow[4];
g_ep0_ops_shadow[4] = (uvc_u32)a6400_uvc_ep0_queue_wrap;
*(volatile uvc_u32 *)((uvc_u32)ep+8u) = (uvc_u32)g_ep0_ops_shadow;
```
This is why B16 shows `ops=5f5722f4, queue=5f5681bc`, restored only at STOP
(`EP0 ops restored orig=603dfb4c`). The queue wrapper:
```c
static int a6400_uvc_ep0_queue_wrap(void *ep, void *req, unsigned int gfp)
{
    buf=rd32(req); len=rd32(req+4); dma=rd32(req+8);
    if (!dma && g_class_dir_out && buf>=0x60000000u && buf<0x70000000u) {
        dma=buf-0x60000000u;
        *(volatile uvc_u32 *)(req+8u)=dma;    /* OUT DMA mapping */
        mapped=1;
    }
    printk("EP0 queue lr=... dir=... req=... buf=... dma=... len=... mapped=...");
    a6400_uvc_tstamp("queue-before-orig");
    ret=g_ep0_queue_orig(ep,req,gfp);
    a6400_uvc_tstamp("queue-after-orig");
    /* install completion thunk AFTER the original queue */
    comp=rd32(req+0x1c);
    if (comp && comp!=thunk) { g_req_complete_orig=comp; *(req+0x1c)=thunk; }
    ... GCRO queue / log_events / log_trb / EP0 queue exit ...
}
```
`mapped=1` on SET_CUR is therefore **intentional**: it fills `req->dma` for the
control-OUT data phase (`GET` is IN and needs no map). It is not a descriptor bug.
But the wrapper:
- installs a **completion thunk after the request was queued** (`req->complete` can
  be used by a fast completion);
- runs `a6400_uvc_gcro`, `a6400_uvc_log_events`, `a6400_uvc_log_trb`, timestamps and
  several `printk`s **synchronously inside the EP0/IRQ thread**.

The completion thunk (`a6400_uvc_ep0_complete_thunk`, source 0x317) prints the
request/state/LR, calls `GCRO complete`, `log_events`, `log_trb`, `EP0 list pre`, and
`TS complete-entry` before calling the original `uvc_ep0_comp`/`kfree`. Every one of
these is in the giveback path.

### 1c. Request handling

Our bridge does **not** implement the UVC class state machine; it forwards the CLASS
callback to the reference `core_cb_class` (module 0x17b0):
- `SET_CUR` (`bRequest 0x01`): allocates an EP0 request, `buf=this_ex+0x1c`,
  `length=wLength`, `complete=uvc_ep0_comp`, queues via `ep0->ops->queue`; success 0.
- `GET_CUR` (`0x81`): helper 0x1390 builds the 26-byte probe reply and returns 0.
- `GET_MIN (0x82)`, `GET_MAX (0x83)`, `GET_RES (0x84)` → 0x19c4/0x19f0/0x1a40 paths.
- `GET_LEN (0x85)`, `GET_INFO (0x86)`, `GET_DEF (0x87)` → 0x1a1c/0x1a2c/0x1a38.
- Unknown/incorrect recipient → return 1 (0x1a60) or 2 (0x1a58).

`setup_req` turns `r0==0` into `clear_halt_ep0` + return 0, and `r0==1` into
`-EINVAL` (0x602ba41c); B16 logged `CLASS exit result=0` for both GET and SET, so the
return path is not the fault.

### 1d. B16 shows the instrumentation delaying the status arm

At GET, `GCRO queue` runs **after** `g_ep0_queue_orig` and already sees
`bpl=0894477c, sz=0, ctl=0x00000c52, HWO=0` — the hardware had already completed the
26-byte IN transfer. The log contains ~8 `printk`s between the class entry and the
return to the event loop (`CLASS pre`, `CLASS`, `GCRO`, timestamps, `EP0 queue`,
`GCRO queue`, `CLASS post`). The pending status NRDY (`0x29c`) is processed only after
that return; the host's status OUT token arrives during those prints and gets a NAK;
the host stack retries only at its ~5.01 s control timeout. This is the module-induced
timing that must be removed.

## 2. Descriptors and the 26-byte VS_PROBE payload

### 2a. Configuration/interface topology (`uvc_ptp_descriptors.c`)

- `config`: 3 interfaces, `bNumInterfaces=3`, `bmAttributes=0x80`, `bMaxPower=250`.
- interface 0: PTP class 6/1/1; endpoints `0x81` bulk 512 IN, `0x02` bulk 512 OUT,
  `0x83` interrupt 32 interval 7.
- interface 1: VideoControl, class `0x0e`/1; `vc_extra = s_desc_12598_template[40]`,
  `baInterfaceNr[0]=2`.
- interface 2: VideoStreaming, class `0x0e`/2;
  `vs_extra = s_desc_12625_template[61]` with header endpoint byte changed to `0x84`.
- VS endpoint: address `0x84`, **attributes `2` (Bulk)**, `wMaxPacketSize=512`,
  no companion/extra.
- The IAD is inserted as `{8,11,1,2,14,3,0,0}` for the UVC function.

### 2b. VS frame descriptor (from `s_desc_12625_template`)

```
0e 24 01 01 3d 00 81 00 02 00 00 00 01 00   VS header (bNumFormats=1, wTotalLength=61,
                                             bEndpointAddress=0x84, bTerminalLink=2)
0b 24 06 01 01 01 01 00 00 00 00            uncompressed format (format 1, 1 frame)
1e 24 07 01 00 00 05 d0 02 00 00 5e 1a 00 00 5e 1a 00 00 e1 00 15 16 05 00 01 15 16 05 00
                                            frame: 1280x720, min/max bitrate 0x1a5e0000,
                                            max frame buffer 0x00e10000=14,745,600,
                                            default interval 333333, one interval
06 24 0d 01 01 04                          color matching
```
The payload `dwMaxVideoFrameSize=14,745,600` matches this descriptor's
`dwMaxVideoFrameBufferSize`, but that descriptor value is itself oversized for
1280×720 (1280·720·2 = 1,843,200). The endpoint is **Bulk 512**, while the probe
advertises `dwMaxPayloadTransferSize=300,000`; that is inconsistent with the exposed
endpoint and is the concrete probe/endpoint contract mismatch to fix.

### 2c. Exact 26-byte VS_PROBE template

The verified template is **26 bytes** (not 25):
```
offset  bytes                    field
0-1     00 00                    bmHint = 0
2       01                       bFormatIndex = 1
3       01                       bFrameIndex = 1
4-7     15 16 05 00              dwFrameInterval = 333333
8-9     00 00                    wKeyFrameRate = 0
10-11   00 00                    wPFrameRate = 0
12-13   00 00                    wCompQuality = 0
14-15   00 00                    wCompWindowSize = 0
16-17   00 00                    wDelay = 0
18-21   00 00 e1 00              dwMaxVideoFrameSize = 0x00e10000 = 14,745,600
22-25   e0 93 04 00              dwMaxPayloadTransferSize = 0x000493e0 = 300,000
```
The hex string has 52 hex digits = 26 bytes; the `00 00 e1 00` at 18–21 is present.
The B16 probe did not dump the bytes, but the reference/Unicorn-verified template is
this exact array (interval patched from `this_ex+0xA8`).

## 3. Why STOP at 222.975 hung the MSC switch

`bridge.invoke()` STOP path (`uvc_callback_bridge.c:616..622`) only:
1. logs the STOP snapshot,
2. restores `ep0->ops` (`EP0 ops restored orig=603dfb4c`),
3. calls the reference STOP callback.

It does **not** call `a6400_uvc_restore_descriptors()`; that function
(`uvc_composite_shim.c:719`) is the one that does the actual USB teardown:
`a6400_usb_pullup(gc,0)`, `setup_disconnect 0x602b9464`, `usb_gcw_stop 0x602bd834`,
demotes the UVC drivers, unhooks `make_config_desc`, and clears the descriptor table.
It is called only from the module unregister/error paths (`uvc_composite_shim.c:942`,
and the commit failure at 689), not from STOP.

So after STOP the gadget is still configured as the UVC composite; the host still sees
the UVC device and cannot re-enumerate to Mass Storage. The camera's MSC switch waits
for a USB release that our module never performs; the host hangs, requiring a battery
pull. This is an own-code teardown bug, not a host bug.

## 4. Concrete C fix to test next (no build performed)

1. **Strip diagnostics from the hot path.** Compile out (`#ifdef A6400_UVC_TRACE`,
   default off) all `printk`, `a6400_uvc_gcro`, `a6400_uvc_log_events`,
   `a6400_uvc_log_trb`, `a6400_uvc_tstamp`, and the class-entry `CLASS lr` log. Do not
   install `g_ep0_ops_shadow` / `a6400_uvc_ep0_queue_wrap`, and do not replace
   `req->complete` with the thunk, in the production path. The stock
   `ep0->ops`/`uvc_ep0_comp` path must run untouched; the OUT `req->dma` mapping (if
   still needed) should be a single silent store in a minimal queue wrapper, never a
   logging/GCRO wrapper.
2. **Fix the probe payload and descriptor together.** For a 1280×720 MJPEG/YUY2
   stream choose one coherent set, e.g.:
   - `dwMaxVideoFrameSize = 1,843,200` (1280·720·2) and descriptor
     `dwMaxVideoFrameBufferSize = 1,843,200`, or the actual maximum compressed frame
     size if MJPEG is used;
   - `dwMaxPayloadTransferSize` set to the exposed endpoint's max payload (Bulk 512,
     or a documented multiple the host accepts), **not 300,000**;
   - keep `dwFrameInterval=333333`, format/frame index 1.
   The descriptor and the 26-byte reply must agree exactly.
3. **Fix teardown.** Either call `a6400_uvc_restore_descriptors()` from STOP when no
   stream is active, or require the daemon to unload/restore the module **before** the
   host MSC switch. Verify `pullup=0`, `setup_disconnect`, `gcw_stop`, descriptor table
   restored and the host sees 054C:0CAA before switching; otherwise the STOP path will
   hang again.
4. Keep the local `translated[8]` wIndex translation; it does not mutate
   `dwc->ctrl_req`. Keep the OUT DMA mapping only if the stock queue still leaves
   `req->dma=0` for control-OUT; make it silent.

The B16 evidence therefore points at **our module’s synchronous EP0 instrumentation and
UVC probe/endpoint mismatch plus missing teardown**, not a Windows xHC bug.
