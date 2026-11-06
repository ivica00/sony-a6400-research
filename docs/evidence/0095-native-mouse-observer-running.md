# E0095 — Targeted native mouse observer running

Date: 2026-11-05. Physical ILCE-6400, normal USB debugger PID 1793.

WSL works with the required host execution permission. The existing targeted
`native_mouse_probe.c` builds with warnings as errors, original Sony libc,
ARM EABI and `/lib/ld-linux.so.3`. Binary is 6960 bytes, SHA-256
`327a08da4f56dc470d531e5f037d5f34dc5a8557b8a12a797c8d968a89275cda`.
Native push to `/setting/native_mouse_probe.elf` verified the complete readback.

Observer PID 2045 was started and confirmed by ps and its first log sample.
Retained start log: `artifacts/hardware/native-mouse-probe-start.log`.
It reads the verified singleton and 80-byte mouse records only, with detach
between samples; no application RAM patches, input injection or SD writes.
Sample zero contains 0x7fff coordinates and zero states while USB is connected.
This does not establish disconnected touch behavior.

The observer runs for at most 1800 samples at 100ms plus read overhead (about
three minutes). Physical interaction is now needed: unplug USB without powering
off, open MENU, turn the wheel/change category, touch several menu positions,
and reconnect. Preserve `/tmp_bt/native_mouse_probe.log` with
`python tools/camera_debugger.py read /tmp_bt/native_mouse_probe.log --output ...`.
Use normal USB, not Senser. If the finite window expired before interaction,
retain the log and rearm a fresh bounded run before requesting a test.

Host `python` has the required Crypto/USB dependencies; this workspace's venv
currently lacks Crypto. No dependency install was needed.

Touch MENU remains unimplemented. A successful observer launch is not a touch
modification or a verified menu dispatch path.
