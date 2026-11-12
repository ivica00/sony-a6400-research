# Sony a6400 · BIONZ X (`CXD90045`) Research & Execution Platform

An evidence-backed **clean-room research platform** for the Sony ILCE-6400 (a6400) and
the Sony BIONZ X `CXD90045` camera family: an offline original-code execution
environment, a decoded hardware/OS contract reference, and a low-latency USB / UVC
streaming workstream you can contribute to **without owning a camera**.

Every result is labelled by what it actually demonstrates — offline execution,
read-only observation, authored demonstration, or a physically verified operation.
Nothing here is a percentage of "firmware compatibility".

## Project pillars

| Pillar | What it means | Current state |
| --- | --- | --- |
| **1 · Clean-Room Firmware Emulator (`CXD90045`)** | Execute original `im.elf`, kernel/bootloader, OSAL/UIPC, GPES GPU, and USB FSM code offline with no hardware risk | Bounded, opt-in contracts. `im.elf` reaches startup and event dispatch; the updater kernel boots to `ttyAM0` console + `cramfs` rootfs; full camera boot is **not** proven |
| **2 · Low-Latency Monitoring & Native UVC (`CinemaHUD` + Track A/B)** | Glass-to-glass latency measurement and control with the camera's own USB transport | **Track A** (pipelined PTP + Android SGSR 1.0) has a physically verified liveview link. **Track B** (composite UVC push) enumerates with clean teardown but still stalls on EP0 `SET_CUR` status-OUT |
| **3 · Multi-Device BIONZ X Platform Support** | Share SoC/kernel contracts across a6400, ZV-E10, a6100, a6600, and a7 III | Typed `TargetProfile` registry with a verified a6400 profile, a ZV-E10 reference chain, and explicit stubs for the rest |

## Recent breakthroughs

- **Offline CXD90045 Kernel & Boot Bring-Up ([E0414](docs/evidence/0414-nflasha-readonly-device-check-and-boot-area-dumps.md)–[E0424](docs/evidence/0424-cxd90045-pl011-primecell-and-ash-shell.md)):**
  Decoded the read-only `nflashaB0` (`EXBL` / Sony `DGU5`) loader and `nflasha1`/`nflasha3`
  boot sets (`0x00000DA9` / `ARM-CXD900X0`). Modelled the GIC + `0xF2403000` timer IRQs,
  `__ex_table` fault recovery, CRCDC clock path (`0xF2A31000`), and bidirectional PL011
  UART (`0xF2000000` with PrimeCell IDs) in Unicorn. The updater kernel now passes
  `calibrate_delay`, mounts `cramfs`, enables `console [ttyAM0]`, and captures **52,976
  bytes** of live serial boot + exception-monitor output (next: decode Sony's
  `0x60103000` cmdline override format so `init=/bin/ash` takes effect).
- **Persistent USB Debugger v2 & WinUSB Preflight ([E0400](docs/evidence/0400-usb-debugger-and-runtime-probe-infra.md)–[E0405ab](docs/evidence/0405ab-device-desc-builder-and-msos2-subset.md)):**
  Protocol v2 (`dmesg`, CRC-checked warm-reboot `klog` ring, `usb-state`, `recover`) runs
  persistently in Mass Storage without SD or battery pulls. Offline WinUSB / MS OS 2.0
  contracts, the dynamic `bcdUSB` builder (`0x602bb988`), the `gadgetcore+0x84` mode gate,
  and a RAM-only `MSFT100 -> MSFT20` round-trip are verified.
- **Track B Composite UVC Teardown & EP0 Root Cause ([E0352](docs/evidence/0352-offline-teardown-soft-disconnect-fix.md)–[E0399](docs/evidence/0399-runb22-deferred-restore-and-status-capture.md)):**
  Unconfigure-first soft-disconnect and bounded park-recovery restore Mass Storage cleanly
  without battery pulls. `P1` confirms 29.8 FPS DMM JPEG frames under live PTP; hardware
  ETW + RAM-ring runs narrowed the `RenderStream` timeout to the EP0 `SET_CUR` status-OUT
  stage and deferred disconnect restore.
- **BCM4339 Wi-Fi / BT Surface ([E0406](docs/evidence/0406-bcm4339-wifi-bt-tuning-surface-readonly.md), [E0408](docs/evidence/0408-clm-blob-and-wlan-baseline.md)):**
  Static Wi-Fi/BT firmware, kernel modules, and CLM blobs are hash-identified offline
  against ZV-E10.

Recorded suite: 1476 tests. Each result is bounded by its own evidence record; no UVC
frame, no control write, and no full firmware boot is claimed.

![Research status: demonstrated results and remaining boundaries](docs/images/research-status.svg?v=a3b01929c7c7)

### Subsystem status matrix

| Subsystem | Demonstrated & verified | Remaining boundary | Evidence |
| --- | --- | --- | --- |
| Firmware & kernel — offline | `im.elf` reaches event dispatch; updater kernel boots through `calibrate_delay`, `cramfs` mount, and live `ttyAM0` serial capture (52,976 B) | Full camera boot unproven; Sony `0x60103000` cmdline override format still to decode for `/bin/ash`; 1/8 task phases | [E0424](docs/evidence/0424-cxd90045-pl011-primecell-and-ash-shell.md), [status data](tools/research/a6400_status_data.py) |
| UIPC / USB FSM — offline | MWF dispatch, ObjMsg wire layout, opt-in sync callback delivery (`h4109` runs to completion) | `h4109`/`h4110` packet payload format and downstream post path unmodelled | [E0327](docs/evidence/0327-mwf-objmsg-wire-format.md), [E0332](docs/evidence/0332-sync-callback-delivery-first-invocation.md) |
| Host enumeration — offline | 173-byte UVC+PTP descriptor decoded; `SET_CONFIGURATION`/endpoint selection modelled; ObjMsg reaches FSM `0x13` | Inbound `SET_CONFIG` not yet delivered end-to-end on the sync lane | [E0337](docs/evidence/0337-emulator-uvc-ptp-preparation-and-0a4002-broadcast.md) |
| Display / GPU — physical + offline | Camera OSD A/B confirmed 640×480 RGBA4444; GPES BAR/IRQ contracts decoded; opt-in engine reaches second guest signal | Keyed `0x820E` completion, guest condition release, OSD mapping, and rasterizer remain open | [E0298](docs/evidence/0298-safe-osd-capture-and-sugilite-correction.md), [E0314](docs/evidence/0314-gpes-bar-irq-contract-engine-model.md) |
| PTP liveview — physical | Original PC Remote delivers 1024×680 sensor JPEGs; foreign `GET_JPEG` sees DMM frames at 29.8 FPS under load | Simultaneous UVC + PTP with reliable teardown not yet demonstrated | [E0349](docs/evidence/0349-p1-foreign-get-jpeg-succeeds-in-pc-remote.md), [E0151](docs/evidence/0151-pc-remote-liveview-and-uvc-verified.md) |
| Composite USB / UVC — physical | Composite enumerates (`MI_00` PTP + `MI_01` Camera) with clean MSC teardown; ETW + RAM-ring isolated EP0 `SET_CUR` status-OUT divergence | DirectShow `RenderStream` times out; deferred workqueue restore + status-stage hook next | [E0350](docs/evidence/0350-trackb-transport-enumerates-but-renderstream-fails.md), [E0398](docs/evidence/0398-runb21-status-stage-and-disconnect-verdict.md) |
| USB Debugger v2 — physical + offline | Persistent MSC debugger with `dmesg`, warm-reboot `klog` ring, `usb-state`, `recover`; RAM-only `MSFT20` round-trip verified | WinUSB composite vendor interface (`B2/B3`) and `bcdUSB` override not yet deployed | [E0401](docs/evidence/0401-usb-debugger-v2-ring-recover-and-mode-boundary.md), [E0405ab](docs/evidence/0405ab-device-desc-builder-and-msos2-subset.md) |
| UVC transport — authored pattern | Static MJPEG 1280×720 @ 29.96 FPS (180 frames); ZV-E10 UVC chain hash-pinned as reference | Sensor feeder unwired; ZV-E10 stack not enabled on a6400 | [E0143](docs/evidence/0143-uvc-720p-test-transport-and-30fps-verified.md), [E0321](docs/evidence/0321-zve10-uvc-enablement-manifest.md) |
| Multi-device targets | Typed a6400 profile with sourced symbols, UIPC queues, and USB identity; ZV-E10 reference chain | Only a6400 is a verified execution target | [`src/a6400/targets/`](src/a6400/targets/catalog.py), [ADDING_A_BIONZX_CAMERA](docs/ADDING_A_BIONZX_CAMERA.md) |
| Validation — local suite | 1476 tests pass offline (structure, target profiles, emulator contracts, docs sync) | Bounded contracts, not compatibility or deployment safety | [tests/](tests/README.md) |

## How to contribute (no camera required)

Roughly 90% of the open work is offline Python: decoders, emulator contracts, tests, and documentation.

**Top 3 open tasks right now**

1. **Sony `0x60103000` cmdline override format** — `setup_arch()` rejects standard ATAGS/raw cmdlines (`invalid cmdline override @ 0x60103000`). Decode the validator around `0x603D98EE` so `init=/bin/ash` boots to an interactive shell over `ttyAM0`.
2. **`h4109`/`h4110` packet payload for the `UsbControl` FSM** — decode the sync-lane packet format and carry an inbound `SET_CONFIG` to a real FSM observation ([`usb_sync_callback.py`](src/a6400/execution/usb_sync_callback.py)).
3. **GPES keyed `0x820E` completion** — resolve the cross-thread completion through the driver-resolved context pointer and guest condition release ([`guest_gles.py`](src/a6400/execution/guest_gles.py)).

More guides: [Contributing to UVC / PTP](docs/CONTRIBUTING_UVC_PTP.md) · [Adding a BIONZ X camera](docs/ADDING_A_BIONZX_CAMERA.md) · [Consolidated UVC/PTP status](docs/UVC_PTP_STATUS.md).

## Quick start

Python 3.10+ with dependencies from [`requirements.txt`](requirements.txt) (no camera required):

```powershell
# Windows (PowerShell)
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m unittest discover -s tests -q
```

```bash
# Linux / macOS
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -q
```

| Check | Command |
| --- | --- |
| Full offline suite | `python -m unittest discover -s tests -q` |
| Structure + targets + docs sync | `python -m unittest tests.test_repository_layout tests.test_target_profiles tests.test_research_status_sync -v` |
| Status card is current | `python -m tools.research.render_research_status --check` |
| Interface launchers (Windows) | [`scripts/`](scripts/) (`launch_cinemahud_ptp.bat`, `launch_cinemahud_android.ps1`, `launch_cinema_mpv.bat`, `start_camera_shell.bat`) |

Run first-party scripts as modules from the repository root (`python -m tools.research.<tool>`). Firmware, backups, and generated artifacts stay local and are excluded from Git.

## Repository map

| Path | Contents |
| --- | --- |
| `src/a6400/execution/` | Bounded guest execution, Unicorn machine, and verified OSAL/UIPC/USB/GPU contracts |
| `src/a6400/targets/` | `TargetProfile` schema, fail-closed validation, and multi-device registry |
| `src/a6400/debug/` | USB debugger protocol, ring buffer, and WinUSB transport |
| `tools/research/` | Analysis, original-code probes, experiment runners, and status-dashboard generator |
| `tools/native_camera/` | Authored native helpers, kernel-module sources, and UVC/PTP transport work |
| `probes/` | Bounded read-only ARM probe for other BIONZ X bodies |
| `tests/` | Contract, regression, and repository-structure checks |
| `docs/evidence/` | Dated claims, identities, observations, and limitations |
| `docs/` | Architecture, workflows, contributor guides, and status card |
| `android/`, `android-client-ref/` | Track A client and CinemaHUD reference client |
| `camera-daemon/` | Track B camera-side composite UVC push daemon |
| `firmware/`, `backups/`, `artifacts/` | Local preserved inputs and generated results (excluded from Git) |

## Epistemic and safety boundaries

- **Evidence policy:** Host-written navigation, rendering, UI, or camera decisions are **not** firmware compatibility. Every claim links to a dated record.
- **Zero flash modification:** No internal-flash writes, firmware installation, or boot changes are part of ordinary work.
- **Clean-room:** Original code owns application logic in fidelity experiments; unknown services stop with PC, arguments, and reason rather than fabricating success.
- **Physical scope:** Read-only observations are authorized; writes, mode switches, module loads, and teardown experiments require explicit scope. Bulk `/dev/mem` sweeps are banned ([AGENTS.MD](AGENTS.MD)).
- **Per-boot values:** Only `kallsyms` addresses are ASLR-free; library bases, fds, and DMM addresses change between boots.

## Research records & attribution

[Evidence index](docs/evidence/README.md) · [Architecture](docs/ARCHITECTURE.md) · [UVC monitor architecture](docs/ARCHITECTURE_UVC_MONITOR.md) · [Roadmap](docs/ROADMAP.md) · [Live camera / emulator workflow](docs/LIVE_CAMERA_EMULATOR_WORKFLOW.md) · [Contributing](CONTRIBUTING.MD) · [Repository layout](docs/REPOSITORY.md) · [Agent rules](AGENTS.MD) · [Archived README](docs/archives/README-2026-11-09.md)

Independent research; not affiliated with or endorsed by Sony. Sony, a6400, ILCE-6400, and BIONZ X are their respective owners' trademarks.
