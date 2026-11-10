# E0271 — F7 final test: LCD liveview active, still no PTP frame; teardown stuck again

Date: 2026-11-09. Physical bounded session (e0251 + fixed PTP probe). Recovery by battery removal.

## Result

- Probe: `no_frame`; connected at 20:32:17, stopped 20:32:21; **device_count = 1** (one Sony WPD device this time); 1.5 s settle + 120 GetObject retries; no frame.
- **Operator observation: the camera LCD showed liveview during the composite session (DA).** This is the first in-session liveview observation.
- Session: **teardown unconfirmed** — `cleanup_error: DebuggerError('Camera error -2: ')`, no `p4_receipt`, `status: started` in the manifest; the tool could not reconnect to the camera.
- Recovery: **battery removal/reinsert**; camera back in MSC, uptime 27.84 s, 42 modules, `usbg_video` absent, `TracerPid: 0`.

## Interpretation

- The camera **was in its liveview state** (LCD liveview), so `s_LiveViewStatus` was presumably set; the app's remote stack had the liveview status active. **The PTP frame absence is therefore downstream of the liveview state** — in the PTP/Mtp response path or the app's message dispatch, not in the liveview on/off gate.
- The teardown stuck again. With the PTP probe, failures are now 2/3 (F5b-1 fail, F5b-2 clean, F7 fail); without PTP, 3/3 clean. The failure is intermittent and correlated with the PTP probe but not deterministic; the exact race is unresolved.

## Limits

One session; the liveview observation is operator-reported (not instrumented). No receipt for this teardown; battery restart was required.

## Next

- Offline: analyze the **GetObject/Mtp response path** (why no frame with liveview active): the app-side `GetLiveViewStatus` branch issues `GetObject(0x1009)`; follow the Mrpw/stillimage response to the PTP interface and look for a state/format gate.
- Teardown: investigate the intermittent stuck gadget when the PTP probe is active (timing/race around unconfigure while PTP is open); no new physical session without a concrete plan.
