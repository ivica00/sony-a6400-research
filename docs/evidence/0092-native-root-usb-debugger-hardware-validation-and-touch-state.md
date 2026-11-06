# 0092: Native root USB debugger validated on hardware; touch-state readout

## Installed, native USB verified

The already approved bootstrap completed after physical reconnect. All payloads and preload were read-back verified; manifest `artifacts/hardware/native-usb-debug-deploy-20261105-170527/manifest.json`. It preserves the experimental touch preload and adds `/setting/usb_debug_launcher.so`. The normal-mode daemon is `/setting/a6400_usb_debugd.elf`.

`tools/camera_debugger.py info` then succeeded over existing normal USB external commands, without Senser/updater entry: A6400_USB_DEBUG_V1, PID 1793, uid/euid/gid 0, feature 0x23. `/proc/self/status` reports Uid/Gid all zero and CapPrm/CapEff/CapBnd `ffffffffffffffff`. These are actual camera observations; no additional kernel privilege change was made. Startup hook installation is verified; a separate future power-cycle restart test is not yet performed.

The first validation report, `artifacts/hardware/native-usb-debug-validation-20261105-170626/`, retained two useful failures: `id` and `head` are not present in the camera shell (exit 127), while `printf ...; exit 7`, timeout and process-memory reads worked. Do not confuse unavailable shell utilities with lost root permissions.

The corrected validation `native-usb-debug-validation-20261105-170848/` uses supported shell builtins and proves:

* Shell Uid/Gid zero and effective capability mask are read from the executing shell's own status.
* `printf ok; exit 7` returns exactly `ok` and status 7.
* A shell-generated 5,000-byte output returns 4,064 bytes plus the truncation flag.
* `sleep 6` is stopped at approximately 5.048 seconds, reporting -ETIMEDOUT.
* Process names, TID names and complete process comm/status/maps files are readable.
* Read-only ptrace windows from PID 149 show input `...0124...` and menu `...00bf...`: the two prior touch patches are still present in this session.

All of these operations, including multiple separate sessions and file/memory reads, use native USB. No service-mode transitions or USB reset calls were needed after bootstrap. MTP mode and recovery after a future disconnect/reset remain unverified.

## Additional debugger improvements

The client now serializes this workspace's separate processes using an OS file lock, avoiding mixed USB request/reply transactions. A real child-process test verifies exclusion while held and acquisition after release. It does not serialize unrelated third-party clients outside this workspace.

`push LOCAL REMOTE` transfers up to 1 MiB through bounded root-shell printf chunks and verifies the complete bytes by native read-back. A 772-byte probe containing all byte values, NUL, quotes and backslashes passed; its own `/tmp_bt/a6400_debug_upload_probe.bin` was removed successfully. Report: `artifacts/hardware/native-debug-upload-20261105-171929/`. This removes the need for another Senser bootstrap for routine small tool uploads. Arbitrary shell commands and uploads remain explicit caller actions.

## Native touch-state observation

`tools.research.remote_elf` resolves exact on-camera ELF32 dynamic symbols through bounded GNU-hash lookups, rather than reusing preserved-image offsets. `native_touch_state` verifies the original GetInstance singleton-pointer producer before deriving the pointer slot. Report: `artifacts/hardware/native-touch-state-20261105-171259/`.

* InfraTp singleton slot 0x0713daa4, object 0x00055880.
* Event-switch byte at object+0x32 is **1** in the USB-connected snapshot.
* Raw words at +0x38/+0x3c/+0x40 are `[0,0,40]`; raw resource mode at +0x44 is 0. Do not label these values enabled/disabled without establishing their enum/resource meaning in the current camera path.
* Menu halfword patch remains present.

The user previously confirmed autofocus touch works and MENU touch does not. This snapshot supports investigating native event dispatch/widget state rather than adding more hardware-on patches. It is not a sample taken while the real MENU was displayed.

## Menu object discovery and finite background sampler

`native_menu_objects` reads and verifies the on-camera PAS_MenuSelectMode constructor's original literal/GOT producer. Live vtable is 0x15f14bd0; mouse method 0x0631e5c9, mouse hook 0x0631e5cf and default-mode setter 0x0612a497. Primary heap scan (0x15000..0x4f3000, 5,103,616 bytes) found **zero candidates** while USB mode was active. Report: `artifacts/hardware/native-menu-objects-20261105-171451/`. The scan is not an atomic snapshot and does not cover all camera allocations; absence here does not prove absence of native menu objects.

Prepared and native-upload/read-back verified a finite read-only sampler `/setting/native_menu_probe.elf` (11,328 bytes; SHA-256 `4ef8b864b37ab261753360b4b6afbe7de36a1cce6503ce94817743300d104485`). Source `devcrashday_a6400/native_menu_probe.c`, argv-aware entry `probe_start.S`; the original debugger's `debug_start.S` remains unchanged. It scans the primary heap, viewUnified2 writable mapping and large private anonymous mappings, bounded to 12 ranges / 40 MiB and at most 16 MiB per range. Up to 32 matching-vtable candidates produce raw default-mode/menu-data/child-vtable fields; these are candidate observations, not proven widget ownership or event delivery.

The sampler performs no code writes, key injection or hardware-setting changes. It briefly ptrace-stops the process leader for each read, then detaches; other threads are not globally stopped. It samples up to 120 times at three-second intervals and can be stopped using its own `/tmp_bt/native_menu_probe.stop` file. Logs and the process marker use volatile /tmp_bt. It has an advisory lock and bounded logging. This diagnostic must be started and its actual log checked before asking for a menu interaction test; deployment alone does not prove it ran.

The sampler was subsequently started through native EXEC and its actual log read back: PID **1863**, `sample=0 scanned=28389376 candidates=0 atomic=0`, with the expected read-only header and no END at this initial read. Initial evidence is retained at `artifacts/hardware/native-menu-probe-start-pid1863.log`. It is now armed for a user interaction test while USB is unplugged. Next user reconnect: read `/tmp_bt/native_menu_probe.log` through the native client, preserve it in a fresh report directory, then stop only this sampler with its stop marker if still running. The finite run is approximately six minutes plus scan time; if expired, preserve its report and rearm explicitly as needed. Do not reboot/remove battery before collecting this volatile report. Opening/using MENU during disconnection is still required; no successful touch behavior is claimed.

## USB lifecycle boundary

The daemon can remain a background process; commands currently work whenever the normal USB transport is available. Stock Mass Storage/Senser are driver/gadget modes, not established independent concurrently callable processes. No simultaneous configuration, host port power cycle, device reconnect ioctl or reset/re-enumeration sequence has been verified here. The new channel avoids routine Senser entry/stop; it does not prove recovery from a fully disconnected USB gadget. A future mode manager must report actual states and coordinate transitions without assuming a host reset can recover a disappeared interface. Wi-Fi operation is still unverified.

## Validation

Full suite: **560 tests passed in 21.310 seconds**, including strict ELF metadata guards, protocol validation, remote ELF bounds/hash lookup, and cross-process locking. ARM sidecar compiled with warnings as errors and original Sony libc. The decisive runtime debugger checks above are hardware observations, separate from the fixture test suite. The touch-menu objective remains incomplete. No SD card writes were made.
