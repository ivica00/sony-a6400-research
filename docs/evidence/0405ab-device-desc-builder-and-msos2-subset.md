# E0405ab — Dynamic device-descriptor builder decode and MS OS 2.0 function subset (offline)

Date: 2026-11-12. Offline only: disassembly of the preserved `vmlinux.bin`
(SHA-256 `12eeec82…43707`) and new Python/Unicorn models. No camera access, no
kernel write, no descriptor change, no module load, no PC Remote.

This is the pre-authorisation increment requested before any RAM-only Mass
Storage enumeration check. It answers where `bcdUSB` comes from and delivers the
MS OS 2.0 configuration/function subset plus an offline EP0/chunk/restore model.

## 1. Device-descriptor builder decoded (`usb_gadgetcore_*`, 0x602bb988)

The device descriptor is **generated**, not stored. Function `0x602bb988`
(`gc` in r0, setup in r1, output buffer in r2) selects one per-speed record from
the native root (`r6 = [gc+0x6c]`) using `[gadget+0x20]`:

| `[gadget+0x20]` | selected record |
| --- | --- |
| `5` | `root + 0x20` |
| `3` | `root + 0x10` |
| other (current MSC boot) | `root + 0x00` |

It then writes the 18-byte descriptor:

| Output | Source |
| --- | --- |
| `[0] = 0x12` | bLength (constant) |
| `[1] = 0x01` | bDescriptorType = DEVICE (constant) |
| `[2..3]` | **halfword at selected record offset 0 = `bcdUSB`** |
| `[4] = record[2]` | bDeviceClass |
| `[5] = record[3]` | bDeviceSubClass |
| `[6] = record[4]` | bDeviceProtocol |
| `[7]` | `gadget+0x14` low byte (bMaxPacketSize0), speed-derived overwrite |
| `[8..9] = root+0x30` | idVendor (0x054C) |
| `[10..11] = root+0x32` | idProduct |
| `[12..13] = root+0x34` | bcdDevice |
| `[14] = root+0x37` | iManufacturer |
| `[15] = root+0x38` | iProduct |
| `[16] = root+0x39` (inferred) | iSerialNumber |
| `[17] = root+0x3a` (inferred) | bNumConfigurations |

The E0404 probe read the live selected record as `00 02 00 00 00 01 00 00`
(halfword `0x0200` at offset 0), i.e. **`bcdUSB = 0x0200`**. That is below the
Microsoft OS 2.0 requirement, so a bounded save/restore override of the
**halfword at selected record + 0** to `0x0210` is required alongside the
18-byte OS-string patch. Selection must be re-evaluated at runtime from
`[gadget+0x20]` exactly as the builder does; it is data-only (no text patch).

The builder tail (out[14] and out[15]) was observed directly; out[16]/out[17]
are inferred from the adjacent `strings_1e3d4`/`+0x39/+0x3a` layout and are
marked as such — they will be re-verified in the pre-hardware model diff.

## 2. MS OS 2.0 Descriptor Set with configuration + function subset

`src/a6400/usb_debug_descriptors.py` now builds and validates the composite set
strictly scoped to the vendor interface:

- 46 bytes total:
  - descriptor-set header (10): `wLength=46`, type `0x0000`,
    `dwWindowsVersion=0x06030000`, `wTotalLength=46`
  - configuration subset header (8): `wLength=36`, type `0x0001`,
    `bConfigurationValue=1`, reserved 0, `wTotalLength=36`
  - function subset header (8): `wLength=28`, type `0x0002`,
    `bFirstInterface=1`, reserved 0, `wSubsetLength=28`
  - compatible-ID feature (20): type `0x0003`, `WINUSB\0\0`, zero sub-ID
- `validate_winusb_20_composite_binding()` verifies every length/header,
  configuration value, `bFirstInterface = 1` and the single-interface scope, so
  WinUSB binds the vendor function and not the composite parent.
- `ms_os_20_vendor_reply()` serves the whole set for `wIndex=0x0007` and the
  configuration subset (set header stripped) for `wIndex=0x0008`.

## 3. Unicorn + Python EP0/chunk/restore model

`src/a6400/debug/gadgetcore_ep0_model.py`:

- `DescriptorModel`: extends the stock MSC configuration with the
  zero-endpoint vendor interface 1 (`0xFF/0xDB/0x01`), answers
  `GET_DESCRIPTOR(Device)` with `bcdUSB=0x0210`, `GET_DESCRIPTOR(Config)`,
  `GET_DESCRIPTOR(String 0xEE)` with the `MSFT20`+`0x02` descriptor, and the
  MS OS 2.0 vendor requests.
- `ChunkTransport`: request assembly from ≤64-byte OUT chunks into exactly one
  4096-byte protocol frame and 64-byte IN chunking of the reply (short tail
  supported); rejects out-of-order/oversized chunks.
- `SaveRestoreGuard`: tracks the OS-string 18 bytes, `gadgetcore+0x84` byte and
  the `bcdUSB` halfword; `reconfiguration_allowed()` stays false until every
  active patch has been restored and verified, implementing the mandated guard
  ordering before any USB reconfiguration and on `rmmod`.
- `UcChunkEngine`: executes the **real assembled ARM bytes** of
  `a6400_chunk_extract`/`a6400_chunk_insert` (freestanding C compiled for
  ARMv7 softfp, 200-byte `.text`, SHA-256
  `ce24b860df46dee092899ba967d8831274dfba505088a43798751bd3707ab45b`)
  under Unicorn. Tests verify extract/insert against the Python framing and the
  bounds rejection path.

`tests/test_gadgetcore_ep0_model.py`: 11 tests pass (descriptor responses,
configuration/function subset bytes, chunk framing, restore guard ordering,
Unicorn extract/insert/overflow). `tests/test_usb_debug_descriptors.py` grows to
19 passing tests with the composite-set layout/tamper checks.

## 4. Status and next step

- **Ready for the pre-authorisation gate:** device-descriptor builder offsets,
  `bcdUSB = 0x0200` override plan, the 46-byte MS OS 2.0 composite set, the
  zero-endpoint vendor interface, chunk framing and the restore guard are all
  modelled and tested offline.
- **Not done:** the real module (tree extension, EP0 queue wiring, cdev, daemon
  bridge) is still unimplemented, and no hardware interaction was performed.
- **Next hardware gate (needs authorisation):** RAM-only Mass Storage load for
  **enumeration only** with save/restore of the OS string, `gc+0x84` and the
  `bcdUSB` halfword; verify Windows sees the vendor interface and Mass Storage
  stays functional, then unload and CRC-verify all three restores. WinUSB
  binding/`--transport winusb` comes after that enumeration check.

Full suite after these models: **1,385 tests OK**.
