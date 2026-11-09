# E0211 — Configured-session teardown boundary and stage diagnostics

Date: 2026-11-09. Offline work only; camera remains recovered in MSC. No module uploaded or loaded in this step.

## Verified original control flow

New probe `tools/research/probe_uvc_ptp_unconfigure.py` executes the original Sony clear-configuration function `0x602b90cc` from the SHA-verified kernel. Four cases pass:

- Configuration 0 returns immediately, with no interface teardown or hardware reset.
- Configuration 1 resolves the current tree, prepares stop, invokes interface stops 0/1/2, clears configuration and alternate bookkeeping, then requests hardware reset.
- A failing interface stop returns -1 early, leaves configuration 1, and skips later interface stops/reset.
- Hardware failure occurs after bookkeeping is already cleared and is normalized to -1; zero configuration alone therefore does not establish successful teardown.

Configuration lookup, stop preparation, per-interface stop and hardware reset are explicit service doubles. This proves the original branch ordering, not the behavior of real PTP/UVC callbacks or physical hardware. Manifest: `artifacts/analysis/uvc-ptp-unconfigure-e0211/manifest.json`.

This is a material coverage gap between E0208/E0209 (sampled configuration 0) and E0210 (healthy configured Windows children). Earlier unconfigured STOP success does not verify configured-session teardown. E0210's exact freeze site remains unknown because the receipt was not retrieved before recovery by restart.

## Diagnostics prepared

With optional trace-control enabled, the existing native backend now logs before/after original pullup(0), its return/configuration, and before/after native disconnect. Dispatch and teardown ordering are unchanged; no new kernel hook or speculative timeout was added. The original pullup busy loop remains unbounded (E0184). These diagnostics require a way to recover logs if the camera stalls; they alone do not make another physical test ready.

Offline candidate: `artifacts/native/uvc-ptp-module-e0211/usbg_video_a6400_shared_candidate.ko`, 72428 bytes, SHA-256 `3701a6f9297460ed6c4382c3f4ecd814d4481fd8b98d8443bb18f2eeea8fc533`. Compiled module audit: 118 checks pass; 55 imports verified. This binary is not physically tested. The last full general suite remains E0210's 612 passing tests; the isolated new ARM probe and module audit cover this step.

## Outstanding work

Trace actual interface-stop/disconnect callback contracts, especially PTP ownership and callback completion after active configuration. Review the runner's failure path: a failed STOP currently logs a warning then proceeds toward hook retirement, and close may retry cleanup. Do not treat that sequence or a host elapsed-time window as evidence of successful session retirement. Stage logs also need a recoverable observation path before a further configured-session test. Do not unload a possibly executing/pinned module or bypass the native busy loop to manufacture a successful STOP.

No change to sensor feeder, no PTP control transactions and no new physical activation occurred.
