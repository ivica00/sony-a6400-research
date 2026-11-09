# Sony a6400 firmware execution research

An evidence-backed execution environment and homebrew research project for the **Sony ILCE-6400**. We investigate original ARM/Thumb code, Linux and Sony service contracts, and physical camera behavior. A complete camera emulator and a finished sensor-to-UVC webcam are still goals.

## Status

![Research status: measured milestones and remaining boundaries](docs/images/research-status.svg)

These are independent research milestones, not a percentage of firmware compatibility. Figures are dated evidence results, not live CI badges. **Updated 2026-11-09, through E0226.**

| Area | Demonstrated | Remaining boundary / evidence |
| --- | --- | --- |
| Physical display | Custom interface drawn on the camera display | Original Sony menu modification and all displayed settings are not established by the photo below |
| UVC transport | Static MJPEG, 1280 × 720; 29.9592 FPS over 180 frames | Live sensor integration unfinished — [E0143](docs/evidence/0143-uvc-720p-test-transport-and-30fps-verified.md) |
| Composite USB | Windows parent + PTP + UVC children simultaneously OK, Code 0 | Camera froze; teardown unconfirmed, recovered by restart. Video disabled; no PTP transaction proof — [E0210](docs/evidence/0210-original-endpoint-number-conflict.md) |
| Monitor output | 30,115 bytes preserved before acknowledgement; wrong cursor rejected | Competing-consumer race remains; no monitor command submitted — [E0226](docs/evidence/0226-preserved-monitor-output-acknowledgement.md) |
| Native storage | A: mapped to SD `/dev/mmca`; B: is internal flash | Authorized SD journal not yet written — [E0222](docs/evidence/0222-physical-sd-volume-device-association.md) |
| Validation | Last recorded full suite: 617 passing; 8 additional compiled ARM admission cases in E0226 | Recorded checks, not a claim that every physical path is safe — [E0225](docs/evidence/0225-physical-readonly-monitor-output-capture.md), [E0226](docs/evidence/0226-preserved-monitor-output-acknowledgement.md) |

### On-camera framebuffer writes

Our custom interface is visibly drawn on the physical a6400 display. This demonstrates framebuffer/display-surface writing. The photo does not prove original-menu navigation or the functionality of labels such as “30m Limit Unlocked”.

![Custom interface written to the physical Sony a6400 framebuffer](docs/images/framebuffer-camera-menu.png)

### UVC mode: demonstrated, unfinished

The test pattern below was used for physical 720p UVC transport verification. FFmpeg decoded the received JPEG; DirectShow measured approximately 30 FPS. **This is a static test pattern, not live sensor output.** The later shared PC Remote/UVC/PTP work has demonstrated joint Windows enumeration, but reliable teardown and sensor streaming remain open.

![Sony a6400 UVC 720p at 30 FPS static test pattern](docs/images/uvc-720p-test-pattern.png)

## Current work

Establish a bounded, non-writing monitor probe with fresh parser checks, continuous preserve-before-ack output collection and an explicit result. The monitor wrapper's return value is not command completion. The output reader still depends on USB and is not a restart-surviving recovery channel. Review configured-session teardown and recoverable observation before another physical UVC activation. Start with [E0226](docs/evidence/0226-preserved-monitor-output-acknowledgement.md) and the [UVC/PTP handoff](docs/UVC_PTP_STATUS.md).

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
