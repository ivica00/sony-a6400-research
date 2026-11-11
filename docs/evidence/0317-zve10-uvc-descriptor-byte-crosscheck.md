# E0317 — ZV-E10 UVC descriptor byte cross-check (a6400 UVC chain source)

Date: 2026-11-11. Inputs: ZV-E10 2.03 extracted `libInfraUsbCmn.so`
(SHA-256 `af830315…`, 94,612 B), E0154 verified 173-byte UVC+PTP
configuration descriptor (`cc99cbd9…`), E0316 chain inventory. Offline only; no
camera writes, no mode change, no module loading.

## 1. Result

The E0154 UVC+PTP configuration descriptor is now **byte-derived and verified
against the original ZV-E10 source tables**: its VideoControl and
VideoStreaming class-specific blocks equal the ZV-E10 `libInfraUsbCmn.so`
descriptor bytes at file offsets `0x12598` (VC, 40 B) and `0x12625` (VS, 61 B),
with exactly the **two documented byte changes** that adapt the stock ZV-E10
profile to the a6400 PC-Remote-compatible composite:

| Block | ZV-E10 source offset | Candidate diff | Meaning |
| --- | --- | --- | --- |
| VC class-specific (40 B) | `0x12598` | byte 12: `0x01` → `0x02` | VC header baInterfaceNr 1 → 2 (video streaming interface number) |
| VS class-specific (61 B) | `0x12625` | byte 6: `0x81` → `0x82` | VS bEndpointAddress 0x81 → 0x82 (avoid PTP address) |
| MJPEG frame descriptor (30 B) | `0x1263e` | none | 1280×720, default interval 0x51615 (333,333 × 100 ns ≈ 30 fps), max frame buffer 14,745,600 |

Source VC blob (`0x12598`, 40 B):
`0d240100012800006cdc020101 122402010102000000000000000003000000 092403020101000100`

Source VS blob (`0x12625`, 61 B): candidate VS blob with endpoint byte restored
to `0x81`:
`0e2401013d008100020000000100 0b24060101010100000000 1e240701000005d00200005e1a00005e1a0000e100151605000115160500 06240d010104`

Frame descriptor (`0x1263e`, 30 B):
`1e240701000005d00200005e1a00005e1a0000e100151605000115160500`

The PAL/25 fps counterparts live in the same table (`streaming_pal_*` symbols,
frame blob at `0x12550`, interval 0x61A80 = 400,000 → 25 fps). The candidate
uses the NTSC/30 fps profile, matching E0134's decoded 720p frames.

## 2. Why this matters

- The UVC chain exists only in ZV-E10 firmware (E0316). This cross-check proves
  the descriptor bytes used by the a6400 contract are the **original Sony
  ZV-E10 descriptor bytes**, not invented or hand-built ones, apart from two
  documented interface/endpoint adaptations.
- The a6400 `uvc-control`/`uvc-streaming`/composite entries therefore have
  firmware-source descriptor evidence; their **otgcore SET_CONFIG template
  remains unresolved** (the entry template does not encode class/subclass), so
  selecting them still stops explicitly.
- No silent success: descriptor evidence only; no UVC function is claimed.

## 3. Code/test hooks

`src/a6400/execution/guest_usb_otgcore.py`:
`ZVE10_UVC_SOURCE_BLOBS`, `ZVE10_UVC_DESCRIPTOR_CHANGES`,
`uvc_ptp_configuration_source_crosscheck()`.

Tests (`TestZvE10UvcChainEvidence`): candidate VC/VS class blocks equal the
source blobs after applying exactly the two documented byte changes; frame
descriptor equals the source NTSC frame bytes.

Full suite: see next run (expected 898+ tests OK).
