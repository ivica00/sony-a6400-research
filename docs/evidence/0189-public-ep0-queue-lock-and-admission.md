# E0189 — Public EP0 queue lock and admission

Offline original kernel execution, SHA-256 `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707`. No camera access or module changes.

Original public `dwc3_gadget_ep0_queue` at `0x602b2ad0` disables migration and locks dwc+0x70 before examining endpoint descriptor +0x1c, pending-list head +0x24 and calling internal queue at `0x602b26ec`. All exits unlock and restore migration. Missing descriptor returns -108, occupied pending list returns -16, and a valid empty endpoint reaches the internal admission test. The internal queue checks dwc+0x170 under this same lock. Original pullup(0) clears that field under dwc+0x70 (E0184).

Therefore public queue admission and the original pullup admission-field clear use the same native lock. A queue entering after the clear rejects before request mutation. A request accepted before the clear is subject to the later cleanup path. This is a control-flow/locking contract, not proof of hardware completion or coverage of every possible internal caller. Cleanup callbacks still temporarily release the lock; admission remains closed unless another actor changes dwc+0x170, which must be excluded by the native mode guard before activation.

Extended `tools/research/probe_uvc_ptp_request_retirement.py` passes **11 cases**: seven previous retirement/EP0 disable cases and four public queue cases (disabled, occupied, admission closed, admitted). New cases execute public and internal original bodies together, verify lock/migration ordering and status, byte-equal request state on rejection, and real list insertion/status -115 on admission. No internal-queue result double is used.

```
python -m tools.research.probe_uvc_ptp_request_retirement --output-dir artifacts/analysis/uvc-ptp-public-queue-e0189
```

Manifest: `artifacts/analysis/uvc-ptp-public-queue-e0189/manifest.json`. Locks/migration and hardware/completion operations remain doubles. The admitted case selects an ordinary idle software state and queues without starting a hardware transfer. No concurrent scheduler execution, physical DMA or direct-internal-caller exclusion is claimed. Module code unchanged; full project tests not rerun.

The remaining activation gap is now primarily composition: safely publish the native ioctl wrapper while existing Sony callers are stopped, retain module ownership across publication and all callbacks, resume Sony threads before pullup, and retire the wrapper only after original route restoration and caller drain. Existing E0182 route equality alone is insufficient. No publication ioctl is implemented yet and combined PC Remote+UVC/PTP test remains not ready; camera should remain MSC.
