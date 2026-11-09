# E0186 — Original gadget setup interface dispatch

Offline execution against retained a6400 kernel SHA-256 `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707`. No camera access, hook publication, upload or module change.

Original `g_setup` (`0x602b8328`) resolves gadget device data and checks gc+0x68 bit 2. Inactive returns zero without calling setup_req. Active calls original `setup_req` at `0x602b94a4`.

For a class/interface request (bmRequestType 0x21), the original branch at `0x602b9ffc` uses current configuration gc+0x74 and the low interface byte from wIndex. At ordinary GCW state (fixture 0), it walks the native list at gc+0x78, requiring descriptor byte +4 to match configuration and byte +5 to match interface. A matching nonnull driver callback at descriptor+0x2c receives r0=descriptor, r1=USB control request, r2=gc gadget pointer (+4).

Callback result zero goes through clear_halt and returns zero. Result one rejects with -EINVAL (-22). Other nonzero results continue searching; a one-entry exhausted list also returns -22. Thus a driver's -95 does not propagate directly through this branch. Callback return is synchronous at this call site, but does not establish completion of any request the callback may have queued.

`tools/research/probe_uvc_ptp_setup_dispatch.py` executes original g_setup and setup_req instructions with explicit descriptor/list/request fixtures. Six passing cases cover inactive, accepted, callback result 1, callback result -95, wrong interface and wrong configuration. Device-data lookup, GCW state, driver callback and clear_halt are explicit service doubles; real driver callbacks and EP0 queue/completion are not executed.

```
python -m tools.research.probe_uvc_ptp_setup_dispatch --output-dir artifacts/analysis/uvc-ptp-setup-dispatch-e0186
```

Manifest: `artifacts/analysis/uvc-ptp-setup-dispatch-e0186/manifest.json`. Module code did not change; prior full project test results are not reported as rerun.

This verifies the original routing contract relevant to separate PTP/UVC interfaces, not concurrent operation on camera. Next trace EP0 request queue ownership/completion and event admission cessation before retiring descriptor hooks. E0182 remains the candidate, no hook is installed by this work, and combined PC Remote+UVC/PTP test remains not ready. Camera should remain in Mass Storage pending that procedure.
