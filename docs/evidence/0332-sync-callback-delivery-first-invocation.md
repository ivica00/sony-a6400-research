# E0332 — Opt-in kernel-originated delivery to sync-registered callbacks (first original callback invocation)

Date: 2026-11-11. Emulator-only work; no camera access, no camera write, no USB
mode change. Continues E0328–E0331 and issue #4.

## 1. Implementation

New opt-in policy for the UIPC model:

- `GuestUipc(sync_callback_delivery_policy=...)`, values `unmodelled` (default)
  and `kernel-origin`.
- `--uipc-sync-callback-delivery unmodelled|kernel-origin` in
  `tools/research/experiment_ui_boot.py`; applied to the restored UIPC subsystem
  *after* `restore_checkpoint` (restore replaces the object, which previously
  swallowed the policy).
- `GuestUipc.callback_ready()` reports pending `flags=1` sync registrations as
  ready only under `kernel-origin`.
- `GuestUipc.handle_wait_cb()` under `kernel-origin` on the original proxy path:
  - delivers the pending message to a `flags=1` registration by writing the
    original four-word tuple `(callback, user_data, msg, index)` and the active
    marker `0x80` in the OSAL message header flag byte (`msg-7`);
  - on the proxy's completion pass, verifies identity/queue/registration,
    clears the marker and records `wait_cb_sync_completion`.
- Default behavior is unchanged: `unmodelled` still raises
  `uipc_sync_callback_not_implemented` for legacy policies and never consumes a
  sync registration on the async path.

Tests: `tests/test_sync_callback_delivery.py` (delivery tuple and header marker,
completion, guard on changed registration, unknown policy rejection, readiness
gating). Full suite: **957 tests OK**.

## 2. Experiment e0684

Base: `boot-e0673-live-full2e.ckpt` (557,079,079, service-idle, `kernel-e0301`).
Flags: `--uipc-sync-callback-delivery kernel-origin`,
`--uipc-inject-objmsg-setconfig-queue 0x00CA0288`, budget 660,000,000.

Observed:

- Injection at 557,079,079: ledger `woken=[1001,1002,1003,1006]` (all four UIPC
  proxies woke, unlike E0331 where `woken=[]`).
- Queue 0x00CA0288 pending list drained: the message was consumed.
- UIPC transactions for the injected message:
  - `wait_cb_sync_delivery`: proxy 0, tid 1001, handle **4109**,
    callback 1447342303, user_data 1447422616, msg 1346059500, mode
    `kernel_sync`;
  - `wait_cb_sync_completion`: same handle/msg, header marker cleared.
- The run continued to 674,711,163 (`instruction_budget_exhausted`),
  `boundary = null`.
- End state: UsbControl still `blocked_futex` (0x10FFED3C), no local queue
  0x00CA8192 message observed in the emulator ledger, no FSM transition claimed.

Interpretation: the **original guest sync callback h4109 executed and completed**
through the emulated kernel-originated delivery path. The callback did not post a
message that reaches UsbControl's local queue in a way this model observes, so
the callback's expected input/format is the next boundary. The injected envelope
was the evidence-derived ObjMsg image (word0 = ObjMsg pointer); the real sync
packet layout for h4109 is not yet decoded.

## 3. Boundary and next step

Boundary: **`sync_callback_packet_format_unmodelled`** — h4109/h4110 callback
argument/packet semantics are unknown; the delivery transport itself works.

Next:
1. Decode callback pointers 1447342303 (h4109, live libUsbControl) and
   1447373447 (h4110) to learn the expected packet fields and the downstream
   post path (likely into local queue 0x00CA8192).
2. Re-run delivery with the decoded packet fields, then instrument
   `UsbControl::ProcessMsg` / `MsgId2EventId` / FSM dispatch to observe event
   `0x13`.
3. Keep default `unmodelled` and the fail-closed guards intact.

## 4. Reproduction

```
.\venv\Scripts\python.exe artifacts\analysis\e0684-run-live-synccb3.py
```

Report: `artifacts/execution/e0684-live-synccb3.json`;
checkpoint: `artifacts/checkpoints/boot-e0684-live-synccb3.ckpt`.
