# F8 repeat PC Remote probe runbook

Status: offline analysis complete enough for a bounded repeat; the physical step needs user approval.

## Preconditions

- Camera in Mass Storage, healthy: `/proc/uptime` monotonic, 42 modules, no `usbg_video`, `TracerPid: 0`.
- Host enumeration clean before the session: composite parent **and** PTP child present (no `VID_0000` / descriptor failure).
- e0251 module + runner identities unchanged; audit `offline_module_audit_passed`.

## Steps

1. Start `run_uvc_ptp_session_test --p4` (e0251, duration 60, MSC wait 120) and the fixed
   `run_ptp_liveview_probe` (settle 1.5 s, retries 120, **close/finally enabled**).
2. Wait for `runner_ready_before_switch=true` and probe `waiting`.
3. User switches the camera to PC Remote; observe the **camera LCD**: liveview shown? (DA/NE).
4. Probe connects, handshakes, polls; it must exit and write `closed_utc` **before** the user
   returns to Mass Storage.
5. User waits ~15–30 s after the probe exits (cooldown), then returns to Mass Storage.
6. Session waits for MSC, reads the receipt, checks the host-enumeration gate
   (`pre_teardown_host_gate`: parent + PTP child), then rmmod/verify.
7. Evaluate: frame (1024×680) captured? receipt stop/retire/complete? host enumeration present?
   LCD liveview shown?

## Acceptance

- **Frame**: `status=captured`, 1024×680, JPEG > 100 B, saved.
- **Teardown**: receipt markers `init/stop_verified/retired/completed` in order, module removed,
  MSC return, no reboot.
- **Host enumeration**: parent + PTP child present at the last monitoring sample.
- **Observation**: LCD liveview DA/NE recorded.

## Abort and recovery

- If the host enumeration loses the PTP child or shows a descriptor error during the session,
  the teardown is at high risk (F5b-1, F7 correlation); expect a possible stuck gadget.
- If the camera does not return to MSC: **battery removal/reinsert**, then verify MSC and record
  `teardown_unconfirmed`. Do not rmmod without a receipt.

## Known limits

- The runner performs its teardown at the end of the 60 s window; the host-enumeration gate is
  diagnostic/expectation, not yet an automatic pre-teardown veto inside the runner.
- PTP-probe sessions are 2/3 stuck so far (F5b-2 clean); the correlation is with host enumeration
  loss, not proven causation.
