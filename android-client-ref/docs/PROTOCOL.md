# Wire protocols implemented by the a6400 reference client

Everything below is what the code actually puts on the wire, byte for byte. Each section
names the file that implements it and the repository receipt it was transcribed from.

Two transports:

* **A â€” PTP over USB** (`054C:0CAA`, interface class 6). Primary, physically verified.
* **B â€” UVC bulk video** (`054C:0322`, VS MJPEG). Secondary, **UNVERIFIED**: no build of
  this path has ever delivered a frame on this hardware.

---

## 1. PTP container framing (transport A)

Implements: `app/src/main/java/com/a6400/lived/usb/PtpContainer.kt`
Pinned to: `android/cinemahud/android/.../MainActivity.kt:109` (encode) and `:120-138`
(length-prefixed reader); byte-identical to `tools/research/ptp_liveview_client.py`.

Little-endian, 12-byte header, payload follows immediately:

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0 | 4 | `length` | total container length **including** this header |
| 4 | 2 | `type` | 1 command, 2 data, 3 response, 4 event |
| 6 | 2 | `code` | operation code for command/response; 0 in a data container |
| 8 | 4 | `tid` | transaction id, echoed by the camera |
| 12 | n | payload | command parameters (4 bytes each, max 5) or the data phase |

Rules the implementation enforces:

* `length >= 12` and `length <= 4 MiB` (`MAX_CONTAINER_BYTES`); anything else is a protocol
  error and the transport fails closed instead of skipping bytes.
* At most 5 command parameters (`MAX_PARAMETERS`), matching PTP.
* A data phase may be split into several data containers that all carry the same `tid`, in
  order (`dataContainers`). Outbound payloads in this client are 1â€“4 bytes, so a data phase
  is one container in practice; chunking exists so a larger payload can never block the
  bulk-OUT pipe inside a single transfer.
* Reassembly treats the bulk-IN pipe as a byte stream: the header length is trusted only
  after the bounds check, and a partial container stays buffered
  (`PtpContainerAssembler`). Two containers can arrive in one 16 KiB transfer and one
  container can span nine transfers (a 140 KB JPEG).

Transaction ids start at 1, increase monotonically, wrap to 1, and are never reused while a
transaction is live (`allocateTransactionIdLocked`).

---

## 2. Sony SDIO handshake

Implements: `usb/PtpSony.kt` (`handshake`)
Pinned to: `CONTROL_IPC.md` Â§1.2; `sony_ptp.dart:239-250`;
`tools/research/ptp_liveview_client.py:340-358`.

```
1. 0x1002  params [1]            OpenSession        accept 0x2001 or 0x201E
2. 0x9201  params [1, 0, 0]      SDIOConnect ph. 1  require 0x2001
3. 0x9201  params [2, 0, 0]      SDIOConnect ph. 2  require 0x2001
4. 0x9202  params [0xC8]         GetSDIOExtDeviceInfo (capability blob)
5. 0x9201  params [3, 0, 0]      SDIOConnect ph. 3  require 0x2001
```

All four SDIO stages returned `0x2001` physically (E0343:8-9, `p8-status2.json` was
produced after this sequence). `0x201E` (SessionAlreadyOpen) is accepted for step 1 only.

Teardown: `0x1003` CloseSession with no parameters, then release the interface, then close
the device. CloseSession is teardown only; it is never used as a control.

---

## 3. Liveview frames: `GetObject 0x1009` on handle `0xFFFFC002`

Implements: `usb/PtpTransport.kt`

```
host  â†’ 0x1009  params [0xFFFFC002]        (command container)
cam   â†’ data container, payload = complete JPEG (SOI FFD8 â€¦ EOI FFD9), 52â€“141 KB
cam   â†’ response container 0x2001
```

or, when no new frame is ready:

```
host  â†’ 0x1009  params [0xFFFFC002]
cam   â†’ response 0x2001 with an 8-byte (all zero) data phase   â† "no new frame, retry"
```

The 8-byte reply is **a retry token, not an error and not a frame**
(`docs/evidence/0151:21`, `USB_GADGET.md` Â§3.3/C1). The client counts these separately
(`noFrameReplies`) and re-issues immediately.

Frame extraction rules (all fail closed, none silently "repair" a frame):

1. payload length 0 or exactly 8 â†’ no-frame sentinel.
2. find the first `FF D8` (SOI); no SOI â†’ drop, count `invalidFrames`.
3. find the last `FF D9` (EOI) after the SOI; no EOI â†’ drop.
4. extracted length > 512 KiB (`maxFrameBytes`) â†’ drop.
5. anything else is passed to the native decoder as a complete JPEG.

`captureNs` is `System.nanoTime()` at *data-phase completion* â€” the first instant the host
can prove the frame existed. It excludes camera-side encode and is therefore reported as
"host-side age", never as glass-to-glass.

### 3.1 Pipelining and the interleave rule

`PtpTransport.Config.pipelineWindow` keeps 2â€“3 `GetObject` requests in flight. The next
request is issued the moment a slot frees; there is **no fixed cadence and no client-side
settle** (`USB_GADGET.md` Â§4.2/Â§5.3 â€” the 200 ms `apply()` sleep in the old client was
politeness, not a camera requirement).

The hard rule:

> A control command container is written **only when no frame transaction is in flight.**

The frame pump stops adding frames as soon as a control is queued, the pipeline drains, the
control goes out alone, and only then does the pump resume. Rationale: the camera's data
phase for a live `GetObject` arrives on the same bulk-IN pipe, and a control container
must never be inserted between a request and its data phase. Cost: one pipeline drain,
bounded by `controlDrainSlackMs`, ~10 ms per fetch measured (`p8-status2.json:898`).

### 3.2 Timeouts, NAKs and reset

* Bulk IN returning â‰¤ 0 is a USB NAK / empty poll, counted as `nakPolls`; the reader loops.
* A frame transaction that passes `frameTransactionTimeoutMs` (1.5 s) is failed and counted;
  five consecutive frame timeouts fault the transport.
* A control transaction that passes `controlTransactionTimeoutMs` (2 s, plus drain slack)
  raises `PtpTimeoutException`. **The camera state for that operation is unknown and the
  caller must not report success**; the transport keeps running and logs it.
* A protocol error (bad container length, stream desync), or a bulk-OUT write that fails
  three times, faults the transport: every pending waiter is released with an error, the
  pump stops, and `FrameSink.onTransportError` fires. Android's USB host API has no bulk
  transfer cancel, so a desynchronised pipe is never "resynced" by skipping bytes.

---

## 4. `0x9209` â€” the 1730-byte property descriptor

Implements: `usb/PtpSony.kt` (`SonyPropertyParser`, `refresh`), exposed as
`(code, datatype, access, enabled, default, current, form, options, limits)`.
Pinned to: `android/cinemahud/lib/sony_ptp.dart:19-116` and
`tools/research/sony_ptp_controls.py::parse_properties` â€” the two proven parsers, which
agree field for field.

```
u32 count                     number of property descriptors (cap 4096)
u32 reserved                  must be 0

per descriptor:
  u16 code                    property code, e.g. 0xD20D
  u16 datatype                PTP datatype (table below)
  u8  access                  0..127 writable, >=128 read-only
  u8  enabled                 1 = settable in the current mode
  T   default                 default value, width from datatype
  T   current                 current value, width from datatype
  u8  form                    0 = none, 1 = range, 2 = enumeration
  form == 1:  3 x T           min, max, step
  form == 2:  u16 n, n x T    the enumeration (authoritative option list)
```

Datatype widths (`1 << ((datatype - 1) / 2)`, odd = signed):

| datatype | type | bytes | datatype | type | bytes |
|---|---|---|---|---|---|
| 1 | INT8 | 1 | 5 | INT32 | 4 |
| 2 | UINT8 | 1 | 6 | UINT32 | 4 |
| 3 | INT16 | 2 | 7 | INT64 | 8 |
| 4 | UINT16 | 2 | 8 | UINT64 | 8 |
| 9 / 10 | INT128 / UINT128 | 16 | 0xFFFF | string (`u8` count then `u16` each) | â€” |

A datatype with bit `0x4000` set is an array: `u32 count` then `count` values of
`datatype & 0x3FFF`. Caps: 4096 properties, 65535 options; a duplicate code, an unknown
form, a truncated blob or trailing bytes are all protocol errors.

The parser never invents option values: for a **range** descriptor (`form == 1`) the option
list is empty, which is exactly why shutter and aperture can only be stepped. When a
direction has to be derived for such a property, `SonyValue.fallbackOptions` uses the
proven client's lists (`sony_ptp.dart:124-198`) â€” used only to decide a sign, never shown as
a camera-advertised value.

Unknown enumeration values are displayed as `code 0x8xxx (unlabelled)`. The focus-mode table
contains `0x8006`â€“`0x8009`, for which no label exists in any evidence; do not invent one.

---

## 5. `0x9207` (effective) and `0x9205` (acknowledged but NOT effective)

### 5.1 `0x9207` â€” signed notch, the only control that changes a value

```
host  â†’ 0x9207  params [propertyCode]   data phase = one signed byte (-1 = 0xFF, +1 = 0x01)
cam   â†’ response 0x2001
```

Pinned to `sony_ptp.dart:391-393` and physically confirmed for shutter
(1/100 â†’ 1/125 â†’ 1/100), aperture (f/2.8 â†’ f/3.2 â†’ f/2.8), EV (0 â†’ +0.3 â†’ 0) and ISO
(Auto â†’ 800 â†’ Auto) â€” `docs/CINEMAHUD_STOCK_PTP.md:71-74`, `CONTROL_IPC.md` Â§1.3.

A `0x2001` response proves the notch was **accepted**, not that the value moved. The UI
therefore always re-reads `0x9209` after a step and shows the camera's own value; if the
value did not change (mode/lens limit) that is reported, not hidden.

### 5.2 `0x9205` â€” absolute write: acknowledged but NOT effective

```
host  â†’ 0x9205  params [propertyCode]   data phase = value, width = datatypeBytes, LE
cam   â†’ response 0x2001
```

**This is the trap this client is built around.** The camera accepts the container and
answers `0x2001`, and then nothing happens, because the PC-Remote handler for these codes
is `InfraRemoteUsb::CtrlCode2InputKey` (`libInfraRemote.so` `0xb520`), which converts the
property code plus the sign of the value into a *directional UI key*:

| code | returned key | code | returned key |
|---|---|---|---|
| `0x5010` (EV) | â‰¤0 â†’ 3, >0 â†’ 4 | `0x5007` (aperture) | â‰¤0 â†’ 8, >0 â†’ 9 |
| `0xD20D` (shutter) | â‰¤0 â†’ 15, >0 â†’ 16 | `0xD200` | â‰¤0 â†’ 6, >0 â†’ 7 |

`0xD21E` (ISO) and `0xD25A` (priority mode) are not in that chain at all â€” which is exactly
how an absolute ISO write can be acknowledged and silently ignored
(`CONTROL_IPC.md` Â§0, Â§2.4; `docs/CINEMAHUD_STOCK_PTP.md:38-46`).

Consequences, enforced in code:

* `PtpSony.setAbsolute` exists and logs
  `0x9205[...] = <value> acknowledged - NOT proof of effect (...)`.
* **No UI control calls it.** Every step button uses `0x9207`.
* Nothing in this client reports a setting change without a `0x9209` readback.

### 5.3 Value encodings

| Control | Code | Type | Encoding | Notes |
|---|---|---|---|---|
| Shutter | `0xD20D` | UINT32 | `numerator << 16` OR `denominator` (`0x00010064` = 1/100) | denominator 0 = BULB, `0xFFFFFFFF` = unavailable |
| Aperture | `0x5007` | UINT16 | f-number Ă— 100 (`280` = f/2.8) | `0`/`0xFFFF` = unavailable |
| ISO | `0xD21E` | UINT32 | absolute ISO, `0xFFFFFF` = Auto | high byte rendered as `NR<n>` (meaning not decoded) |
| Exposure comp | `0x5010` | INT16 | millistop (`300` = +0.3 EV) | enumeration order is non-monotonic |
| Focus mode | `0x500A` | UINT16 | raw camera enumeration | labels only for 1/2/3/0x8004/0x8005 |
| Battery | `0x5001` | UINT8 | 0â€“100 % | **absent on the a6400** â€” never fabricated |

Notch direction semantics used by the UI (mirrors the proven client's metric, so a step's
sign matches what those controls did physically):

* shutter: metric `-(num/den)` â€” a larger metric is a longer exposure.
* aperture: raw fĂ—100 â€” `+1` closes down.
* EV: raw millistop â€” `+1` is brighter.
* ISO: index in the camera's enumeration â€” `+1` is the next higher option.

---

## 6. Transport B â€” UVC composite (`054C:0322`), UNVERIFIED

Implements: `usb/UvcTransport.kt`, claiming in `usb/UsbHost.kt` (`openUvc`).

This path has **never produced a frame on this hardware**. The transport builds bind on
Windows and then fail to produce samples (`USB_GADGET.md` Â§0, Â§6/B3). The client therefore
fails closed at the first step the device does not support, with a message naming that
step â€” it never presents a black surface as success.

### 6.1 Descriptor parsing

`UsbDevice.getRawDescriptors()` is walked by descriptor type:

| type | meaning | what is read |
|---|---|---|
| `0x02` | configuration | walked only |
| `0x04` | interface | number, alternate setting, class, subclass |
| `0x05` | endpoint | address, attributes, max packet |
| `0x0B` | interface association (IAD) | walked only |
| `0x24` | class-specific interface | subtype below |

UVC subtypes used: VC header `0x01` (gives `bcdUVC`), VS input header `0x01` (streaming
endpoint address, terminal link), `VS_FORMAT_MJPEG 0x06` (format index), `VS_FRAME_MJPEG
0x07` (frame index, `wWidth`, `wHeight`, `dwMaxVideoFrameBufferSize`,
`dwDefaultFrameInterval`, discrete intervals).

Frame selection prefers 1280Ă—720 (the reference descriptor), then the largest buffer, then
a default interval near 1/30 s; the whole interface walk and the final choice are logged.

### 6.2 PROBE / COMMIT

Class requests on EP0:

| Field | SET | GET |
|---|---|---|
| `bmRequestType` | `0x21` | `0xA1` |
| `bRequest` | `0x01` (SET_CUR) | `0x81` (GET_CUR) |
| `wValue` | `CS << 8` | `CS << 8` |
| `wIndex` | entity in the high byte, interface in the low byte (entity 0 for VS) | same |
| data | 26-byte `uvc_streaming_control` | 26-byte `uvc_streaming_control` |

`CS`: `0x01` = `VS_PROBE_CONTROL`, `0x02` = `VS_COMMIT_CONTROL`. The `wIndex` convention
(entity in the high byte, interface in the low byte) matches the repository's own adapter,
which preserves the high byte as the entity id
(`tools/native_camera/uvc_ptp_adapter.c:9-17`).

The 26-byte `uvc_streaming_control` (UVC 1.0/1.1) this client builds:

| Offset | Size | Field | Value used |
|---|---|---|---|
| 0 | 2 | `wHint` | 1 (`dwFrameInterval`) |
| 2 | 1 | `bFormatIndex` | from the MJPEG format descriptor |
| 3 | 1 | `bFrameIndex` | from the chosen frame descriptor |
| 4 | 4 | `dwFrameInterval` | 100 ns units; chosen interval |
| 8 | 2 | `wKeyFrameRate` | 0 (unused for MJPEG) |
| 10 | 2 | `wPFrameRate` | 0 (unused for MJPEG) |
| 12 | 2 | `wCompQuality` | 100 (1 = best â€¦ 1000 = worst) |
| 14 | 2 | `wCompWindowSize` | 0 |
| 16 | 2 | `wDelay` | 0 |
| 18 | 4 | `dwMaxVideoFrameSize` | `dwMaxVideoFrameBufferSize` |
| 22 | 4 | `dwMaxPayloadTransferSize` | min(16384, max frame size) |

Sequence: `GET_CUR(PROBE)` (best effort, logged) â†’ `SET_CUR(PROBE)` â†’ `GET_CUR(PROBE)`
**required** (commit is built from the camera's answer, not from our request) â†’ sanity
check of `dwMaxVideoFrameSize`/`dwMaxPayloadTransferSize` â†’ `SET_CUR(COMMIT)` â†’ read bulk
IN. Any rejection aborts with `UvcUnsupportedException` naming the step.

### 6.3 Payload headers and MJPEG reassembly

Each bulk-IN transfer starts with a UVC payload header:

| Byte | Field | Meaning |
|---|---|---|
| 0 | `bHeaderLength` | header length in bytes (including PTS/SCR fields) |
| 1 | `bmHeaderInfo` | bit0 FID, bit1 EOF, bit2 PTS, bit3 SCR, bit6 ERR, bit7 EOI |
| 2â€¦ | PTS (4 B) / SCR (6 B) | present only when the corresponding flag is set |

Assembly rules: `bHeaderLength` is used but raised to the length implied by the PTS/SCR
flags if the device understates it, and clamped to the transfer size; a FID toggle with a
non-empty buffer drops the truncated frame; exceeding 4 MiB drops the frame; EOF or EOI
completes it; an `ERR`-flagged frame is dropped; the result must contain SOIâ€¦EOI.
Frames are delivered exactly like transport A (monotonic `seq`, drop-oldest queue,
`captureNs` at completion).

---

## 7. Endpoint map

| Transport | Endpoint | Direction / type | Documented | Client behaviour |
|---|---|---|---|---|
| A | `0x02` | bulk OUT | yes (E0315:10-14) | resolved by descriptor, mismatch logged |
| A | `0x81` | bulk IN | yes | resolved by descriptor, mismatch logged |
| A | `0x83` | interrupt IN, 32 B, interval 7 | yes | resolved, read only if `readEventEndpoint` is enabled (default off; no client has ever read it) |
| B | `0x84` | bulk IN (VS) | yes (E0339) | resolved by descriptor; the VS alternate setting carrying it is claimed and selected with SET_INTERFACE |

No endpoint number is ever hardcoded as a transfer target: the constants exist only to
*compare* and log.
