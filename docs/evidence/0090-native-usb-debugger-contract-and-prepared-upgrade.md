# 0090: Native USB debugger contract and prepared upgrade

## Scope and historical channel identification

User asked to continue the touch-menu investigation, use USB debugging without service mode when possible, and improve debugger functions/permissions. They clarified they did not know the command/tool, but Antigravity had implemented it and also tried Wi-Fi.

Read-only, project-specific inspection of Antigravity's retained camera-task history located `brain/8a822bd0-2c71-41a0-aa94-e79e9c1ecc0e/.system_generated/tasks/task-2546.log` under the user's Antigravity data. That actual execution log explicitly records Mass Storage -> Senser, authentication, the localhost tools/usb_session.py bridge, and `Camera Root Shell Verified` with the camera Linux version. It proves a root **service-mode** shell, not a normal-mode debugger. Nearby project-task logs retain Wi-Fi attempts but no independently verified working Wi-Fi shell was established here. Treat historical prose claims separately from execution evidence.

`tools.research.probe_usb_debugger` ran against the physical camera without mode switching or updater execution. Camera information returned ILCE-6400, serial 03925553. Existing PMCA feature 0x23 TEST returned SCSI invalid-command sense 05/20/00. Manifest: `artifacts/hardware/usb-debug-probe-20261105-162923/`. The localhost :8088 ping timed out. No service-free shell was available in these probes.

## Original Sony contracts

Dependency planning completed 21 functions for usb_extcmd.ko under `artifacts/analysis/usb-debug-driver-20261105/`. A name-ambiguous libusbcmd REA batch is retained as failed under `artifacts/tools/rea/usb-debug-api-20261105/`. Successful exact-entry batch: `usb-debug-api-exact-20261105/`; input SHA-256 `9f2dd49dfae785aad9fbc1abf53c6d4179b8540c3e68ee1ca06eb2497bb71644`, Ghidra 12.1.4. For this ET_DYN, provider entries are linked addresses +0x10000: queried 0x12ae0, 0x12d60, 0x12782, 0x1279c, 0x1283c, 0x12590. Original instruction inspection independently checked the create path and literals.

Successful kernel batches `usb-debug-driver-20261105/` (extcmd_ioctl/open/release) and `usb-debug-wait-20261105/` (synchronize_wait_event/list_append_node/instructions) establish:

* Device `/dev/usb/usb_extcmd` is opened O_RDWR.
* Register ioctl 0xc00ceb00 takes 12 bytes: opcode u8 at +0, feature u16 at +2, receive size at +4, send size at +8. Existing library constructs opcode/feature from its arguments.
* Receive ioctl 0xc014eb02 and send 0xc014eb03 use a 20-byte driver parameter: pointer +0, size +4, remaining +8, timeout +12, flags u16 +16. Library PackParamDriver reorders its 24-byte public parameter into this structure.
* Duplicate opcode/feature registrations return -114. The implementation refuses takeover and closes the failed registration FD without unregistering another handler.
* Explicit unregister ioctl 0xc002eb01 is required: the release callback only frees per-file private storage, not the registered handler. The server explicitly unregisters before close.
* Timeout 0 means indefinite wait. The server uses exactly 1000 (one-second conversion path), not a guessed fractional timeout from decompiler pseudocode. Driver cancel/timeout conditions remain distinct errors.

These are static preserved-input contracts. The deployment script checks the on-camera driver/API files byte-for-byte before registering a server; this has not run because deployment was rejected.

## Prepared implementation

`devcrashday_a6400/a6400_usb_debugd.c`: a userspace handler for opcode 0x7a/feature 0x23 through the original driver. No updater invocation, kernel patch, app code patch or network listener. Fixed 4096-byte frames contain version/op/request ID/status/length/flags/arguments plus at most 4064 payload bytes. It implements actual uid/euid/gid reporting, process/thread names, bounded file/pseudo-file reads, read-only ptrace process-memory windows, explicit root shell commands with output limits/exit status/five-second monotonic deadline, and clean unregister/exit. Ptrace reads temporarily stop only the selected thread; they are not atomic whole-process snapshots. No new privilege beyond existing root is claimed.

`tools/camera_debugger.py`: native MSC/MTP client with bounded busy retries, response identity/length validation, explicit truncation, errno/command-status separation, chunked reads, and local process snapshots. It contains no service/updater mode transition and does not silently fall back. MTP is implemented but untested.

`devcrashday_a6400/hook/usb_debug_launcher.c`: once-per-boot double-fork/exec launcher, with a volatile /tmp_bt marker and `/setting/disable_usb_debug` suppression. Reaps its intermediate child. The server has its own advisory lock. Persistent startup requires appending the launcher to preload; this is part of the blocked deployment, not an already installed capability.

`tools/deploy_native_usb_debugger.py`: one-time Senser file bootstrap, verifies original camera driver/API, backs up preload, uploads and reads back both small payloads, then appends only its launcher entry while preserving existing entries. No deployment occurred.

`tools.research.build_native_usb_debugger` supports direct WSL invocation and records source/binary/libc hashes. Final build manifest: `artifacts/analysis/native-usb-debugger-build-20261105-164856.json`. ARM server and launcher build with warnings as errors, undefined-symbol rejection, explicit 32-bit time/file ABI, and original Sony libc. Dynamic server imports require GLIBC_2.4 only. A nested Windows-Python WSL call returned E_ACCESSDENIED; the existing direct-WSL path succeeded. No dependency upgrades were performed.

## Validation and approval boundary

Six new Python protocol tests pass; the full project suite passed **553 tests in 16.462 seconds**. Final C changes (reaping launcher child and retrying interrupted ptrace wait) compiled cleanly. The native C dispatch harness was prepared but could not run: WSL lacks native gcc/cc and qemu-arm; Windows gcc is MinGW. Do not claim C timeout/truncation/ptrace or ioctl lifecycle were runtime-tested. They require hardware checks after deployment approval.

Automatic approval review rejected execution of the deployment script: general authorization to improve the debugger did not explicitly approve persistently autostarting a root USB server capable of arbitrary shell execution, file access and process-memory reads. The installation command did **not** execute. Do not bypass the rejection; request explicit approval for this concrete persistent capability. Existing camera preload/mod state was not changed in this task.

Follow `docs/NATIVE_USB_DEBUGGER.md` for package scope, commands, first hardware checks, startup-disable and cleanup semantics. The original touch-menu objective remains open. This work prepares a more useful observation channel; it does not establish touch navigation or live debugger permissions.
