# E0154: Native UVC+PTP Candidate and Original Sony Serializer

Date: 2026-11-08.

## User Goal

Compatibility with Sony desktop applications is not a requirement. The goal is UVC video alongside original PTP/PC Remote protocol for future custom open-source applications. This does not remove the need for the active original Sony PTP driver, sensor, native callbacks, and memory ownership.

## Implementation

Added `tools/native_camera/uvc_ptp_descriptors.{c,h}` implement a separate ARM32 table candidate in original Sony format: speed entry 16 bytes, configuration 24, interface 8, alternate 20, and endpoint 20. Sizes are protected by compile-time checks.

The candidate is not wired into the physical module and performs no registration or USB link change. Only the High Speed profile is populated. There is no declared Full/Super Speed support; that remains a blocker before deployment.

| Interface | Function | Channels |
|---|---|---|
| 0 | Original PTP 06/01/01 | 81 Bulk IN, 02 Bulk OUT, 83 Interrupt IN |
| 1 | UVC VideoControl | no endpoints |
| 2 | UVC VideoStreaming | 82 Bulk IN, 512 bytes |

0x82 is not exposed in the physically read PC Remote layout. Earlier candidate 0x84 was replaced with 0x82: original `dwc3_gadget_init` runs `dwc3_gadget_init_hw_endpoints` with the number of IN endpoints from `dwc+2f2`; that helper constructs indices sequentially from zero (`r7`). Exposing 0x83 with that initializer strongly implies the preceding IN endpoint 0x82 exists. This is an inference from static code and descriptors, not a live slot readback, allocation result, free TRB/FIFO capacity, or physical UVC transfer on 0x82.

VideoControl and VideoStreaming class-specific blocks come from original ZV-E10 `libInfraUsbCmn.so`. Exactly two bytes were changed: VC `baInterfaceNr` 1->2 and VS `bEndpointAddress` 81->82. Original profile remains 1280x720/30; this does not prove sensor UVC 720p30. Audio is not included in this candidate.

A dedicated ARM function inserts the video IAD before interface 1. It first validates the entire chain, length, capacity, and unique insertion point. It rejects duplicate insertion and does not modify the buffer on rejection. It takes a fully serialized configuration; in a future live wrapper it must be called before truncating to the host's `wLength`. Calling it on an already truncated header reply is disallowed.

## Original Serializer Executed to Return

`tools.research.build_uvc_ptp_descriptor_candidate` builds a standalone ARM ELF with no unresolved imports. It then actually executes its init and IAD functions, as well as original a6400 `make_config_desc` at `602bbc54` and `memcpy` at `60258b80`. There is no host replacement of serializer/memcpy or fabricated successful firmware return. Kernel is write-protected. Execution is bounded to those original functions and the compiled candidate; writes only to the declared candidate, output, and stack. Gadgetcore, speed=3, caller-owned tree, and requests are explicit offline fixtures, not a capture of an active controller.

Verified identities:

- a6400 kernel SHA-256: `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707`.
- ZV-E10 `libInfraUsbCmn.so` SHA-256: `af830315ce51c38b010995f2147d556286364323734f64b877fcc3bb1a916c02`.

24 checks pass, including original full-configuration return, 9-byte header, 17-byte and zero-length requests, unique endpoint addresses, equality of PTP interface/endpoint bytes with physical PC Remote readback, strictly bounded edits to original VC/VS blocks, valid IAD, and rejections without partial writes. IAD increases configuration size from 165 to 173 bytes.

Artifacts: `artifacts/native/uvc-ptp-descriptors-e0154/`:

- `candidate.elf`: offline ARM candidate, not a kernel module.
- `sony-serialized-before-iad.bin`: original serializer output, 165 bytes.
- `uvc-ptp-hs-config.bin`: after compiled ARM IAD function, 173 bytes.
- `manifest.json`: all 24 checks, hashes, evidence boundaries, and configuration.

Build:

```
python -m tools.research.build_uvc_ptp_descriptor_candidate --output-dir artifacts/native/uvc-ptp-descriptors-e0154
```

## Physical PC Remote Contract and Deploy Boundary

GetDeviceInfo 1001 returned 2001 and ILCE-6400. Advertised vendor operations: 9201, 9202, 9205, 9207, 9209. Not advertised: 9280/9281, which the existing debugger transport uses in MTP. Absence from the list is not itself proof that the call never works, but it is not justified to assume the debugger remains available after MSC->PC Remote transition. No 9280/9281 call was sent. Raw DeviceInfo and JSON saved in `artifacts/hardware/uvc-ptp-coexistence-e0152/pc-remote-device-info.*`.

The candidate is not yet ready for loading. Still needed:

- Bind UVC wire interfaces 1/2 to reference callbacks that expect the old layout; specifically verify `wIndex`/entity ID and request lifetime.
- Change physical START endpoint bridge from hardcoded 81/dwc+dc to verified 82/dwc+e4, with native wrapper identity and descriptor guards.
- Preserve the original PTP driver in shared gadgetcore configuration, implement registration and teardown with return to PC Remote.
- Resolve Full Speed reply, device descriptor/Windows grouping, EP0 full reply before IAD/truncation, and readback/recovery without a lost debugger.
- Bind real native JPEG frames with DMM ownership and profile dimensions.

There is no physical composite enumeration test or UVC+PTP transfer test yet.

## Checks and Final State

Full suite: 605 tests passed in 18.685 s. An additional 24 offline ARM controls passed. Final hub readback `pc-remote-after-e0154.json` confirms the same Sony 054c:0caa and identical original PC Remote descriptors, no errors. No camera uploads, modules, feeder processes, USB mode changes, or SD/persistent writes.
