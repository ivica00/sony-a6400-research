# E0217 — Original USB event producer and DWC dequeue

Date: 2026-11-09. Offline research only; no camera access, upload or module changes.

## USB event producer

New `probe_uvc_ptp_event_queue.py` executes original `usb_event_add_queue`602b5c14, context lookup602b57b0 and ring writer602b5b10 from the pinned a6400 kernel. Six cases pass: normal STOP-shaped event,8-byte payload spanning ring end, full queue, unregistered context, disabled producer and invalid callback.

- Valid event serializes context/callback/subtype/payload-length, alignment and payload; original producer then updates notification count and wakes its waitqueue.
- Full queue returns -105, restores the used cursor, increments overflow count, and does not wake. Partial bytes/high-water bookkeeping may already have changed: cursor rollback is not byte-atomic rollback.
- Unknown context returns0 **without inserting an event**, while incrementing notification count and waking. Thus result0/notification/wakeup alone is not proof an application STOP event was delivered.
- Disabled producer returns0 without insertion/wakeup. Invalid zero callback returns-22.

There is no producer branch that waits for the consumer to free queue capacity in these original bodies; saturation returns an error. Real spinlock acquisition and waitqueue wake remain service boundaries, so this is not a general nonblocking or deadlock-freedom proof.

Artifacts: `artifacts/analysis/uvc-ptp-event-queue-e0217/manifest.json`. Division, memory-copy, spinlock/migration and wake are explicit service doubles; registry/ring/globals are fixtures. No actual consumer or user callback executes.

## DWC dequeue and synchronous giveback

New `probe_uvc_ptp_dwc_dequeue.py` executes original `dwc3_gadget_ep_dequeue`602b053c and giveback602affb8. Four cases pass: missing, pending, active, previously failed request.

- Missing returns-22 and produces no completion.
- Pending request is removed and completed synchronously without hardware transfer-stop call.
- Active request invokes original transfer-stop boundary602b03d8 before giveback.
- Giveback changes an in-progress -115 status to -104 for dequeue, preserving a prior -5 error. This differs from endpoint-disable shutdown status -108.
- Completion runs after DWC lock/migration release; original code reacquires them before returning. Ownership field is cleared before completion.

Artifacts: `artifacts/analysis/uvc-ptp-dwc-dequeue-e0217/manifest.json`. Hardware stop, DMA unmap, locking/migration and final completion are explicit recorders. These fixtures do not prove DMA stopped, callback scheduling, concurrent list safety or complete PTP STOP. E0216 separately executes the original PTP read completion through a deliberately synchronous service fixture; these reports are complementary, not one physically observed end-to-end trace.

## Remaining boundary

Static inspection of602b03d8 shows a nonzero resource-index path that invokes endpoint command602b0220 and then a delay helper60257f04 before clearing the native transfer bookkeeping. Neither command/MMIO behavior nor delay was executed by the dequeue probe. These and actual lock contention remain open investigation targets, not identified E0210 hang sites.

No evidence here establishes whether E0210 froze while negotiating UVC controls, disconnecting hardware, stopping PTP, or later. E0212 control rejection and E0215 runner permission check remain offline. Next: execute endpoint-command completion/timeout contracts and prepare recoverable observation before another configured physical session. Camera last verified recovered MSC. The general suite was not rerun for the isolated research scripts; last612passing result remains E0215.
