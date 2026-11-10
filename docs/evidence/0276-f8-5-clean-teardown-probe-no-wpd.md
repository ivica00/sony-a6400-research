# E0276 — F8-5: clean teardown, host enumeration lost, probe never connected

Date: 2026-11-09. Physical bounded session (e0251 + fixed probe with close/finally).

## Result

- Session: **`p4_session_completed`**, receipt `init/stop_verified/retired/completed` all present, no cleanup error — teardown **clean** (4/5 clean overall).
- Host gate: **`ok=false`** — `composite_parent_not_ready`, `ptp_not_ready`, `no_ptp_child`; last monitoring sample `pcremote_active=true`, `ptp_count=0`. PnP showed the WPD parent (`VID_054C&PID_0CAA`, Status OK) but no PTP child.
- Probe: **`no_wpd_device`** (120 attempts, stopped 20:48:40); never connected, so no PTP session and **no frame**; `closed_utc` absent because no connection was established.
- Camera: back in MSC, healthy (uptime 861.64 s, 42 modules, no `usbg_video`).
- LCD observation: pending (operator not yet reported).

## Hypothesis refinement

| Session | PTP probe connected | Host PTP child | Teardown |
| --- | --- | --- | --- |
| F5b-2 | yes | yes | clean |
| F5b-1 | yes | descriptor failure | stuck |
| F7 | yes | no | stuck |
| F8-5 | **no** | no | **clean** |

The stuck risk appears to require **an established PTP session plus host enumeration loss**; enumeration loss without a PTP session was clean. The probe's close/finally was not exercised this run.

## Limits

No frame path test this run (probe never connected). The WPD/PTP child enumeration on Windows is now the primary blocker for the repeat: the composite session sometimes exposes the parent but not the PTP child, and the probe's WPD discovery fails.

## Next

- Investigate/repair the host-side PTP child enumeration for the composite session (Windows WPD/USB stack timing; maybe a re-enumeration/retry before starting the probe).
- Then repeat the probe under the runbook and record the LCD observation.
