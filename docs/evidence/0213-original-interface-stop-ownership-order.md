# E0213 — Original interface STOP ownership order

Date: 2026-11-09. Offline only; no camera access, upload or activation.

`tools/research/probe_uvc_ptp_interface_stop.py` executes original a6400 `0x602b8f8c` from the verified kernel, with explicit registry and ordinary PC Remote GCW-state fixtures. Four cases pass: active matching interface, inactive record, other interface, other configuration.

For an active match, the original code clears registry record+0x14 at `0x602b901c` **before** invoking descriptor STOP at `0x602b9024`. Only after the callback returns does it release each endpoint wrapper, free the endpoint-pointer list, then disable endpoints belonging to the interface. The callback is void: its residual return register is ignored. A record whose active flag is already clear skips that callback and list-release sequence.

This is an important recovery limitation: an inactive registry flag alone does not prove callback completion, and a retry cannot infer that the previous callback returned. Combined with E0211, zero configuration or cleared activity must not substitute for a successful complete teardown receipt. This does not identify the E0210 hang site.

Manifest: `artifacts/analysis/uvc-ptp-interface-stop-e0213/manifest.json`. Callback, endpoint release, allocation free and hardware-disable services are recorders; no real PTP/video callback body runs. GCW states 5/6, wildcard fallback drivers, endpoint-list lifetime under concurrency and physical teardown are not covered. No firmware behavior is synthesized beyond the documented fixture/service boundaries.

E0212's OBS finding and enumeration-only CLASS/VENDOR rejection remain relevant independent work. No new physical test was attempted. Next: inspect actual registered PTP/video STOP callback bodies and provide an observation path that survives a failed session, then review runner failure handling. Do not implement timeout-driven unload or skip native teardown based only on these flags.
