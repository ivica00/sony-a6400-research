# E0254 — F5a: repeated clean teardowns (3/3)

Date: 2026-11-09. Physical sessions with the unchanged e0251 candidate and rebuilt runner. No new module behavior, no PTP transaction yet.

## Results

| Session | Result | Receipt | Postflight uptime | Modules | usbg_video | Reboot |
| --- | --- | --- | --- | --- | --- | --- |
| E0252 (F4) | p4_session_completed | stop-verified + retired + complete | 922.14 s | 42 | absent | no |
| F5a trial 1 | p4_session_completed | stop-verified + retired + complete | 1393.14 s | 42 | absent | no |
| F5a trial 2 | p4_session_completed | stop-verified + retired + complete | 1537.10 s | 42 | absent | no |

Each trial: preflight ok, both children enumerated (MTP + UVC Status OK), 60 s hold, `rmmod` succeeded, module list restored, Mass Storage returned, owned `/tmp_bt` files removed. Uptime is monotonic across the three sessions (922 → 1393 → 1537), so no reboot occurred.

## Interpretation

The unconfigure-first teardown is repeatable: three consecutive configured sessions ended with the stop/retire/unload receipt and a clean Mass Storage return. This is stability evidence for the teardown path, not proof about PTP transactions, streaming or sensor frames.

## Limits

Same module/runner and user-driven switches; no PTP command, UVC START, sensor frame or SD write. Timing/uptime deltas are not performance measurements.

## Next

F5b: the same session with the read-only WPD/PTP liveview probe, expecting one 1024×680 JPEG and the same clean teardown.
