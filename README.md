# Sony a6400 firmware execution research

An evidence-backed execution environment and homebrew research project for the **Sony ILCE-6400**. We investigate original ARM/Thumb code, Linux and Sony service contracts, and physical camera behavior. A complete camera emulator and a finished sensor-to-UVC webcam are still goals.

**Host-written navigation, rendering, UI and camera decisions are not firmware compatibility.** Custom graphics, static test patterns and passing fixtures demonstrate only their own bounded contracts.

## Research status

**2026-11-10 | [E0314](docs/evidence/0314-gpes-bar-irq-contract-engine-model.md).** Read-only camera observations and original driver analysis establish the GPES BAR/IRQ and event-wait contracts. An opt-in engine model advances original guest code out of the event loop and to a second guest signal, under explicitly labelled command-result assumptions. Cross-context completion and guest condition-variable release remain unresolved; `THREAD_APP` and the view tier have not started. **No verified emulator GUI frame or OSD mapping.** The recorded full suite passes 880 tests.

![Research status: demonstrated results and remaining boundaries](docs/images/research-status.svg)

These are independent, dated results, not a percentage of firmware compatibility. Offline original-code execution, physical camera observations and authored demonstrations are identified separately below. All results are bounded by the linked evidence and experiment policies.

| Area / evidence type | Demonstrated | Remaining boundary |
| --- | --- | --- |
| Firmware execution - offline | Original ARM/Thumb code reaches `im.elf` and the first event-dispatch phase | Full camera boot is unproven; 1/8 task phases observed and 0/198 static plugin definitions initialized - [status data](tools/research/a6400_status_data.py) |
| UIPC / USB - offline | Original VBUS callback delivery/completion; state-valid OTG input reaches UsbControl and produces a new futex wake | Wake-only, no FSM transition; missing MWF `0x0A4000` producer remains unresolved - [E0304](docs/evidence/0304-preboundary-usb-injection-and-vbus-delivery.md), [E0310](docs/evidence/0310-team-cycle-buspower-lane-and-second-path.md), [E0311](docs/evidence/0311-usbcontrol-wake-only-gles-models-and-grm-wait.md) |
| Display - physical capture + offline contract | Camera OSD A/B confirmed as 640x480 RGBA4444; captured PlayMemories MSC screen; hash-checked read-only flash namespaces let offline startup advance | `THREAD_APP`/view tier not started; emulator OSD A/B unmapped and no verified GUI frame - [E0298](docs/evidence/0298-safe-osd-capture-and-sugilite-correction.md), [E0314](docs/evidence/0314-gpes-bar-irq-contract-engine-model.md) |
| GPU / GPES - physical observation + offline model | DMP SMAPH-S30 identity; BAR/IRQ and event-wait contracts decoded; opt-in engine experiment reaches a second original guest signal | Result-bit assumptions remain labelled; keyed context completion and guest condvar release unresolved. Rasterizer still lacks verified draw/shader semantics - [E0313](docs/evidence/0313-readonly-physical-gpes-bar-and-grm-state.md), [E0314](docs/evidence/0314-gpes-bar-irq-contract-engine-model.md) |
| PTP liveview - physical | A sensor JPEG, 1024x680, transferred in original PC Remote mode | Composite PTP frame delivery and simultaneous UVC/PTP operation remain unproven - [E0151](docs/evidence/0151-pc-remote-liveview-and-uvc-verified.md), [E0296](docs/evidence/0296-snapshot2-reconnect-budget-teardown.md) |
| UVC - authored pattern, physical transport | Static MJPEG 1280x720 at 29.9592 FPS over 180 frames | Sensor feeder remains unwired; static frames do not demonstrate sensor streaming - [E0143](docs/evidence/0143-uvc-720p-test-transport-and-30fps-verified.md), [E0243](docs/evidence/0243-opt-in-producer-admission-module.md) |
| Composite USB - physical | PTP/UVC children enumerated; E0289 retained enumeration through liveview with a clean teardown | E0296 later became unresponsive after liveview despite stable enumeration; reliable lifecycle and frame delivery remain open. This workstream is paused - [E0289](docs/evidence/0289-e0288-keeps-device-enumerated.md), [E0296](docs/evidence/0296-snapshot2-reconnect-budget-teardown.md) |
| Native monitor / storage - physical + offline checks | Original help and fixed `IFSYS getdriveinfo A` replies verified; A: identified as SD | General command behavior and competing-consumer ownership remain open; diagnostic SD journal remains unwritten - [E0234](docs/evidence/0234-ordinary-pcremote-ifsys-query-answered.md), [E0222](docs/evidence/0222-physical-sd-volume-device-association.md) |
| Custom menu - authored demonstration | Our interface drawn on the camera display | Does not establish original Sony menu behavior, navigation or settings - [photo](docs/images/framebuffer-camera-menu.png) |
| Validation - local tests | 880 tests recorded passing in E0314 | Bounded contracts, not full compatibility or physical deployment safety - [E0314](docs/evidence/0314-gpes-bar-irq-contract-engine-model.md) |

The tested syscall, filesystem, mapping and linker cases are limited contract checks, not complete subsystem implementations. Firmware inventory counts describe research scope, not executable compatibility; see [status data](tools/research/a6400_status_data.py). Historical USB/liveview findings are retained in the [archived status narrative](docs/archives/research-status-through-e0298.md) and [roadmap](docs/ROADMAP.md).

## Current work

Continue offline from E0314's GPES dependency chain:

1. Resolve cross-thread/keyed `0x820E` completion through the driver-resolved context pointer. IRQ acknowledgement alone does not complete a guest context.
2. Identify the original guest condition-variable release path for TID1011 (`0x99E34`), then observe whether RM/INFRA startup creates `THREAD_APP` and the view tier.
3. Continue tracing the real USB MWF producer. The verified power notification and the OTG wake do not establish a USB FSM transition.

The engine model is opt-in; its command-result bit and readiness experiments are assumptions, not physical verification of the entire command protocol. Preserve explicit boundaries and default baselines. Fresh-path tzset remains unresolved. Firmware content comes from hash-checked read-only inputs; no synthetic messages, host-called callbacks or substitute screen establish compatibility. Physical composite/liveview work remains paused; do not repeat E0297's `/dev/stream` capture method.

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
