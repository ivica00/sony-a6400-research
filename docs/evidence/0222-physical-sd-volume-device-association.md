# E0222 — Physical SD/native volume association

Date: 2026-11-09. User returned after a shooting session, placed camera in MSC and explicitly requested repeating the observer. No SD/NAND write occurred; no UVC module/hook/native filesystem function was activated.

## Original contract

Exact Ghidra queries for Fsys_Mount, Fsys_GetDriveInfo, Fsys_GetDeviceInfo and fsys_GetDeviceId are retained under `artifacts/tools/rea/fsys-media-association-e0222`. Original Fsys_Mount copies the supplied device name into its drive record at+0x954. This provides a direct observational association, unlike interpreting opaque header bytes. Fsys_GetDeviceInfo itself allocates a temporary record, configures a driver and invokes service callbacks; despite its name, it is not a passive memory query and was not called.

The observer was extended to read that bounded NUL-terminated device string as hex, resolve native globals through actual GOT entries each sample and retain the prefix check. Writes remain confined to four fresh own RAM paths. The builder now requires a new artifact output directory and refuses to replace an existing manifest.

## Repeated physical capture

Exact observer:10896bytes, SHA-256 `45bfbb834e3cc17ceaf77f3ac5f7b07fc525b0c0fe366e65ca1e24315d6a1d90`, `artifacts/native/fsys-observer-e0222/native_fsys_observer.elf`. Fresh repeat PID760,40nominal seconds/21samples. Ready sample in MSC was verified before instructing the switch. User then switched ordinary PCRemote and returned MSC after the observation period. Windows native ILCE-6400/0CAA StatusOK was observed. One collection attempt preceded MSC availability; subsequent reconnect succeeded.

Complete receipt gives:

| Native letter | Original mount device string | Physical namespace verification |
| --- | --- | --- |
| A | `/dev/mmca` | Block device250:10, SD/MMC path |
| B | `/dev/nflasha23` | Block device252:23, internal flash partition |

Read-only `ls -l` verified those two existing nodes. `/proc/partitions` uses names mmca10/mmca10p1, but `/dev/mmca10` and `/dev/mmca10p1` nodes do not exist here; do not substitute those paths for the native mount string. The diagnostic journal must target only the identified SD-backed native A: path, never B:/internal flash. This identifies the device association; it is not a file-create or durability proof.

Evidence directory: `artifacts/hardware/uvc-sd-device-map-e0222-repeat-20261109_143859/`, including observer.log, run.json, ready.log, final status/modules and device-nodes.txt. Latest-path pointer: `artifacts/hardware/uvc-sd-device-map-e0222-latest.txt`. The earlier40-second attempt was interrupted at chat level by the user's absence and is not substituted for this repeated receipt.

## Final state and limits

Complete receipt recovered; only repeat's own binary/log/receipt/stderr paths removed. PID149 TracerPid0, no usbg_video module, debugger responsive, camera MSC. No ptrace was requested by this observer; direct pread only. Sequential unlocked reads are not an ownership token; the prefix check does not verify the complete live library. Native A:/B: associations can change with other devices/firmware, so future writes must validate the active association again rather than rely on a global hardcoded drive letter.

Small SD journal authorization remains valid. Next: verify exclusive/non-overwriting creation through the existing initialized filesystem service and bounded write/flush/readback, then restart survival, before another configured UVC activation. No journal has yet been written. Do not initialize a parallel filesystem instance or mount raw media for writing alongside Sony.
