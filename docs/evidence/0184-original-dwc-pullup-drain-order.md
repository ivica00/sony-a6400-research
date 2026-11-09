# E0184 — Original DWC pullup wait and teardown order

## Scope and source

Offline execution of original a6400 `dwc3_gadget_pullup` at `0x602b1d3c`, using the retained kernel SHA-256 `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707`. No camera access, upload, mode change, hook publication or module change occurred.

## Verified original decisions

For disable, the function saves the previous `dwc+0x170` value and clears that field under `dwc+0x70` lock. It obtains the busy object through `*(dwc+0xcc)` and tests bit 0 at object+0x10. While busy, it unlocks, enables migration, calls `__cond_resched`, disables migration, relocks and retries. There is no retry counter or deadline in this original loop.

Only after the busy bit clears does original code call:

1. `stop_active_transfers` at `0x602b04f4`;
2. endpoint disable `0x602b1a3c` for `dwc+0xd0` and `dwc+0xd4`;
3. disconnect notification `0x602af150` when the saved `+0x170` was nonzero;
4. run/stop `0x602aeffc` with enable=0.

The run/stop result is returned after unlock/migration restore. A failure is not a rollback of the preceding calls. Enable skips the busy wait and these disable operations, calling run/stop with enable=1.

## Executed probe

`tools/research/probe_uvc_ptp_pullup_drain.py` executes original instructions `0x602b1d3c..0x602b1df4`. Six passing cases cover idle disable, connected disable, busy clearing after three scheduler yields, persistent busy, run/stop error -110 and enable. Each checks argument identities, teardown order and return behavior. Disable cases also check the original clear of `+0x170`.

Hardware operations, disconnect notification, locking and scheduling are explicit service doubles. The persistent-busy case is stopped after 20 yields by the harness; this is deliberately **not** reported as a native timeout. Its trace contains no stop-transfers, endpoint-disable or run/stop call before that observation boundary.

```
python -m tools.research.probe_uvc_ptp_pullup_drain --output-dir artifacts/analysis/uvc-ptp-pullup-drain-e0184
```

Manifest: `artifacts/analysis/uvc-ptp-pullup-drain-e0184/manifest.json`. The existing module was not changed, and the previous 605-test result was not rerun for this isolated research tool.

## Consequence for activation design

Do not hold all Sony userspace threads stopped while invoking native pullup(0): the original path yields while waiting for another actor, whose progress has not been proven independent of those threads. The CPU barrier is for route publication, with Sony threads resumed before USB teardown. A host timeout alone cannot safely cancel a kernel call already in this loop or justify unloading its caller.

This probe verifies control flow, not endpoint completion or callback lifetime. Safe publication/unpublication still needs complete owner/thread coverage and module self-pin lifetime. EP0/IRQ/DMA drain and the identity/producer of the busy bit remain open. Combined PC Remote+UVC/PTP activation is still not ready; camera should remain in Mass Storage pending the controlled test.
