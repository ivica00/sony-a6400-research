# E0251 — Opt-in end-path unconfigure-first candidate built offline

Date: 2026-11-09. Offline build only: no camera access, no module load. Follow-up to E0250.

## Change

- `uvc_ptp_session.h`: optional `unconfigure` op added to `a6400_uvc_ptp_ops` (end-path only; not used by session begin).
- `uvc_ptp_native_backend.c`: `unconfigure(gc)` validates the live gc and a nonzero configuration byte, then calls the original clear-configuration `0x602b90cc`; the backend initializer publishes it in `ops->unconfigure`.
- `uvc_ptp_session.c`: under `A6400_UVC_TEARDOWN_UNCONFIGURE_FIRST`, `session_end` calls `ops.unconfigure(gc)` **before** `ops.quiesce(gc)`; a failure holds the session.
- `build_uvc_composite_module.py`: new `--teardown-unconfigure-first` flag (requires the shared enumeration candidate) adds the macro.

## Build result

- `artifacts/native/uvc-ptp-module-e0251/usbg_video_a6400_shared_candidate.ko`, **72,712 B**, SHA-256 `383ea3b880063461dc0bc92d0a1235f253b457562da3bb6711085746f65aae28`.
- 3 executable sections prefix-match the reference with the two documented patches; **55 undefined symbols** all verified; GPL-only imports none; `a6400_uvc_ptp_session_end` and `a6400_uvc_ptp_native_backend_init` are defined.
- Compiled order confirmed by disassembly:
  - `a6400_uvc_ptp_session_end`: loads `ops.unconfigure` at session+`0x2c`, calls it, then loads `ops.quiesce` at `0x28` and calls it.
  - backend `unconfigure`: `movw/movt 0x602b90cc; bx r3`.
- Manifest: `artifacts/native/uvc-ptp-module-e0251/manifest.json`.

## Limits and open risk

The build tool's step 5 (Unicorn under WSL) cannot run in this environment. The module audit was therefore run through a new prebuilt-fixture path: `audit_uvc_ptp_module.py --prepare-only` writes the exact gcc/ld commands, the fixture is compiled and linked with direct WSL, and the audit is rerun with `--linked-elf`. Result: **118/118 checks pass**, `offline_module_audit_passed`, module SHA-256 matches `383ea3b8…` (`artifacts/analysis/uvc-ptp-module-e0251/manifest.json`). This closes the earlier audit gap.

The candidate is **not deployed or physically tested**. The key open question is the state after `unconfigure`: `session_end` later calls `resume`, which returns `-16` unless the backend's `stopped()` check (config byte 0 and original `0x602bd450()` returning 1) holds. `quiesce` still runs pullup(0) after unconfigure, so the state may become 1 as before, but this is unproven. If `resume` fails or the gadget still does not return to Mass Storage, the session holds (runner RETAINED); candidates B/C from E0250 remain fallbacks.

## Next

F4 (user-gated): a short session with this candidate, the host USB monitor and the strict runner policy. If `resume` fails or the gadget still does not return to MSC, record the stage and fall back to interface-stop-before-pullup or no-custom-pullup.
