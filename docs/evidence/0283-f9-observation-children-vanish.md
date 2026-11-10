# E0283 — F9 observation: composite enumerates, then the children vanish at liveview start

Date: 2026-11-09. Physical bounded observation (e0251 session, no probe) + 0.2 s USB capture.

## Timeline (capture samples, 0.2 s)

| Time (UTC) | Parents | PTP children | UVC children | Event |
| --- | --- | --- | --- | --- |
| 21:01:08 | 0 | 0 | 0 | start |
| 21:01:48 | 1 | 0 | 0 | parent appeared |
| **21:01:58.7** | **1** | **1** | **1** | composite enumerated (PTP + UVC children present) |
| **21:02:54.4** | 1 | **0** | **0** | children vanished (liveview start / app gadget re-create) |
| 21:03:07.6 | 0 | 0 | 0 | teardown/MSC return |

## Session

- `p4_session_completed`; receipt `init/stop_verified/retired/completed` — **clean teardown** (5/6 clean).
- `host_enum_gate` false at the last sample (children gone).
- Camera in MSC afterwards (uptime 1787.18 s, 42 modules, no `usbg_video`).
- Operator LCD observation still pending.

## Interpretation

The composite configuration and both children work at enumeration (21:01:58.7). At liveview
start the app's gadget re-create removes the **PTP and UVC child functions** while the parent
remains — matching the mismatch/function-registration hypothesis (E0282): the config descriptor
hook still returns the composite, but the re-created gadget no longer exposes the child
functions, so the host sees the parent without children (and the probe later finds no WPD PTP
device).

This also explains earlier sessions: when the probe connected before the transition, it lost the
device afterwards; when it started after the transition, `no_wpd_device`.

## Next

- Mitigation: ensure the app's re-created gadget keeps/serves the child functions, or re-apply
  the UVC/PTP function set after `usb_gcw_start` (option B), with the consistency fallback
  (option A: unhook the config descriptor around the app re-create so the host sees a consistent
  stillimage-only device).
- A controlled re-enumeration after the app's re-create may be needed to re-expose the children.
