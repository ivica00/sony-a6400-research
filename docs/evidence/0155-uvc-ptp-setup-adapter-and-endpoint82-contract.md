# E0155: UVC/PTP Request Adapter and Endpoint 82

Date: 2026-11-08. Continuation of E0154; compatibility with Sony host programs is not a goal. All changes in this step are offline.

## Original Obstacles

Original reference `usbg_video.ko` SHA-256 `d385a051bf01b0e5ea37412623ae85cfe3cda76ab0d11e61d111994ca9fbf4fb`:

- `core_cb_class` at `.text+17b0` calls helper at `+1390`. For GET request A1 the helper reads `wIndex`, first splits high-byte entity ID, then low-byte interface. Interface 0 enters VC path, non-zero interface enters VS path. Without an adapter the new VC interface 1 wrongly enters VS. This was confirmed with the original ARM slice, not merely disassembly interpretation.
- `core_cb_start` at `+10f0` at `+116c` executes `mvn r2,#0x7e`, then at `+1174` writes byte 81 into the native request tag at `extended-context+18`. Changing only USB descriptors/endpoint wrapper does not change this tag.

## Implementation of Standalone Adapter Parts

`tools/native_camera/uvc_ptp_adapter.{c,h}` are not wired into the active bridge.

`a6400_uvc_ptp_translate_setup` takes caller-owned 8-byte wire and output buffers and the exact wire shadow (1 or 2). For class/interface 21/A1 requests it translates exclusively `wIndex` low-byte 1->0 or 2->1. High-byte entity ID remains unchanged, as do `bRequest`, selector, length, and direction. PTP interface 0, wrong shadow, standard/vendor/endpoint recipient, null, and overlapping buffers are rejected before any write. The original request is not modified.

The caller must prove output buffer lifetime for native callback/completion. This API alone does not solve that. No stack-buffer passing into a live driver and no assumption that native code never retains the pointer.

`a6400_uvc_ptp_select_endpoint` for the planned HS profile requires:

- Native `dwc`, native list, and low-byte count 1..16 (upper padding bytes are not count, per earlier physical contract).
- Raw endpoint from `dwc+e4` (0x82 per original DWC lookup contract), enabled bit in `raw+4c`, and raw descriptor 7/5/82/Bulk/maxpacket512.
- Exactly one gadgetcore wrapper with `wrapper+24` equal to that raw endpoint.

Zero, wrong PTP channel 81/83, interrupt, wrong size, wrong wrapper, and duplicate/ambiguous ownership return zero. The function does not allocate an endpoint and does not prove pointer legitimacy; it must receive them from a verified kernel START contract. In the check all these objects are explicit fixtures.

## Explicit MOD Edit of START Tag

Builder preserves the original module and produces a separate `reference-endpoint82.offline.o`. Before editing it checks full SHA and exact instruction bytes at `.text+116c` (`7e20e0e3`). It changes them to `7d20e0e3` (`mvn r2,#0x7d`). Across the entire file, exactly one byte differs, at file offset 11a0. Relocations and all other bytes remain identical.

Original slice writes 81; explicitly modified slice writes 82. Neither was executed through full START. Registers/request memory are explicit fixtures and execution stops before further native calls.

SHA-256 of modified offline object: `4e45ec555d284ce5686babbd4a56dcfcbb073e71dc2ffdd2de606a290a2a3307`. This is not a complete linked module and must not be loaded as a finished UVC+PTP mod.

## Checks

`tools.research.build_uvc_ptp_adapter` builds a standalone ARM ELF without unresolved imports. It executes the real compiled adapter, original ARM classification slices, and separate MOD slice. Reference code is write-protected during execution; the host explicitly modifies it between parallel runs only for the documented MOD test and invalidates code cache. Code/write guards constrain execution and writes.

55 checks pass, including entity ID preservation, original VC/VS path, rejections without writes, original count low-byte, endpoint identity/descriptor negative cases, and single-byte MOD comparison. GET classification stops before allocator/queueing; SET_CUR test verifies only transformed bytes. No fabricated successful firmware allocator or callback returns.

```
python -m tools.research.build_uvc_ptp_adapter --output-dir artifacts/native/uvc-ptp-adapter-e0155
```

Results and hashes: `artifacts/native/uvc-ptp-adapter-e0155/manifest.json`. Existing live bridge and module builder were not modified. Previous 605 project tests from E0154 were not repeated since the new isolated parts are not wired into existing runtime.

## Remaining Before Camera

Must prove setup-buffer lifetime/completion and wire new wire shadow routing without changing reference lifetime contract. Shared PTP/UVC gadgetcore register/stop/unregister and rollback to PC Remote are not yet implemented, nor are FS configuration/Windows grouping, or native JPEG/DMM ownership. Existing bridge compares full `wIndex` against interface number, which rejects entity high-byte; it must be explicitly adapted on integration, alongside these checks. Do not wire the adapter as if its mere existence solves this.

In this step there is no camera access, uploads, modules, feeder processes, USB mode change, or SD/persistent writes. Physical UVC+PTP is not proven.
