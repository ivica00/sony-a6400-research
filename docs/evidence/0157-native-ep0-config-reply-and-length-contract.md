# E0157: Native EP0 Configuration Reply

Date: 2026-11-08. Continuation of E0156. This step does not access the camera.

## Problem Solved

Original Sony `make_config_desc` serializes the entire configuration and only at the end clamps the return length to `wLength`. Inserting the UVC IAD after the result has already been truncated to a 9-byte header is not the same as building the full configuration. Live integration must consistently report 173 bytes in both the short header and the full reply, without writing past the actual output.

## Implementation

Added ARM function `a6400_uvc_ptp_candidate_config_reply` in `tools/native_camera/uvc_ptp_descriptors.{c,h}`:

1. Accepts only standard IN GET_DESCRIPTOR for configuration 0, High Speed. Confirms gadgetcore uses the exact caller-owned candidate.
2. Checks topology before calling the original serializer: counts, alternate/endpoint/extra pointers, and lengths. This avoids calling the original unbounded write on an arbitrarily large tree.
3. Uses a local synchronous request with `wLength=512` and a 512-byte staging buffer. Original setup and output are not modified up to this point.
4. Calls real original `make_config_desc` at `602bbc54`. Expects exactly 165 bytes, inserts the IAD with the real compiled ARM function, and confirms the final 173 bytes.
5. Copies `min(original wLength, 173)` bytes only after all checks. Too-small caller output returns `-28` before serialization; invalid request/topology returns `-22`. Output overlapping setup or the candidate tree is rejected. Native negative serializer result is propagated, though that branch is not separately physically proven.

The caller must keep descriptor topology stable for the entire call. No mutex is introduced here and multi-threaded live integration is not proven. The local request serves only the synchronous original serializer which ran to return in verification; it is not sent to asynchronous EP0 completion.

## Verification of the Real Compiled Path

Extended `tools.research.build_uvc_ptp_descriptor_candidate` executes: compiled reply wrapper -> original Sony serializer/memcpy -> compiled IAD -> copy to caller buffer. No serializer stub. Caller-owned candidate, gadgetcore, speed, setup, and stack are explicit offline fixtures. Original firmware identities remain SHA-pinned, kernel code write-protected, and execution/writes bounded by guards.

172 checks pass: the earlier 24, plus 13 positive requests with six checks each and 14 negative cases with five checks each. These are not 172 physical USB tests.

Positive lengths: 0, 1, 8, 9, 17, 39, 40, 47, 172, 173, 174, 512, 65535. In each, the original serializer is actually called once, output matches the expected prefix, the rest of the buffer remains untouched, and setup and native tree are unchanged.

Negative cases: other-speed, wrong configuration index, recipient, bRequest/wIndex, insufficient capacity, foreign table, wrong speed, interface/alternate count, oversized class/endpoint extra block, and output alias. All are rejected before the native serializer, without modifying setup, tree, or output buffer.

Saved results of the real compiled wrapper:

- `artifacts/native/uvc-ptp-ep0-e0157/native-ep0-reply-9.bin`.
- `artifacts/native/uvc-ptp-ep0-e0157/native-ep0-reply-173.bin`.
- `artifacts/native/uvc-ptp-ep0-e0157/manifest.json` with hashes and observed fixture stack consumption (not a measurement of free live kernel stack).

Header: `09 02 ad 00 03 01 00 80 fa`; `wTotalLength=173`, three interfaces. PTP part remains identical to the physical readback from E0153.

```
python -m tools.research.build_uvc_ptp_descriptor_candidate --output-dir artifacts/native/uvc-ptp-ep0-e0157
```

## Boundary Before Physical Integration

The function has not yet replaced the live gadgetcore EP0 hook. The full native device-descriptor table with strings and device identity is not finished; the existing candidate proves configuration topology, not the whole USB device. Full Speed/other-speed reply is intentionally rejected instead of fabricating an unverified profile; before deployment a real fallback contract must be resolved. Shared register/stop/unregister of original PTP and UVC, rollback, and native JPEG/DMM producer also remain open.

These parts are not wired into existing runtime so the full suite was not repeated after E0156 (605 tests passed). No camera uploads, modules, feeder processes, USB changes, SD, or persistent writes. Physical enumeration and shared UVC+PTP transfer remain unconfirmed.
