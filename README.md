# Sony a6400 firmware execution research

An evidence-backed execution environment and homebrew research project for the **Sony ILCE-6400**. We investigate original ARM/Thumb code, Linux and Sony service contracts, and physical camera behavior. A complete camera emulator and a finished sensor-to-UVC webcam are still goals.

**Host-written navigation, rendering, UI and camera decisions are not firmware compatibility.** Custom graphics, static test patterns and passing fixtures demonstrate only their own bounded contracts.

## Research status

**2026-11-10 · [E0300](docs/evidence/0300-uipc-proxy-start-and-vbus-callback.md).** With the opt-in verified UIPC pool header, original firmware starts four proxy threads and executes and returns from the original USB VBUS callback. Callback completion, message ownership and synchronous delivery remain open; the emulator has no verified GUI frame or OSD mapping.

![Research status: demonstrated results and remaining boundaries](docs/images/research-status.svg)

These are independent, dated results, not a percentage of firmware compatibility. Offline original-code execution, physical camera observations and authored demonstrations are identified separately below. All results are bounded by the linked evidence and experiment policies.

| Area / evidence type | Demonstrated | Remaining boundary |
| --- | --- | --- |
| Firmware execution · offline | Original ARM/Thumb code reaches `im.elf` and the first event-dispatch phase | Full camera boot is unproven; 1/8 task phases observed and 0/198 static plugin definitions initialized — [status data](tools/research/a6400_status_data.py) |
| UIPC / USB · offline | Four proxy threads start; a verified VBUS message reaches the original callback, which returns and frees its message | Completion ownership/refcounts, synchronous delivery and the dynamic control queue remain incomplete — [E0300](docs/evidence/0300-uipc-proxy-start-and-vbus-callback.md) |
| Display · physical capture + offline contract | OSD A/B confirmed as 640×480 RGBA4444; safe ptrace capture shows the camera's PlayMemories MSC screen | Emulator OSD A/B remain unmapped; no emulator GUI frame. Sugilite is an internal buffer — [E0298](docs/evidence/0298-safe-osd-capture-and-sugilite-correction.md) |
| GPU · static analysis | DMP SMAPH-S30 identity established | Register, draw and shader semantics remain insufficient for a verified rasterizer; PICA200 assumptions are superseded — [E0298](docs/evidence/0298-safe-osd-capture-and-sugilite-correction.md) |
| PTP liveview · physical | A sensor JPEG, 1024×680, transferred in original PC Remote mode | Composite PTP frame delivery and simultaneous UVC/PTP operation remain unproven — [E0151](docs/evidence/0151-pc-remote-liveview-and-uvc-verified.md), [E0296](docs/evidence/0296-snapshot2-reconnect-budget-teardown.md) |
| UVC · authored pattern, physical transport | Static MJPEG 1280×720 at 29.9592 FPS over 180 frames | Sensor feeder remains unwired; static frames do not demonstrate sensor streaming — [E0143](docs/evidence/0143-uvc-720p-test-transport-and-30fps-verified.md), [E0243](docs/evidence/0243-opt-in-producer-admission-module.md) |
| Composite USB · physical | PTP/UVC children enumerated; E0289 retained enumeration through liveview with a clean teardown | E0296 later became unresponsive after liveview despite stable enumeration; reliable lifecycle and frame delivery remain open. This workstream is paused — [E0289](docs/evidence/0289-e0288-keeps-device-enumerated.md), [E0296](docs/evidence/0296-snapshot2-reconnect-budget-teardown.md) |
| Native monitor / storage · physical + offline checks | Original help and fixed `IFSYS getdriveinfo A` replies verified; A: identified as SD | General command behavior and competing-consumer ownership remain open; diagnostic SD journal remains unwritten — [E0234](docs/evidence/0234-ordinary-pcremote-ifsys-query-answered.md), [E0222](docs/evidence/0222-physical-sd-volume-device-association.md) |
| Custom menu · authored demonstration | Our interface drawn on the camera display | Does not establish original Sony menu behavior, navigation or settings — [photo](docs/images/framebuffer-camera-menu.png) |
| Validation · local tests | 782 tests passed on 2026-11-10 (19.561 s) | Tests cover bounded contracts; they do not prove complete compatibility or physical deployment safety — [E0300 validation context](docs/evidence/0300-uipc-proxy-start-and-vbus-callback.md) |

The tested syscall, filesystem, mapping and linker cases are limited contract checks, not complete subsystem implementations. Firmware inventory counts describe research scope, not executable compatibility; see [status data](tools/research/a6400_status_data.py). Historical USB/liveview findings are retained in the [archived status narrative](docs/archives/research-status-through-e0298.md) and [roadmap](docs/ROADMAP.md).

## Current work

Continue offline from E0300's explicit callback-completion boundary:

1. Decode original `finish_callback` queue state, ownership and reference counts. The VBUS callback already frees its message; completion must not free it again.
2. Verify the completion protocol and dynamic callback-control queue before extending the opt-in model.
3. Resolve synchronous callback delivery on queue `0x009c015b`, then observe whether original firmware advances toward the USB view and OSD mappings.

The early VBUS injection is a timing experiment, not verified physical event ordering. The host must not call the callback or draw a substitute screen. SMAPH-S30 rasterization remains a separate unresolved contract. Physical composite/liveview work remains paused; do not repeat E0297's `/dev/stream` capture method.

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
