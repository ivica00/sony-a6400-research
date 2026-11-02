# UIPC blocking receive and sender wake integration

Date: 2026-10-24

## Contract and implementation

Under the explicit `threads` policy, an empty indefinitely waiting UIPC receive
(`ioctl 0x80000007`, timeout `0xffffffff`) returns `None` from the existing queue
model. The interpreter now saves the caller's complete register context, sets its
saved PC to the SVC instruction (`pc - size`), registers the queue wait through
`handle_uipc_wait`, and restores the next runnable thread including TLS.
No receive result or output pointer is supplied while blocked. If no runnable
thread exists, execution stops with `blocked_uipc`.

After a successful asynchronous send (`ioctl 0x80000004`), the interpreter calls
`handle_uipc_wake` for the destination queue and records the awakened thread IDs.
The awakened receiver repeats the original SVC with its original fd, command and
argument pointer. The existing UIPC queue model owns dequeue and output-pointer
delivery. This applies to every thread, without a special case for TID 1007.
Finite receive timeouts and unsupported commands retain their existing behavior.

## Validation

`test_blocked_receive_retries_svc_after_sender_wakes_it` executes a constructed
ARM instruction fixture with two threads. The receiver blocks, the sender queues
a message and wakes it, the sender exits, and the receiver repeats its SVC and
receives the exact queued pointer. This verifies the interpreter integration,
not only the scheduler helpers.

The same integration test also runs as Thumb code to verify the two-byte SVC
retry address, rather than only the four-byte ARM instruction path.

Full regression suite: **400 tests passed**. Retained output:
`artifacts/execution/uipc-wait-wake-final-suite.txt`.

## Firmware experiment definition

The requested `plan_gui_rendering.md` was not present in the project. The retained
`artifacts/execution/ui-boot-dynfix.json` reports 80,830,480 instructions but stops
at syscall 268 (`tgkill`), rather than a resumable queue wait. Its recorded boot
stimulus includes three injected experimental messages. It is not a saved CPU/RAM
checkpoint. The new run starts from original process entry with a 150,000,000
instruction budget and no injected queue messages:

```powershell
.\venv\Scripts\python.exe -m tools.research.experiment_ui_boot --instructions 150000000 --timeout-us 3600000000 --argument i --stimulus none --madvise-dontneed --urandom-open --urandom-entropy deterministic --tmp-overlay experimental-empty --stream-device image-driver --regular-inode-rdev --readonly-image-times --backup-service preset-backed --graphics-service authentic-grm --null-page read-zero --proc-overlay experimental-empty --report artifacts/execution/ui-boot-uipc-wait-wake-150m-entropy-open.json
```

The selected existing service policies and experimental process inputs remain
limitations of this user-space experiment. The `authentic-grm` option name is not
independent proof of full service or camera fidelity. The framebuffer model's
default geometry, pixel format and physical address remain unverified. A mapped
buffer or framebuffer ioctl alone cannot establish authentic rendered pixels.
No card writes or updater execution are part of this experiment.

The first launch omitted `--urandom-open` and stopped at 41,781,060 instructions
while opening `/dev/urandom` (`runtime_namespace_not_supplied`, prefix `/dev`).
That report is retained separately as
`artifacts/execution/ui-boot-uipc-wait-wake-150m.json`. No runtime namespace guard
was changed; the corrected command above explicitly enables the existing node
contract as well as the deterministic entropy policy.

## Firmware result

The corrected run stopped at **80,737,298 instructions**, before the requested
150,000,000 budget, with `unsupported_uipc_contract`:

- Reason: `unsupported_backup_operation`, operation **30** (`0x1e`).
- Request words: `[30, 0, 3, 4063565, 0, 0, 24117248, 1376191004, 4]`.
- PC: `1344909436`; ioctl: `0x80000005`; argument pointer: `1400171360`.
- Eight thread descriptors exist. Without injected events, `grm_dn_vdf_if` is
  **TID 1005**, not TID 1007. It reaches an empty blocking receive on queue
  **0x0080003b** and switches to TID 1003, with state `blocked_uipc`.
- The wait event records the ARM SVC retry address `1344909432` (`pc - 4`).
- No sender wake event occurs before the next unsupported contract. Actual
  send/wake/retry delivery is verified by the ARM and Thumb integration fixtures,
  not claimed as an observed firmware drawing command.
- Framebuffer transactions: **0**. VRAM base: **null**. No image was exported as
  `artifacts/reports/gui_first_frame.png`; no pixel bytes were available.

Report: `artifacts/execution/ui-boot-uipc-wait-wake-150m-entropy-open.json`.
SHA-256: `b80baa6161e8d253d2f39be4f86c12db96cfa2b64ab0b67445cd881dc86ae4ca`.
Console output: matching `.txt` file.

The blocking scheduler integration is implemented and tested. The first-frame
objective remains blocked by the next unimplemented backup contract and any
subsequent renderer/display prerequisites. Resolve operation 30 from original
firmware evidence and its actual required state before advancing; do not replace
it with a generic acknowledgement. No full-kernel, camera display or SD-to-GUI
compatibility claim follows from this process run.

