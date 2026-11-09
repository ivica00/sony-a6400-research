# E0190 — Route publication code lifetime policy

Implemented `tools/native_camera/uvc_ptp_route_lease.{c,h}` as an **offline MOD policy**, not an installed kernel hook. No camera access or shared-module integration occurred. E0182 remains the actual shared candidate.

Publication pins code before entering the caller barrier and atomically compares the slot's expected original target before replacing it. A foreign target, including an unexpected already-equal wrapper, enters HELD and retains the pin rather than inferring ownership from pointer equality. Barrier-release failure also retains the pin and HELD state.

Retirement enters the caller barrier and requires a separate retirable callback before atomically restoring the original target. The pin is released only after route restoration and successful barrier release. Busy sessions leave the published route pinned and allow a later retry. Foreign replacement and barrier-release failure retain ownership. Successful publish/retire can repeat. HELD recovery is deliberately not implemented yet; it cannot be silently reset or unloaded.

The policy caller must serialize operations. Its supplied barrier must cover **all** possible cached route targets/callers, not merely guard count or saved userspace registers. Failed barrier entry must clean up its own partial stops; failed release requires external recovery. The retirable callback must exclude live session/descriptor hooks, callbacks and guard reservations. These are explicit provider contracts; this change does not supply or prove them physically.

## Validation

`tools/research/check_uvc_ptp_route_lease.py` builds a freestanding ARM executable containing the actual policy and explicit C barrier/pin fixtures, then executes it with Unicorn. Fixtures cover null/invalid operation, full publish/retire and repeat cycle, double publication, busy retirement/retry, pin failure, barrier-entry failures, foreign route on publication and retirement, unexpected wrapper equality and barrier-release failures before/after restoration. The fixture asserts the pin remains held whenever required and unpin occurs only outside the barrier. All assertions pass. A separate ARM object also builds with warnings as errors.

```
python -m tools.research.check_uvc_ptp_route_lease --output-dir artifacts/analysis/uvc-ptp-route-lease-e0190
```

Manifest: `artifacts/analysis/uvc-ptp-route-lease-e0190/manifest.json`. Policy code is new MOD code, not original Sony behavior. Slot and barrier are fixtures. No native fops address is written. The initial host-gcc attempt was unavailable in WSL; final validation builds and executes ARM directly. The shared module and its prior full test results are unchanged; the full suite was not rerun for this unintegrated policy.

Next implement/validate the concrete caller-barrier provider and HELD recovery before wiring this lease into the module or exposing publication ioctls. Physical PC Remote+UVC/PTP test remains not ready; leave camera in Mass Storage.
