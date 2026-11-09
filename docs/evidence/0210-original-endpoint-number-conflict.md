# E0210 — Original SET_CONFIGURATION endpoint-number conflict

Date: 2026-11-09. Offline admission proof followed by a physical 90-second enumeration test.

## Physical Windows result

With the endpoint84 candidate, Windows enumerated both children simultaneously without manual driver replacement. `active-binding.json` records parent `usbccgp`/`usb.inf`, PTP MI_00 `WUDFWpdMtp`/`wpdmtp.inf`, UVC MI_01 `usbvideo`/`usbvideo.inf` (Camera, ILCE-6400), all Status OK / ProblemCode 0. The monitor first reported the healthy UVC child at 40.6 seconds. This is joint driver enumeration, not proof of actual PTP control transactions or sensor frames. Evidence directory: `artifacts/hardware/uvc-ptp-endpoint84-e0210`.

**Recovery failure:** after the monitoring window, the user reported that the camera menu no longer responds. The controller timed out waiting for MSC reconnection; a subsequent present-device query found no Sony USB device. No final camera receipt or teardown completion was recovered, and module unload/restoration is NOT confirmed. User was asked to disconnect USB and check whether the menu responds, with power left on initially. Do not repeat deployment until camera recovery and teardown diagnosis. Enumeration success must not be described as a successful complete lifecycle.

**Recovery verified:** disconnecting USB did not restore the menu. User subsequently restarted the camera, confirmed that the menu works and reconnected in MSC. Read-only debugger verification then succeeded: debugger PID703 responsive, PID149 TracerPid0, no `usbg_video` module, uptime56.81s. The set of module names matches pretest; raw `/proc/modules` is not byte-equal across the restart, so do not claim in-place rollback. Recovery files are `debugger-after-reboot.txt`, `modules-after-reboot.txt`, `status-after-reboot.txt`, `uptime-after-reboot.txt`; manifest status is `children_enumerated_teardown_unconfirmed_recovered_by_restart`. Final session receipt was not recovered before restart; exact hang site remains unknown.

The original pullup disable has an unbounded busy wait (E0184), and the configured-session disconnect also invokes original driver teardown. These are investigation targets, not established causes. No further physical activation should precede a reviewed configured-session teardown path and better stage visibility. The host controller's misleading elapsed-window message has been corrected: it no longer asserts that the camera session completed.

The original Sony SET_CONFIGURATION branch at `0x602b9650` scans endpoints by `address & 15` (`0x602b9740`), comparing interface ownership, full address and endpoint metadata. The PTP OUT endpoint `0x02` on interface 0 and UVC IN `0x82` on interface 2 therefore collide in this native implementation. This is a concrete camera-side configuration obstacle, not yet proof of the cause of Windows parent Code 10: E0209 did not trace all setup requests.

`tools/research/probe_uvc_ptp_config_endpoints.py` executes the original instruction loop with explicit descriptor/stack/context fixtures. Configuration lookup, prior teardown and hardware admission are service doubles. It stops at the native conflict branch `0x602b9898` or completed endpoint scan `0x602ba42c`. Results: UVC 82/81/83 conflict; UVC 84 completes the scan. It does not claim full SET_CONFIGURATION success, endpoint hardware allocation, driver callbacks, or Windows child enumeration.

Candidate changes consistently move shared UVC to IN `0x84`: VS input header, endpoint descriptor, enabled-endpoint selector (`dwc+0xf4`, derived from original mapping), reference START tag immediate (`7b20e0e3`), build integrity expectations and offline fixtures. PTP endpoints remain unchanged. Video START/submission remains disabled for the enumeration candidate.

Built module: `artifacts/native/uvc-ptp-module-e0210/usbg_video_a6400_shared_candidate.ko`, 71904 bytes, SHA-256 `7440933f3b07e0c8d9dda9fc7883ee9934238e6924468cb67103bb7e65d74e80`, 55 verified imports. Compiled module audit: 118 checks pass. Adapter controls: 65 pass. Descriptor serialization/identity/clone controls pass. Integrated descriptor lease/session/native backend controls: 155 pass after correcting an outdated test fixture's raw endpoint slot to match the new address.

Initial general test run encountered four temporary-file permission errors; retain `artifacts/uvc-ptp-endpoint-e0210-tests.log` as the failed receipt. Retry: all 612 tests pass in 16.922 seconds (`artifacts/uvc-ptp-endpoint-e0210-tests-retry.log`). Initial module-audit compiler invocation also lacked WSL access; rerun with compiler access passed.

Next: investigate configured-session teardown and a recoverable observation path (E0211) before another physical activation. Do not infer sensor streaming or retained camera controls from enumeration alone.
