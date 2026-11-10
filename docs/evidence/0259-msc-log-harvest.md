# E0259 — Read-only MSC log harvest: no session logs retained

Date: 2026-11-09. Camera in Mass Storage; read-only debugger only. No writes, no PC Remote, no module.

## Tool

`tools/research/harvest_msc_logs.py` lists `/`, `/tmp`, `/log`, `/setting`, `/system`, reads bounded log/text files (including `/tmp/kikilog.dat`, 1,957,888 B) and scans for `liveview`, `SDIO`, `stillimage`, `usbg_video`, `PTP`, `0xFFFFC002`, `Composite`, `UVC`, `PC Remote`, `descriptor`, `054c`, `0caa`. Tests: `tests/test_harvest_msc_logs.py` (4 cases).

## Result

- 14 files harvested; **19 keyword hits**; camera unchanged (uptime monotonic, module bytes equal).
- The hits are in:
  - `/log/feeder.log` — a **legacy UVC feeder** record (720p@30 static pattern): `IOCTL_UVC_INIT/REG_BUF/ENABLE result=0`, `first IOCTL_UVC_UPDATE result=-16`.
  - `/tmp/a6400_hw_dump.txt` — module/library map (`usbg_stillimage`, `libInfraPtpControl.so`, `libInfraPtpExtCmd.so`, `libptp.so`).
- `/tmp/usb_daemon.log`, `/tmp/usb_cmd.txt`, `/tmp/uipc_stat_*`, `/tmp/gui.log`, `/tmp/modern_menu.log` contain no session evidence (homebrew/IOC statistics; empty logs).
- `/tmp/kikilog.dat` produced **no ASCII keyword hits** (binary/encoded Sony log format).
- No `/var/log`; no PC Remote/PTP liveview logs from the E0248–E0257 sessions survived (the camera was restarted and `/tmp` holds rootfs/homebrew artifacts).

## Interpretation

The camera's retained logs do not contain evidence about the composite-session liveview gap. Absence is recorded as absence, not as proof that the camera logged nothing. The legacy feeder log shows a previously exercised UVC INIT/REG_BUF/ENABLE path and an `UPDATE result=-16` (busy) on that older feeder, which is a separate historical data point.

## Limits

Read-only; no file was written on the camera. `kikilog.dat` parsing was ASCII-only; its binary format was not decoded.
