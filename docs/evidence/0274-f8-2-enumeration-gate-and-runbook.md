# E0274 — F8-2: teardown failures correlate with host enumeration loss; runbook and gate

Date: 2026-11-09. Offline only.

## Correlation

| Session | Host enumeration (monitor) | Teardown |
| --- | --- | --- |
| F5b-2 (E0257) | parent + PTP child present (`pcremote_active`, binding parents/children) | clean |
| F5b-1 (E0255) | `VID_0000/PID_0002` descriptor failure | stuck (battery) |
| F7 (E0271) | last samples: `pcremote_active=true` but **binding parents/ptp_children empty**, `ptp_count=0` | stuck (battery) |

The stuck teardowns happened when the host had lost the composite enumeration (no PTP child),
not merely when the probe was active. The clean F5b-2 had parent + PTP child. The PTP probe and
enumeration loss may share a cause (host/WPD opening during composite enumeration), but the
correlation is the actionable signal.

## Gate

Added `pre_teardown_host_gate(binding)` to `p4_policy.py`: requires `composite_parent_ready`,
`ptp_ready` and `ptp_children`; returns reasons otherwise. Tests: `tests/test_p4_host_gate.py`
(4 cases); p4 policy + gate tests 16 pass; full suite **657 tests**.

## Runbook

`docs/F8_REPEAT_PROBE_RUNBOOK.md` defines the bounded repeat: fixed probe with close/finally,
LCD liveview observation, probe completion before returning to MSC, cooldown, host-enumeration
gate at the last monitoring sample, receipt, and battery recovery if MSC does not return.

## Limits

The runner's teardown is still automatic at duration end; the gate is diagnostic/expectation,
not yet a pre-teardown veto. Causation between the probe/WPD activity and enumeration loss is
unproven.

## Next

- Integrate the host gate into the session tool's reporting/decision path (or document the veto).
- Then run the repeat probe under the runbook (physical, user approval).
