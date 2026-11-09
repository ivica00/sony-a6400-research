# E0191 — HELD recovery after partial caller resume

Extended the offline MOD `uvc_ptp_route_lease.{c,h}` with `a6400_route_recover`. No camera access, kernel slot write or shared-module integration. E0182 remains the module candidate.

Recovery requires HELD state, a retained pin and an explicit `barrier_recover` provider. It **always rebuilds complete caller quiescence**, rather than trusting barrier_held after a failed leave: some callers might already have resumed. It then checks retirable, compares the current route, restores an owned wrapper atomically and releases the barrier before unpinning. An already-restored original route is accepted only inside that rebuilt barrier and after retirable approval. Failure keeps the pin and HELD state for retry.

Added a separate published ownership bit. Pointer equality alone cannot authorize removal of a wrapper that this lease never published. Foreign targets and an unexpected/unowned equal wrapper remain untouched. No recovery provider returns -95 without unpinning. Normal publication refuses stale ownership state; normal retirement requires publication ownership.

## Validation

Expanded `check_uvc_ptp_route_lease.py` executes actual compiled ARM policy and C fixtures in Unicorn. Existing E0190 scenarios still pass. New assertions cover partial caller resume after failed leave, barrier-recovery failure, busy recovery/retry, successful recovery followed by a new publish/retire cycle, recovery after original route already restored, refusing unowned wrapper/foreign route, missing provider and repeated leave failure. The partial-resume fixture deliberately has lease.barrier_held=1 while its caller state is running; recovery must call the new provider to re-establish the barrier.

The fixture now supplies a freestanding memset because the expanded struct initializer caused a compiler-generated reference. Assertion failure is marked noinline so the emulator catches it by symbol instead of relying on its instruction budget. All assertions pass, and separate ARM object compilation passes warnings-as-errors.

```
python -m tools.research.check_uvc_ptp_route_lease --output-dir artifacts/analysis/uvc-ptp-route-recovery-e0191
```

Manifest: `artifacts/analysis/uvc-ptp-route-recovery-e0191/manifest.json`.

Barrier/pin/retirable providers are explicit fixtures, not real camera operations. Concurrent CAS interference, actual owner discovery, ptrace recovery, IRQ/DMA and physical publication remain unproven. No module code was changed and full project tests were not rerun. Next implement a concrete barrier provider with complete owner coverage and partial-stop recovery before module integration. Combined PC Remote+UVC/PTP test remains not ready; leave camera in Mass Storage.
