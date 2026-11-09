# E0188 — EP0 disable retirement and closed admission

Offline original kernel execution using SHA-256 `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707`. No camera access, upload, hook publication or module change.

## Original admission contract

E0184 established that pullup(0) clears dwc+0x170 before waiting for the event worker. Original `__dwc3_gadget_ep0_queue` at `0x602b26ec` reads this same field at `0x602b2704`. Zero returns -108 (ESHUTDOWN) through `0x602b2834` before modifying request status, actual length, endpoint number or queue links. Thus this field is an admission gate in the actual internal EP0 queue path, not merely a display state.

## Original disable contract

Original endpoint disable `0x602b1a3c` calls cleanup `0x602b0484` first. The latter executes original giveback `0x602affb8` for active and pending requests (E0187). Disable then clears the endpoint enable bit in MMIO+0x620 and zeroes endpoint descriptor +0x1c, +0x44 and flags +0x4c, with associated flag bytes updated. For endpoint numbers zero and one it skips non-EP0 endpoint accounting. Both calls made by E0184 pullup can therefore reach the same original synchronous request retirement path.

## Controls

Extended `tools/research/probe_uvc_ptp_request_retirement.py` now passes **7 cases**: the five E0187 cases and two complete original EP0/EP1 disable cases, each with one active and one pending request. New cases check both completion calls, empty lists, cleared descriptor/flags and correct MMIO enable-bit clear. They then execute the original internal EP0 queue body with dwc+0x170 zero, checking -108, byte-equal request state and unchanged empty queue.

```
python -m tools.research.probe_uvc_ptp_request_retirement --output-dir artifacts/analysis/uvc-ptp-ep0-retirement-e0188
```

Manifest: `artifacts/analysis/uvc-ptp-ep0-retirement-e0188/manifest.json`.

Hardware stop, unmap, completion, lock and migration operations remain explicit service doubles. The tested endpoint flags select ordinary enabled/non-stalled state; stall clearing and TRB accounting are not covered. MMIO is a fixture, not hardware. Queue is attempted after disable, not reentrantly during the completion double; its early-zero gate is executed directly. Concurrency, public queue wrapper locking, all alternate submission paths and physical DMA cessation are not established by these tests.

## Next boundary

The original paths now provide a concrete order to preserve: close EP0 admission, allow event worker to finish, retire requests and return from their completions, then consider callback retirement. Need verify the public queue wrapper's locking, module lifetime/publication and rollback composition before enabling the shared candidate. The module was unchanged, so prior full project tests were not rerun. E0182 remains candidate; combined PC Remote+UVC/PTP test remains not ready and camera should remain in Mass Storage.
