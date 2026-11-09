# E0214 — Original PTP STOP and application-event adapter

Date: 2026-11-09. Offline only, no physical camera access or module changes.

## Original module identity and executed scope

Located a6400 PTP implementation in `usbg_stillimage.ko`, SHA-256 `d4843c6abac908881ef5a96fd570fb345f766fff9ee562413f5f63e9cc7e0ff9`. New probe `tools/research/probe_uvc_ptp_stillimage_stop.py` pins that identity, executes original `core_cb_stop` (.text+0xaa4) and its original `sicd_call_user_cb` (.text+0x270). Text-local absolute jump-table relocations are applied for the test load base; external calls are explicit recorders. No relocated call is silently treated as original kernel execution.

Two cases pass with event enqueue result 0 and -12. Both reach original STOP return. This establishes callback ordering and error propagation limits under the stated service fixtures, not successful hardware teardown.

## Observed order

1. Acquire extended-context mutex +0x258.
2. Dequeue outstanding endpoints via `sicd_ep_dequeue_all` (recorder in this probe).
3. Free requests for endpoint list entries 1, 0, 2, with request fields +0x20, +0x18, +0x28 respectively.
4. Clear 24 bytes at extended context +0x14 and clear endpoint list.
5. Release mutex +0x258.
6. Acquire mutex +0x288, set status 0x2019, release it.
7. Invoke original event adapter with event selector 1 and zero payload arguments. It selects the stored callback identifier at context+8 and calls `usb_event_add_queue` with `[0, callback_id, context_word0, 0, 0, 0]`.

The callback body contains no direct wait for application acknowledgement after enqueue. This does not prove queue implementation is nonblocking: its body is a recorder here. A negative enqueue result is not checked by STOP. Mutex acquisition, request dequeue/completion and freeing remain possible blocking/service boundaries, not established causes of E0210.

Static inspection of `sicd_ep_dequeue` shows a separate mutex +0x2a0 and unlock before calling endpoint dequeue. It does not by itself prove freedom from lock cycles. Reference UVC STOP also takes mutexes and performs dequeue/free; enumeration-only START suppression prevents the bridge from marking a stream started, but actual callback selection under every event remains to be verified. Do not attribute E0210 solely to PTP or video STOP.

## Artifacts and limits

`artifacts/analysis/uvc-ptp-stillimage-stop-e0214/manifest.json` contains both executed receipts. `callback-relocations.json` records static call relocation metadata for original PTP/UVC STOP and selected completion helpers, with module hashes.

Getters, mutexes, dequeue, free, status, zeroing and event enqueue are explicit service recorders. No real request completion, lock contention, user-event consumption, complete configured teardown, sensor or camera-control behavior is proven. The probe records callback order, not firmware compatibility of replaced services. The general suite was not rerun for this isolated research tool; last full result remains E0212's 612 passing tests.

Next: complete callback/lock interaction tracing, improve runner STOP-failure handling and establish a recoverable diagnostic channel before any further configured-session activation. E0212's explicit rejection of host video controls is still offline and not a proven freeze fix. Camera last verified recovered MSC.
