# E0194 — Physical kernel stop sites during CPU barrier

## Result

Extended the actual CPU capture helper to read `/proc/149/task/<tid>/wchan` immediately after each successful GETREGS while the same all-thread CPU barrier remains held. Output is emitted only after resume. Reads use existing Sony libc open/read/close and remain subject to the helper's 2000ms capture deadline. Every failure still reaches resume before reporting.

New probe: `artifacts/native/uvc-ptp-freeze-e0194/native_usb_freeze_probe.elf`, **7044 bytes**, SHA-256 `c52dead0682c612340ddc2cee4654571dfea3dccb7123b36c271a2206e5799c3`. Built with warnings as errors and physically uploaded/readback verified. One physical capture produced **174 attached, 174 resumed, 1076ms, result0**, exact fresh TID-set match, **174/174 wchan=ptrace_stop**, and TracerPid0 after capture. Debugger PID703 remained responsive. No module, hook or USB mode change; payload/log writes only unique `/tmp_bt` files, retained there.

Receipt: `artifacts/hardware/uvc-ptp-kernel-stop-e0194/manifest.json` and its `freeze.log`, status-before/after and debugger receipts. CPU capture runner now accepts an artifact build directory, verifies binary length/hash against its build manifest before push, and validates stop-record TID coverage when present. The earlier E0192 binary remains supported by its own build manifest.

## Original kernel investigation

Hash-verified retained kernel identifies ptrace_stop=`0x6014266c`, ptrace_notify=`0x60143710`, do_signal=`0x601102e8`, get_signal_to_deliver=`0x601437d8`. Original ptrace_stop writes task state 0x88 before its notification/scheduling path. Original do_signal checks saved CPSR low bits at regs+0x40 (`0x601102f8..108`) and returns immediately for nonzero low mode bits. The signal-delivery call at `0x60143948` is one of multiple original direct ptrace_stop call sites; observing the wchan symbol alone does not identify the exact caller.

The physical wchan observation is therefore stronger than saved user registers alone, but it is **not a kernel stack unwind**, a proof that all previous VFS callbacks returned, or evidence of IRQ/DMA completion. No new publication authorization is inferred from it.

## Remaining work

Need concretely attest route-publication callers/stop provenance and prevent new native owners before linking the route lease to native fops. E0191 recovery providers remain offline fixtures, and E0182 remains the shared module candidate. This step changes only helper/runner code, so module tests were not rerun; camera helper build and physical capture are the relevant checks. Combined PC Remote+UVC/PTP test is not ready. Camera remains in Mass Storage.
