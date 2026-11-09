# E0187 — Original request retirement and completion

Offline original ARM execution against kernel SHA-256 `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707`. No camera access, upload, hook or module change.

Original endpoint cleanup at `0x602b0484` walks endpoint+0x2c (active list), calling stop_active_transfer first when nonempty, then gives back each request with -108 (ESHUTDOWN). It subsequently gives back requests on endpoint+0x24 (pending list). The surrounding stop_active_transfers loop at `0x602b04f4` starts with dwc+0xd8, not the dwc+0xd0/+0xd4 EP0 entries: E0184's later EP0 disable calls remain a separate path to verify.

Original `dwc3_gadget_giveback` at `0x602affb8` unlinks request+0x34/+0x38, poisons those links, clears request+0x48, and replaces status at +0x2c only if it is -115 (EINPROGRESS). In the tested ordinary path it calls unmap, releases dwc+0x70 lock and enables migration, calls completion pointer request+0x1c with endpoint/request arguments, then disables migration and relocks. The callback call is synchronous, but it occurs after unlocking, so concurrent or reentrant request production is not excluded by that call alone.

`tools/research/probe_uvc_ptp_request_retirement.py` executes both original cleanup and giveback bodies together. All **5 cases pass**: empty lists, pending only, active only, both lists and preserving pre-existing error -5. Checks cover list emptiness, active-before-pending order, hardware-stop service invocation for active requests, status visible at completion, cleared ownership field and unlock/callback/relock order.

```
python -m tools.research.probe_uvc_ptp_request_retirement --output-dir artifacts/analysis/uvc-ptp-request-retirement-e0187
```

Manifest: `artifacts/analysis/uvc-ptp-request-retirement-e0187/manifest.json`. Objects/lists are explicit fixtures; request flag bit2 is clear, so TRB accounting is not tested. Transfer stop, unmap, completion, locks and migration are service doubles. Completion does not enqueue a new request. No physical DMA or producer exclusion is claimed. Module code was unchanged; previous full project tests were not rerun.

Next verify EP0 disable's request retirement and admission exclusion before removing descriptor/route hooks. E0182 remains the module candidate; combined PC Remote+UVC/PTP test is not ready. Camera remains appropriate in Mass Storage.
