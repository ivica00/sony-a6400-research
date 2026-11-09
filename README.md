# Sony a6400 firmware execution research

An evidence-backed execution environment and homebrew research project for the **Sony ILCE-6400**. We investigate original ARM/Thumb code, Linux and Sony service contracts, and physical camera behavior. A complete camera emulator and a finished sensor-to-UVC webcam are still goals.

**Host-written navigation, rendering, UI and camera decisions are not firmware compatibility.** Custom graphics, static test patterns and passing fixtures demonstrate only their own bounded contracts.

## Status

![Research status: measured milestones and remaining boundaries](docs/images/research-status.svg)

These are independent, dated research results, not a percentage of firmware compatibility. **Updated 2026-11-09, through E0239.** Latest boundaries: [E0239](docs/evidence/0239-offline-uvc-frame-metadata-contract.md) adds the first offline UVC contract (bounded JPEG SOF dimension parser, 15 host cases, ARM compile; not yet wired into `IOCTL_UVC_UPDATE`). [E0238](docs/evidence/0238-8.3-journal-rebuild-offline.md) rebuilds the collector with the 8.3 target `A:/A6400J.DAT` (21 ARM admission, 19 mocked collector cases, 624 tests) but it is not physically deployed. [E0237](docs/evidence/0237-offline-path-contract-8.3-rejection.md) proved the earlier `0x80000041` was the 8.3 path normalizer, not an empty letter table. [E0236](docs/evidence/0236-physical-journal-path-and-reboot-fault.md) records the refused write and the intermittent PC Remote self-reboot that stops physical collector sessions. No SD journal write and no UVC activation.

| Area | Demonstrated (bounded) | Remaining boundary / evidence |
| --- | --- | --- |
| Guest emulation | `im.elf` entry reached; event phase 1/8; 36/36 ARM syscalls, 20/20 ext2, 14/14 mmap, 13/13 uIPC, 12/12 linker, 8/8 event dispatch | Full boot is not claimed; 1/8 task phases and 0/198 static plugin definitions initialized — counts from [status data](tools/research/a6400_status_data.py) |
| Firmware surface | 474 inventoried ELFs; 74,134 exported function symbols (63,992 unique); 8,658 unique imports; 289 functions with retained static analysis | Internal/static functions and unused tables remain unenumerated; 10/37 drivers, 28/88 device nodes, 7/30 partitions, 15/22 boot mounts — counts measured locally with [elf_inventory](tools/research/elf_inventory.py); the inventory artifact is excluded from publication |
| Custom menu (framebuffer) | A custom interface is visibly drawn on the camera display | **Host-written; not firmware compatibility, original-menu navigation or settings proof** — [framebuffer photo](docs/images/framebuffer-camera-menu.png) |
| PTP liveview | Sensor JPEG 1024×680 transferred over PTP in PC Remote | PTP control transactions, simultaneous UVC/PTP control and teardown remain unproven — [E0151](docs/evidence/0151-pc-remote-liveview-and-uvc-verified.md) |
| UVC transport | Static MJPEG 1280×720 at 29.9592 FPS over 180 frames | Static pattern only; sensor feeder unwired — [E0143](docs/evidence/0143-uvc-720p-test-transport-and-30fps-verified.md), [E0239](docs/evidence/0239-offline-uvc-frame-metadata-contract.md) |
| Composite USB | Windows parent + PTP + UVC children enumerated with video disabled | Later runs report parent Code 10; teardown and recoverable observation unresolved — [E0207](docs/evidence/0207-first-physical-composite-pcremote-enumeration.md), [E0208](docs/evidence/0208-windows-90s-parent-code10-and-feeder-boundary.md) |
| Native monitor | Bounded help command and one fixed `IFSYS getdriveinfo A` query returned original replies | General command results, per-event mode timing and competing-consumer ownership remain open — [E0227](docs/evidence/0227-physical-native-monitor-help-roundtrip.md), [E0234](docs/evidence/0234-ordinary-pcremote-ifsys-query-answered.md) |
| Native storage / journal | A: mapped to SD `/dev/mmca`; 8.3 journal path validated offline | Journal unwritten; PC Remote self-reboot blocks physical sessions — [E0222](docs/evidence/0222-physical-sd-volume-device-association.md), [E0237](docs/evidence/0237-offline-path-contract-8.3-rejection.md), [E0238](docs/evidence/0238-8.3-journal-rebuild-offline.md) |
| Validation | 624 tests; 21 compiled ARM admission cases; 19 mocked collector cases | Bounded checks, not every physical path — [E0238](docs/evidence/0238-8.3-journal-rebuild-offline.md) |

### Emulation (guest contracts)

The bounded guest executes original ARM/Thumb code through verified CPU, Linux and hardware contracts. It reaches the `im.elf` entry point and the first event-dispatch phase, with complete contract coverage for the tested syscalls, ext2 surface, mmap, uIPC, NPTL threads and linker paths. It does **not** boot the camera: 1 of 8 task phases is observed and none of the 198 static plugin definitions is initialized. Instruction counts and passing fixtures are not a timing model, complete machine or deployment-safety proof.

### Physical modes: UVC, PTP, composite, native monitor, journal

Physical work is deliberate and evidence-bounded. Static 720p UVC transport and a 1024×680 PTP liveview JPEG have been demonstrated separately; the shared composite session enumerates on Windows but the parent later reports Code 10, teardown is unresolved and the sensor feeder is not connected. The native monitor answered a fixed `IFSYS` query in an ordinary PC Remote cycle with a verified receipt. The authorized small SD journal is still unwritten: the 8.3 path and collector are ready offline, but an intermittent PC Remote self-reboot stops further collector sessions until the cause is understood.

### Host-written artifacts (not firmware compatibility)

The custom menu drawn on the camera display and the static UVC test pattern are artifacts we wrote. They show framebuffer/display-surface writing and static transport respectively; they do not establish original Sony menu behavior, live sensor frames, settings labels or application compatibility.

## Current work

Offline UVC/PTP implementation and validation. The next bounded step is the producer admission contract: validate the source span and decoded dimensions (the [E0239](docs/evidence/0239-offline-uvc-frame-metadata-contract.md) parser), wait for the destination slot to be free, enforce per-slot frame lengths and only then wire the parser into `IOCTL_UVC_UPDATE`. Physical collector and UVC sessions stay stopped until the PC Remote reboot cause is understood; the camera is used only for quick read-only USB debugger checks. See the [UVC/PTP handoff](docs/UVC_PTP_STATUS.md).

## Working with the project

Use legally acquired local firmware and device captures; proprietary inputs and generated artifacts are excluded from Git. A source clone alone does not reproduce physical experiments. The existing Windows environment is not a dependency lock or a verified fresh-install recipe.

Run ordinary tests from the project root; no camera is required:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -q
```

See [CONTRIBUTING.MD](CONTRIBUTING.MD) for contributions and [AGENTS.MD](AGENTS.MD) for agent rules. Device diagnostics and deployment are deliberate operations, never incidental test steps.

| Path | Contents |
| --- | --- |
| `src/a6400/` | Bounded guest execution and verified contracts |
| `tools/research/` | Analysis, original-code probes and experiment tools |
| `tools/native_camera/` | Authored native helpers and module sources |
| `tests/` | Contract and regression checks |
| `docs/evidence/` | Claims, identities, observations and limitations |
| `legacy/` | Historical HLE/UI prototypes; not firmware compatibility evidence |
| `firmware/`, `backups/`, `artifacts/` | Local preserved inputs and generated results; excluded from publication |

## Research records

- [Evidence index and record format](docs/evidence/README.md)
- [Live camera / emulator workflow](docs/LIVE_CAMERA_EMULATOR_WORKFLOW.md)
- [Dependency analysis workflow](docs/DEPENDENCY_WORKFLOW.md)
- [Roadmap](docs/ROADMAP.md)
- [Archived README and earlier milestones](docs/archives/README-2026-11-09.md)

## Scope and attribution

Independent research; not affiliated with or endorsed by Sony. Sony, a6400 and ILCE-6400 are their respective owners' trademarks. Firmware packages, extracted proprietary binaries, device backups and raw RAM captures remain local. Custom graphics, passing fixtures and instruction counts do not establish complete firmware compatibility or deployment safety. Unknown behavior must remain explicit.
