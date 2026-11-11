# E0321 — ZV-E10 UVC enablement manifest for a6400 (fail-closed verdict)

Date: 2026-11-11. Offline only. Inputs: extracted a6400 8.2.5.7 and ZV-E10 2.03
trees; hash-pinned components from E0316/E0320. No camera access, no module
load, no camera write, no mode change.

## 1. Result

The enablement state is now a generated, hash-checked manifest:

`artifacts/analysis/e0321-uvc-enablement-manifest.json`
(built by `tools/research/uvc_enablement_manifest.py`).

**Verdict: `not_enabled`** — the a6400 tree is missing four ZV-E10 UVC chain
components and the two device nodes:

| Item | a6400 state | Required (ZV-E10 2.03) |
| --- | --- | --- |
| `usbg_video.ko` | missing | 20,668 B `d385a051…` |
| `usbg_audio.ko` | missing | 20,456 B `8f735727…` |
| `libInfraStreamingUsb.so` | missing | 52,524 B `0a9448e3…` |
| `libInfraUsbCmn.so` | hash mismatch (85,876 B a6400 build) | 94,612 B `af830315…` |
| `devno.ko` | hash mismatch (4,308 B a6400 build `3b36fcea…`) | 4,368 B `273db657…` |
| `/dev/usb/audio` | absent | 248:32 |
| `/dev/usb/video` | absent | 248:33 |

ZV-E10 reference check: all five pinned components `verified` (including
`devno.ko`). Module vermagic is **equal** (`3.0.27_nl-rt106+ SMP preempt
mod_unload ARMv7`), so symbol/vermagic parity holds (E0316); this is not
loadability proof.

## 2. Device-node table decoding note

The pure parser (`src/a6400/execution/zve10_uvc_enablement.py`) decodes Sony
`devno.ko` entries as 12 bytes `{name_offset, dev_t, flags}` where the dev code
is `major << 16 | minor`; for the `usb/*` group the minor is stored in the flags
word (`0x10000 | minor`). The a6400 table reproduces the physical camera nodes
(massstorage 248:0 … adb 248:16); the ZV-E10 table additionally has audio
248:32 and video 248:33. The a6400's own `/dev/usb` listing on the live camera
(E0320 read-only) matches the parsed a6400 table, which validates the decoder.

## 3. Enablement steps (declared overlay only)

1. **Device nodes:** add ZV-E10 `devno.ko` entries `/dev/usb/audio` 248:32 and
   `/dev/usb/video` 248:33 via a declared modified overlay or equivalent
   node-namespace contract.
2. **Kernel modules:** add `usbg_video.ko` + `usbg_audio.ko` (hash-pinned) and
   keep `usbg_stillimage`/`usbg_storage` in the same gadgetcore configuration;
   load order `usbg_cmn` → video/audio is implied by `usbg_cmn_reg` usage but
   not yet physically proven.
3. **User-space chain:** add `libInfraStreamingUsb.so` and streaming-enabled
   `libInfraUsbCmn.so`; the a6400 build lacks the streaming tables
   (`streaming_*`, `CUsbGadgetStreaming`).
4. **Emulator contracts:** serve the video node only through the fail-closed
   `GuestUsbVideo` (E0320) until the 56-byte request and buffer/completion
   paths (E0319) are decoded; host USB enumeration/`SET_CONFIG` remains the
   orthogonal gap (E0318).
5. **Physical load** of ZV-E10 modules on the a6400 changes camera runtime and
   requires separate explicit authorization, recovery plan and teardown
   receipts; nothing was loaded.

## 4. Boundaries

- `missing_components: libInfraStreamingUsb.so, usbg_audio.ko, usbg_video.ko`
- `hash_mismatch: devno.ko, libInfraUsbCmn.so`
- `device_node_gaps: /dev/usb/audio (absent); /dev/usb/video (absent)`
- No UVC function/frame is claimed; no camera write or mode change occurred.
- Full suite after this work: **918 tests OK** (5 new enablement tests).
