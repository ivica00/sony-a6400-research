# E0315 — USB PTP descriptor firmware evidence; UVC still unresolved

Date: 2026-11-11. Inputs: extracted 8.2.5.7 firmware (nflasha15 image) and
read-only live 8.2.6.0 captures. No camera writes, no mode switch, no /dev/mem;
only bounded `read`/`exec` of `/usr/lib`, `/usr/kmod`, `/proc/uptime`. No source
fabrication.

## 1. Answer in one paragraph

The PTP function descriptor is now confirmed by **two independent sources**: the
retained host capture (E0258/E0240: interface class `6/1/1`, endpoints `0x81`
bulk 512 IN, `0x02` bulk 512 OUT, `0x83` interrupt 32 interval 7) and a
**firmware-side descriptor template inside `libptp.so`**, which contains the
same interface class/subclass/protocol (`09 04 00 00 03 06 01 01 05`) plus a
configuration template and gadget endpoint paths. Live 8.2.6.0 carries the same
USB gadget module set as the extracted image, and `usbg_stillimage.ko`
`.text`/`.data` are byte-identical live vs extracted (only `.comment` differs),
so the extracted module is a faithful live-build input for the Still Image/PTP
function. **UVC remains unresolved**: live `/usr/kmod` has no UVC-specific
module (`usbg_uvc.ko`/`g_webcam.ko` absent), and no UVC class-`0x0E` interface
descriptor exists in the scanned extracted/live libraries or modules; the only
UVC descriptor evidence remains the experimental host composite capture
(E0240/E0258), so the UVC contract keeps its explicit `descriptor_unresolved`
boundary.

## 2. Verified inputs (hashes read locally, re-hashable)

| Input | Size (B) | SHA-256 |
| --- | --- | --- |
| extracted `libptp.so` (nflasha15 image) | 142,348 | `e7fcb34db0cfd5e9…` (full hash in artifact) |
| live `/usr/lib/libptp.so` (read-only capture) | 142,304 | `1a05838102ad0279…` (full hash in artifact) |
| extracted `usbg_stillimage.ko` | 28,016 | `d4843c6abac90888…` |
| live `/usr/kmod/usbg_stillimage.ko` (read-only capture) | 28,016 | `420f6e5db6f1ab5b…` |

`usbg_stillimage.ko` section comparison: `.text` 12,864 B **byte-identical**
(`6d335c4b…` both), `.data` 516 B **byte-identical** (`e9698d76…` both);
`.comment` differs (toolchain metadata only). Extracted module is therefore a
faithful stand-in for the live module.

## 3. PTP descriptor template in `libptp.so`

Offsets are identical in extracted and live captures:

| Offset | Bytes | Decode |
| --- | --- | --- |
| `0x1be6b` | `09 02 00 00 01 01 04 c0 01` | configuration template: bLength 9, type 2, wTotalLength 0 (runtime-patched), bNumInterfaces 1, bConfigurationValue 1, iConfiguration 4, bmAttributes 0xC0, bMaxPower 1 |
| `0x1be74` | `/dev/gadget/net2280` | gadgetfs legacy endpoint base |
| `0x1be88` | `/dev/gadget/ep-a` | endpoint path A |
| `0x1be99` | `/dev/gadget/ep-b` | endpoint path B |
| `0x1beaa` | `/dev/gadget/ep-c` | endpoint path C |
| `0x1bebb` | `09 04 00 00 03 06 01 01 05` | **PTP interface descriptor**: bLength 9, type 4, bInterfaceNumber 0, bAlternateSetting 0, **bNumEndpoints 3**, bInterfaceClass 0x06 (Still Image), subclass 0x01, protocol 0x01, iInterface 5 |
| `0x1bec4` | `Sony Corporation` | iManufacturer string |
| `0x1bed6` | `Sony Digital Still Camera` | iProduct string |
| `0x1beec+` | `DDISCVRY.DPS`, `HDISCVRY.DPS`, `DREQUES…` | PTP device-discovery filenames |

Related endpoint descriptor template bytes exist at `0x201e4`–`0x20211` in the
same library (`07 05 …`): bulk OUT/IN and interrupt IN descriptors in
full-speed/high-speed variants (addresses `0x01`/`0x82`/`0x83`, 64/512 B). They
match the **host-captured PTP endpoint roles** (bulk OUT, bulk IN, interrupt IN)
but not the exact captured addresses (`0x02`/`0x81`/`0x83`), so they are
recorded as endpoint-role corroboration, not as the exact runtime descriptor.

## 4. UVC status (explicit boundary)

- Extracted and live `/usr/kmod` contain only `usbg_buspower`, `usbg_cmn`,
  `usbg_sen`, `usbg_stillimage`, `usbg_storage`, `g_mass_storage` — **no UVC
  gadget module**.
- A class-`0x0E` interface descriptor search over extracted `kmod/*.ko` and
  `lib/*.so` found none; the only UVC evidence remains the experimental host
  composite capture (E0240/E0258: VC class 14/1 no endpoints; VS class 14/2 bulk
  IN 512; IAD `{8,11,1,2,14,3}`), which is not stock-verified.
- Therefore `uvc-control`, `uvc-streaming` and the composite entry keep
  `otgcore_template=None` and their `descriptor_unresolved` boundaries. No
  silent success, no fabricated descriptors.

## 5. Consequence for the otgcore descriptor-table contract

- `ptp` entry: USB descriptor now corroborated by firmware-side bytes
  (`libptp.so 0x1bebb`, interface class 6/1/1, 3 endpoints) in addition to the
  host capture; the **otgcore SET_CONFIG entry template remains unresolved**
  (the entry template in libInfraUsbCmn does not encode class/subclass), so PTP
  selection still stops explicitly rather than inventing an io-type mapping.
- `uvc-*`: unchanged unresolved placeholders.
- Full USB mode-activation sequence, PTP/UVC runtime descriptors as built by the
  original firmware, and image-buffer/media contracts remain **not finished**;
  they are tracked in `docs/UVC_PTP_STATUS.md` and
  `artifacts/analysis/e0303-ptp-uvc-media-buffers.md`.

## 6. Reproduce

`tools/research/...`-free manual commands (read-only):

```
.\venv\Scripts\python.exe tools\camera_debugger.py read /usr/kmod/usbg_stillimage.ko --output artifacts/hardware/live-libs/rootfs/usbg_stillimage.ko --limit 40000
.\venv\Scripts\python.exe tools\camera_debugger.py read /usr/lib/libptp.so --output artifacts/hardware/live-libs/usr/libptp.so --limit 200000
```

Section/hash/decode evidence: `artifacts/analysis/e0680-secs.py`,
`artifacts/analysis/e0681-desc2.py`, plus the JSON summary in
`artifacts/analysis/e0315-ptp-descriptor-evidence.json`.
