# E0244 — P0 idle isolation, trial 1: bounded staged process, no reboot

Date: 2026-11-09. Physical, read-only observation plus one bounded idle collector session. No `/dev/mem`, no SD write, no UVC activation.

## Trial 1

- Preflight (read-only debugger): camera in Mass Storage, uptime 4049.97 s, 42 modules, no `usbg_video`.
- Staged `native_monitor_collector.elf` SHA-256 `b0402893382ce4763db2eff357d12d9eb04f375845213cec67d63e15425382af` (24,652 B) in `/tmp_bt/mon_sd_20261109_192750.elf`, PID 824, mode `--sd-idle`; the collector waits for the ordinary PC Remote identity and holds a bounded RAM-only session.
- User switched the camera to PC Remote and returned it to Mass Storage.
- Receipt marker: `MONITOR_COLLECTOR READY pid=824 mode=sd_idle bounded_RAM_log` and `IDLE_SESSION_COMPLETE result=1` (92-byte receipt).
- Uptime after: 4374.99 s, i.e. +300.45 s over the staging uptime (4074.54 s). Monotonic, so **no reboot** occurred during the switch or session.
- Module count before/after both 42; `usbg_video` absent; MSC debugger reconnected.
- Cleanup: `receipt_recovered_idle_success_cleaned`; owned `/tmp_bt` files removed after preserving the receipt.

## Interpretation and limits

One bounded idle session with a staged process completed without a reboot and without touching `/dev/mem`, SD or UVC. The reboot fault is intermittent (an earlier probe-5 with the same build rebooted), so this single trial does **not** establish isolation. The acceptance for P0 is three consecutive idle trials with monotonic uptime; 1/3 is complete. If 3/3 pass, the next physical step is a P4 enumeration/teardown rerun with the existing enumeration-only module. This trial provides no evidence about UVC activation, PTP transactions, streaming or teardown with a module loaded.

## Next

Trials 2 and 3 with the same staged idle collector, each followed by receipt recovery, uptime check and cleanup.
