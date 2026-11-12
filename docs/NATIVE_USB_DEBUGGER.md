# Native USB debugger (installed; normal MSC verified)

## Protocol v2 (E0401): warm log readout, recover, and the PC Remote boundary

The installed daemon now speaks protocol v2 (same 4096-byte frame, feature
`0x23`, opcode `0x7a`) and adds four operations while keeping the v1 surface:

* `usb-state` — UDC/module/node/klog/debugger receipt.
* `dmesg` — non-destructive kernel printk readout over USB (`SYSLOG_ACTION_READ_ALL`);
  no SD card needed.
* `dump-ring` — the camera kernel's warm-reboot klog ring at the
  `/proc/cmdline`-verified `klog.addr` (`0x035a5000`, `0x20000` bytes), read
  through `/dev/mem` O_RDONLY, validated against `/proc/iomem`, CRC32-checked,
  and split into per-boot segments. A warm reboot keeps the previous boot's log
  and appends the next boot's log (decoded from the preserved `vmlinux.bin`).
* `recover` — process-context removal of allowlisted authored modules with a
  receipt; `recover --to-msc` additionally asks a PTP-mode camera to reconnect
  to Mass Storage (`SonyReqReconnect 0x9282`), where that operation exists.

**Measured boundary:** this firmware's stock PC Remote mode (`054C:0CAA`) exposes
only PTP `0x1001-0x100A/0x101B/0x9201/0x9202/0x9205/0x9207/0x9209` — no
`SonyDiExtCmd 0x9280/0x9281` and no `0x9282`. The debugger therefore answers in
Mass Storage and survives a full MSC→PC Remote→MSC round trip with the same
pid, but is **not reachable while PC Remote is active**. Recovery from PC Remote
is currently the camera's own menu switch (zero battery pulls), or a future
composite-gadget interface. An "MTP" USB setting was requested but the camera
re-enumerated as Mass Storage before each recorded session, so MTP-mode
reachability and a live in-band MTP→MSC switch are **not** claimed; the
`0x9282` request is sent on the same open MTP session when one is present. See
[E0401](evidence/0401-usb-debugger-v2-ring-recover-and-mode-boundary.md).

`tools/research/upgrade_usb_debugger.py` stages a new daemon over USB
(`/tmp_bt` → `/setting`) with a preserved rollback copy and never needs service
mode; the daemon retries lock/registration so the old instance can be stopped
without leaving the camera without a debugger.

Research update, 2026-11-06: see E0106–E0109 for complete active-menu capture,
original lookup/geometry/hit/selection controls and the remaining activation
resource-manager boundary. The one-shot main-thread helper reads TLS/registers
and detaches; it does not establish the originating UI worker. Operational
workflow: [live camera plus emulator](LIVE_CAMERA_EMULATOR_WORKFLOW.md).
Historical statements below that the debugger was not yet installed refer to
pre-E0092 preparation, not its current installed state.

Latest menu investigation: E0097 captured the actual PAS_MenuListTab tree and
touch coordinates during disconnected MENU interaction. The root inherits an
empty mouse handler; only GEN_Button among 21 sampled widget types has a
specialized handler. Touch menu remains incomplete: the original application
selection/activation contract still needs verification. Targeted observers
were built and verified running, logs preserved, then stopped. See
`docs/evidence/0097-real-menu-widget-tree-and-mouse-handlers.md`. Use host `python`
for the client in this environment; the workspace venv lacks Crypto.

Hardware status: installed with read-back verification, running as PID 1793/uid=euid=0 over normal USB external commands. Shell status/capabilities, command exit codes, five-second timeout, output limits, process/thread/file/memory reads and verified small binary uploads have passed camera tests. Multiple sessions worked without service-mode entry. See E0092 and the manifests under artifacts/hardware. A separate future power-cycle startup test, MTP mode, and disconnected-interface recovery remain unverified. The historical preparation/approval text below records earlier stages; it does not override this current status.

Current status: the user explicitly approved this package after the initial automatic-review rejection. Bootstrap then stopped on original-file comparisons, which were resolved as build metadata differences with code/data/relocations verified unchanged. No payload/startup write has occurred; the camera stopped enumerating before the next attempt. Resume the approved installer after physical USB reconnect. See E0091 for exact captured originals and identity checks; no repeat deployment approval is needed.

This debugger registers a userspace command handler in Sony's existing `/dev/usb/usb_extcmd` driver. Normal requests use the Sony MSC/MTP external-command transport, feature 0x23. The client never enters Senser or updater mode. MSC operation is the first hardware test target; MTP support is implemented but unverified.

The previous Antigravity bridge in tools/usb_session.py used Senser. Its historical task-2546 log explicitly records switching modes and a working root shell. The new channel has not yet been deployed or tested on camera; current camera identity succeeds over native USB, but both the PMCA TEST probe and the local bridge did not provide a usable normal-mode debugger.

## Intended capabilities

* `info`: server PID, uid/euid/gid, protocol and limits.
* `ps` / `threads PID`: process or thread names.
* `read /absolute/path`: chunked file/pseudo-file reads with explicit limits.
* `maps PID` / `snapshot PID DIRECTORY`: retain process comm/status/maps locally.
* `mem PID ADDRESS SIZE`: bounded read through ptrace, with attach/wait/read/detach. This temporarily stops the selected thread; it does not stop all threads or produce an atomic whole-process snapshot.
* `exec COMMAND`: root shell command, merged stdout/stderr, real exit status, five-second deadline and explicit output truncation. These commands can modify the camera when the caller requests it.
* `push LOCAL REMOTE`: bounded small binary upload through supported shell printf, with full read-back verification, without service mode.
* `stop`: unregister this USB feature and exit the debugger process.

No network listener is created. No kernel patch, global security setting change, flash partition rewrite, or camera UI replacement is part of this debugger. Effective permissions must be measured on hardware; no privilege beyond root is claimed.

## Build and validation

Run `venv\Scripts\python.exe -m tools.research.build_native_usb_debugger` from the project root. It uses the installed WSL ARM compiler and original Sony libc, with explicit time/file ABI settings, linker undefined-symbol rejection and warnings as errors. It does not install tools or deploy to the camera. A manifest under artifacts/analysis retains source/binary hashes.

Six protocol tests cover response identity, malformed frames, chunk offsets, EOF versus limits, errno versus shell exit status, memory bounds and path validation. The full project suite passed 553 tests before final C-only cleanup. The ARM sources compile successfully; this does not validate their hardware behavior. A host C dispatch harness exists at tools/research/test_usb_debug_dispatch.c, but was not run because this WSL installation has no native gcc/cc (only the ARM cross-compiler). Timeout/truncation and native ioctl lifecycle still require runtime tests. Do not describe these C paths as exercised.

## Deployment and approval boundary

Deployment was blocked by automatic approval review: general debugger improvement authorization did not explicitly cover a persistent root USB server with arbitrary shell commands, file access and process-memory reads. Obtain the user's explicit approval for this package before running `venv\Scripts\python.exe tools/deploy_native_usb_debugger.py`. Do not work around that rejection.

The one-time installer uses Senser to read/verify the analyzed camera driver/API, upload and read back two small payloads, back up `/etc/ld.so.preload` locally, and append `/setting/usb_debug_launcher.so` while preserving existing entries. No new USB server is currently installed. After installation, subsequent debugger requests are intended to avoid service mode; native registration must first be verified.

The launcher starts the daemon once per boot, using `/tmp_bt` for its one-shot marker. The daemon holds an advisory process lock and unregisters its feature on a clean stop. `/setting/disable_usb_debug` suppresses future launches; it does not stop an existing process. `stop` does not remove preload or its launch marker. Remove only this launcher's preload entry to uninstall startup behavior, preserving other entries. Keep the installer's before/after files and report actual read-back results.

## First hardware checks after approval

Use the client with the existing USB mode and verify `info`, `exec 'id'`, `/proc/self/status` effective capabilities, `ps`, process maps and a small known code window. Test `exec 'printf ok; exit 7'` and bounded timeout/output behavior. Retain failures as failures; never auto-fallback to service/updater mode. Confirm the complete original ioctl create/transfer/destroy lifecycle before relying on repeated sessions.

The debugger is an investigation tool. The physical touch-menu mod is still not functional; further native touch-to-widget event tracing remains necessary.

## Current USB lifecycle guidance

The native daemon is a background process, so routine debugger calls no longer require entering and stopping Senser. The client serializes this workspace's sessions. It does not automatically reset USB, switch camera modes, or power-cycle a port. Simultaneous Mass Storage/Senser operation and software recovery after the gadget disappears have not been tested. Keep those device-state transitions distinct from the background process lifecycle.
