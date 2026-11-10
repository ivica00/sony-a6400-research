# E0247 — P4a module load/unload smoke test: e0212 clean in Mass Storage

Date: 2026-11-09. Physical, bounded: one module load and unload in Mass Storage. No INIT, no PC Remote switch, no UVC session, no SD write.

## Setup

- Module: `artifacts/native/uvc-ptp-module-e0212/usbg_video_a6400_shared_candidate.ko`, 72,512 B, SHA-256 `1bcb464842e8d478a8735be46161689f6d3e8c280c6b048bd94a2687f9e33b23`, upload read-back verified.
- Tool: `tools/research/run_p4a_module_smoke.py`; owned `/tmp_bt/p4a_<stamp>.ko` and `p4a_<stamp>.klog` only.

## Receipts

- Preflight (read-only): MSC, uptime 5539.41 s, `TracerPid: 0`, `usbg_video` absent; module list saved as the byte baseline.
- `insmod`: status 0; `usbg_video` visible in `/proc/modules`.
- `dmesg` after load: 5,135 B captured, no `Oops`, `BUG:`, `Unable to handle kernel`, `Kernel panic` or `Internal error`; the retained ring contains only early boot messages, not the module's own init lines.
- `rmmod usbg_video`: status 0; `/proc/modules` **byte-equal to the preflight baseline**; `usbg_video` absent.
- `dmesg` after unload: no oops markers.
- Uptime after: 5543.63 s (+4.22 s, monotonic) → **no reboot**.
- `TracerPid: 0` after; `/tmp_bt` listing shows none of the owned files left.

## Interpretation

The current e0212 enumeration candidate loads and unloads cleanly in Mass Storage on the running firmware: the module becomes visible, unload restores the exact module list, and the retained dmesg shows no oops. This is the intended P4a gate before any PC Remote enumeration session.

## Limits

No INIT, no gadget-active path, no PC Remote switch and no UVC enumeration were exercised; loading in MSC is not proof that the session path is safe. The dmesg ring retained only early boot output, so absence of module init messages is not evidence of silence. The absence of an oops in 5,135 bytes of retained dmesg is not a complete kernel-log proof.

## Next

P4b: `run_uvc_ptp_session_test.py --p4` with the rebuilt stop-attested runner, 60-second hold, strict receipt/after policy and no module unload without a verified teardown. User-gated.
