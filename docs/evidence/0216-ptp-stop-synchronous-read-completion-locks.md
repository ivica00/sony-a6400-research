# E0216 — PTP STOP through synchronous read completion

Date: 2026-11-09. Offline only, no camera access, upload or activation.

## Executed chain

Expanded the identity-pinned E0214 probe with `--completion-chain`. It now executes original a6400 PTP STOP, `sicd_ep_dequeue_all`, `sicd_ep_dequeue`, `sicd_data_read_comp`, `sicd_request_stop`, `sicd_set_requesting_flag` and `sicd_call_user_cb`. Text-local and BSS relocations needed by these functions are applied against explicit test mappings. The endpoint dequeue service deliberately invokes the original read completion synchronously, with one pending OUT request and two idle endpoints.

Mutex services record a set of held lock addresses and reject recursive acquisition or unmatched unlock. They do not implement kernel locking/scheduling. Under this scenario:

- STOP holds extended-context mutex +0x258.
- Dequeue inspects the pending request under +0x2a0 and unlocks it **before** invoking the endpoint dequeue service.
- Synchronous read completion, entered while +0x258 remains held, clears the requesting flag using +0x2a0, then uses +0x270 for the cancelled-read state.
- It releases these locks and submits a completion event before STOP frees its requests and submits the separate STOP event. All recorded locks are released by return.

This rejects a narrow hypothesis that this particular original synchronous-read-completion path directly reacquires STOP's +0x258 or enters completion while its own +0x2a0 remains held. It does not prove absence of cross-thread deadlock, other lock cycles, queue blocking, hardware waits or the cause of E0210.

## Cases and boundaries

Four chain cases pass: normal/cancelled read state crossed with event enqueue 0/-12. Tests assert requesting and cancellation fields cleared, correct normal/cancelled completion event subtype, byte-equal error/length payload (512, -108), completion before free before STOP event, and request-free order. Original E0214's two isolated cases also still pass.

Receipts: `artifacts/analysis/uvc-ptp-completion-locks-e0216/manifest.json`. Tool: `tools/research/probe_uvc_ptp_stillimage_stop.py --completion-chain`. Module identity remains `d4843c6abac908881ef5a96fd570fb345f766fff9ee562413f5f63e9cc7e0ff9`.

The endpoint dequeue service, getters/endpoint-info lookup, mutexes, free, status, zeroing and event enqueue are explicit fixtures/recorders. The completion is original code but its invocation timing is a deliberately selected scenario, not observed physical DWC behavior. No actual kernel locking, IRQ/DMA drain, queue implementation or userspace consumption runs. There is no write-completion, interrupt-endpoint completion, special GCW state or multi-thread proof. Last full project suite is E0215's 612 passing tests; this isolated tool step reran the six affected original-code cases only.

## Next

Remaining diagnostic boundaries are actual DWC dequeue/completion and USB event queue behavior plus an observation path that survives losing the USB gadget. The debugger supports Sony MSC/MTP extension transports in principle, but neither is independent of a disconnected gadget; it must not be called a recovery channel without physical proof. E0212 enumeration-control rejection and E0215 STOP receipt handling remain offline. Do not repeat configured activation merely because this scenario passes. Camera last verified recovered MSC.
