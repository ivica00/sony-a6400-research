# E0389 — B17 ETL decode: GET_CUR now fails in ~2.9 ms with XACT_ERROR (no 5 s timeout), no SET_CUR/COMMIT; e0388 probe path and VS descriptors audited

Date: 2026-11-12. Fast offline analysis. No camera run.

Input: `artifacts/analysis/e0388-runb17cleanep0/usb-capture.etl` (6,250,496 B) →
`tracerpt -of XML` 58,136,265 B → 27,350 records; control URBs extracted and paired.

## 1. B17 host URB timeline (Sony 054C:0322, UCX UsbDevice `0x597383899398`)

Only **two** control URBs on the Sony device; both are `GET_CUR` retries:

| # | Start (UTC) | Duration | bmRequestType | bRequest | wValue | wIndex | wLength | USBD_STATUS |
|---|---|---|---|---|---|---|---|---|
| 1 | 06:57:15.1612973 | **2.925 ms** | 0xA1 | 0x81 | 0x0100 | 0x0002 | 0x001A | **0xC0000011 XACT_ERROR** (Nt 0xC0000001) |
| 2 | 06:57:15.1644769 | **2.858 ms** | 0xA1 | 0x81 | 0x0100 | 0x0002 | 0x001A | **0xC0000011 XACT_ERROR** (Nt 0xC0000001) |

- **GET_CUR no longer waits 5.01 s**: it completes in **2.9 ms**, twice, both with
  `USBD_STATUS_XACT_ERROR`.
- **No `SET_CUR` for VS_PROBE_CONTROL (0x0100) and no `VS_COMMIT_CONTROL`
  (0x0200) was ever submitted.** The host retried GET_CUR once and then ffmpeg
  exited with `Could not RenderStream to connect pins`.
- No bulk/iso URB on the Sony device; the 4,578 isoch URBs in the trace belong to
  other devices. The UVC stream never started on the wire.

So the clean build fixed the 5 s timeout, but exposed the earlier hidden failure:
the 26-byte GET_CUR reply is rejected at the wire/protocol level (`XACT_ERROR`).

## 2. Did e0388's 26-byte probe change reach the helper?

- `core_cb_class` GET path `0x19b0` calls helper **0x1390**; for `wValue=0x100/0x200`
  that helper calls **0x11bc** (`bl 0x11bc` at `0x16a8`).
- Helper **0x11bc** at `0x11d4..0x11e4` does:
  `r0=fp-0x46; r1=[pc,#0x1a0] (literal); r2=0x1a; bl memcpy` — it copies the
  **26-byte rodata template**, then patches `dwFrameInterval` from `this_ex+0xA8`,
  builds the request (`req->buf`, len 26, complete `uvc_ep0_comp`) and queues it.
  `dwMaxVideoFrameSize` and `dwMaxPayloadTransferSize` come from the template, not from
  live `this_ex` fields.
- The e0388 final module contains the new template at file offset `0xaa7e`:
  `00000101151605000000000000000000000000201c00f4ff0100` (old bytes absent).
  So the patched rodata is what 0x11bc copies; no `this_ex` update was needed for
  those two fields. **However**, B17's GET_CUR never succeeded, so the exact 26 bytes
  on the wire cannot be confirmed from this ETL; the request failed with XACT_ERROR.

## 3. Descriptor dump (byte-for-byte)

### VC extra (40 B, template + `vc_extra[12]=2` patch)
```
0d 24 01 00 01 28 00 00 6c dc 02 01 01 12 24 02 01 01 02 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 09 24 03 02 01 01 00 01 00
```
Wait: the exact source array is 40 B:
`0d240100012800006cdc020101122402010102000000000000000003000000092403020101000100`
Decoded: VC header (13 B): bLength 0x0d, type 0x24, subtype 1, bcdUVC 0x0100,
wTotalLength 0x0028 (40), dwClockFrequency 0x02dc6c00 (48 MHz), bInCollection 1,
baInterfaceNr[0]=**2** after the `vc_extra[12]=2` patch. Then input terminal
(18 B, subtype 2, ID1, camera terminal) and output terminal (9 B, subtype 3, ID2,
source ID1).

### VS extra (61 B)
```
0e 24 01 01 3d 00 84 00 02 00 00 00 01 00
0b 24 06 01 01 01 01 00 00 00 00
1e 24 07 01 00 00 05 d0 02 00 00 5e 1a 00 00 5e 1a 00 20 1c 00 15 16 05 00 01 15 16 05 00
06 24 0d 01 01 04
```
- VS input header (14 B): bLength 14, type 0x24, subtype 1, bNumFormats 1,
  **wTotalLength 0x003d = 61**, **bEndpointAddress 0x84**, bmInfo 0,
  bTerminalLink 2, bStillCapture 0, bTriggerSupport 0, bTriggerUsage 0,
  bControlSize 1.
- Format descriptor (11 B): bLength 0x0b, subtype 6 (uncompressed/MJPEG shape),
  bFormatIndex 1, bNumFrameDescriptors 1, bmFlags 1, bDefaultFrameIndex 1,
  aspect 0/0, interlace 0, copy-protect 0. It has **no 16-byte `guidFormat`**, so it
  is the 11-byte **MJPEG** format descriptor, not the 27-byte uncompressed one.
- Frame descriptor (30 B): bFrameIndex 1, bmCapabilities 0, **wWidth 0x0500=1280**,
  **wHeight 0x02d0=720**, min/max bitrate 0x1a5e0000, **dwMaxVideoFrameBufferSize
  0x001c2000=1,843,200**, default interval 0x00051615=333333, one interval.
- Color matching (6 B).
- VS interface: bInterfaceNumber **2**, bAlternateSetting **0**, bNumEndpoints **1**;
  endpoint **0x84**, bmAttributes **2 (Bulk)**, wMaxPacketSize **512**, no companion.

### Windows/usbvideo checks
- VS header `bEndpointAddress=0x84` matches the endpoint descriptor 0x84; VC
  `baInterfaceNr=2` matches VS interface 2; VC wTotalLength 40 and VS wTotalLength 61
  are internally consistent.
- The format is MJPEG-shape (no guidFormat). `ffmpeg` explicit
  `-f dshow -video_size 1280x720 -framerate 30 -i video="ILCE-6400"` can be tried,
  but it cannot fix a graph-level `RenderStream` failure caused by the failing
  GET_CUR/descriptor acceptance.
- The Bulk endpoint is legal UVC, but `dwMaxPayloadTransferSize=131,060` is not a
  multiple of the 512-byte endpoint packet and is far above the endpoint max packet;
  this is the remaining descriptor-level suspect for the host rejecting the probe
  reply. `dwMaxVideoFrameSize` now matches the frame descriptor (1,843,200).

## 4. Verdict

- Hot-path timing defect is fixed: GET_CUR is **2.925 ms**, not 5.01 s.
- New immediate failure: GET_CUR returns `0xC0000011 XACT_ERROR` on two attempts; the
  host never sends SET_CUR/COMMIT, so ffmpeg cannot build the DirectShow graph.
- e0388's probe template is present in the module and the helper copies that rodata
  template (interval patched from `this_ex`), so the new frame/payload values should be
  on the wire; the ETL shows the transfer failed before a successful 26-byte exchange.
- Next: determine why the 26-byte reply causes XACT_ERROR (payload alignment/content,
  or Bulk `dwMaxPayloadTransferSize` vs 512 endpoint); fix the probe/endpoint contract
  and retest. No camera run was performed for E0389.
