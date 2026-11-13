# Sony a6400 Research & Emulator Platform

An open, evidence-backed research project for the **Sony a6400** (`ILCE-6400`, `CXD90045` chip).
We study how the camera's original software and Linux system work by running them safely
in an offline emulator and observing the real camera read-only—plus building low-latency
USB liveview and debugging tools.

**You don't need a camera to contribute.** Roughly 90% of the open work is offline Python.
Every result here is strictly labelled by what was actually shown (offline emulation,
read-only observation, or a real hardware test), and nothing is presented as a percentage
of "full firmware compatibility."

## Three main goals

| Goal | What it means | Current state |
| --- | --- | --- |
| **1 · Offline Firmware Emulator** | Run Sony's original camera software, bootloader, and Linux kernel on a PC with zero risk to hardware | Core camera software reaches startup and event dispatch; the updater Linux kernel boots to its serial console and root filesystem, though full camera boot is **not** yet reached |
| **2 · Low-Latency Liveview & USB Video (`CinemaHUD`)** | Stream video from the camera with minimal delay over USB | **Android/PTP liveview** works on real hardware. **Native USB webcam (UVC) mode** shows up on the host and disconnects cleanly, but video streaming still stalls during USB setup |
| **3 · Multi-Camera Support** | Share hardware and kernel knowledge across the a6400, ZV-E10, a6100, a6600, and a7 III | Typed device profiles exist for the a6400 (verified) and ZV-E10 (reference), with placeholders for the other models |

## Latest progress

- **Cross-Model BIONZ X Platform Map ([E0477](docs/evidence/0477-bionz-x-platform-map-13-updaters.md)–[E0482](docs/evidence/0482-three-stubs-gain-sourced-values.md)):**
  Thirteen official updaters unpacked offline: a6400, a6600, a6100A, ZV-E10, A7 III, A7C,
  A7R III, A7R IV, A7R IVA, A9, A9 II, ZV-1 and RX0 II. They run **nine kernels**, not thirteen:
  ZV-E10 and A7C put all 14,460 function symbols at the same address and differ in 9 data
  addresses, while a6400/a6600 share all 14,401 function symbols; a6100A/A7 III/A7R IVA share
  one symbol set but 4,033 of their 4,042 differing addresses are functions, so they are three
  separate kernels. The `av-cam` command table is a monotone ladder (285 records on the a6400,
  286 on the a6600 with exactly `0x413b` added, 337 on the ZV-E10/A7C). Six USB-side kernel
  symbols now resolve for every body **without a camera**, and for the a6400 the offline
  decode matches the existing live `/proc/kallsyms` read on all seven symbols. The
  `ilce_6100`, `ilce_6600` and `ilce_7m3` profiles stop being stubs and carry sourced values.
- **Offline Linux Kernel Boot ([E0414](docs/evidence/0414-nflasha-readonly-device-check-and-boot-area-dumps.md)–[E0461](docs/evidence/0461-cxd90045-pt-regs-scan-and-live-ash.md)):**
  Decoded the camera's first-stage bootloader and updater boot images, and emulated the
  interrupt controller, system timers, clock hardware, and serial console. The updater
  Linux kernel now boots through delay calibration, mounts its compressed root filesystem,
  captures **52,976 bytes** of live serial output, and accepts Sony's custom boot-argument
  override. User-space memory faults are now routed cleanly into the kernel without stack
  corruption, though the kernel's fault handler does not yet resume the first user program
  (so an interactive shell is not open yet).
- **Persistent USB Debugger ([E0400](docs/evidence/0400-usb-debugger-and-runtime-probe-infra.md)–[E0405ab](docs/evidence/0405ab-device-desc-builder-and-msos2-subset.md)):**
  A v2 USB debugger runs in Mass Storage mode, letting us read kernel logs (including
  logs preserved across warm reboots), check USB state, and recover cleanly without pulling
  the SD card or battery. Offline contracts and a safe RAM-only round-trip check for
  automatic Windows WinUSB driver binding are also verified.
- **USB Video (UVC) Teardown & Stall Diagnosis ([E0352](docs/evidence/0352-offline-teardown-soft-disconnect-fix.md)–[E0399](docs/evidence/0399-runb22-deferred-restore-and-status-capture.md)):**
  Fixed the USB disconnect sequence so the camera returns to Mass Storage mode cleanly
  without needing a battery pull. Live tests confirmed the camera can serve 29.8 FPS JPEG
  frames alongside PTP, and USB packet/kernel traces narrowed the remaining DirectShow
  streaming timeout down to the final status stage of a USB control handshake.
- **Wi-Fi & Bluetooth Chip Analysis ([E0406](docs/evidence/0406-bcm4339-wifi-bt-tuning-surface-readonly.md), [E0408](docs/evidence/0408-clm-blob-and-wlan-baseline.md)):**
  Identified and cataloged the Broadcom Wi-Fi/Bluetooth firmware, kernel drivers, and
  regulatory configuration blobs offline against the ZV-E10.

## Status overview

Recorded suite: 1531 tests. Each result is bounded by its own dated evidence record; no
UVC video frame, no flash write, and no full firmware boot is claimed.

![Research status: demonstrated results and remaining boundaries](docs/images/research-status.svg?v=3bfe86f4a267)

### Subsystem status

| Subsystem | What works today | What's still missing | Evidence |
| --- | --- | --- | --- |
| **Offline firmware & kernel** | Main camera binary reaches event dispatch; updater Linux kernel boots to its serial console (52,976 B captured) and mounts rootfs; user faults reach the kernel cleanly | Kernel page-fault handler does not yet resume user-space programs (`/bin/ash`); full camera boot unproven | [E0430](docs/evidence/0430-cxd90045-abt-sp-isolation-and-live-ash.md), [status data](tools/research/a6400_status_data.py) |
| **Internal messaging & USB state** | Message routing and synchronous kernel-to-user callbacks run to completion offline | Remaining callback packet format is still unknown | [E0327](docs/evidence/0327-mwf-objmsg-wire-format.md), [E0332](docs/evidence/0332-sync-callback-delivery-first-invocation.md) |
| **Offline USB enumeration** | Combined USB webcam + PTP descriptors decoded; configuration and endpoint selection modelled | Delivering an incoming USB configuration end-to-end on the sync lane | [E0337](docs/evidence/0337-emulator-uvc-ptp-preparation-and-0a4002-broadcast.md) |
| **Display & GPU** | Camera screen layout confirmed (640×480); GPU memory/interrupt contracts decoded offline | Completing the GPU wait signal and rendering a verified firmware frame | [E0298](docs/evidence/0298-safe-osd-capture-and-sugilite-correction.md), [E0314](docs/evidence/0314-gpes-bar-irq-contract-engine-model.md) |
| **PTP liveview (real camera)** | PC Remote streams 1024×680 sensor JPEGs; custom reader captures 29.8 FPS alongside PTP | Running UVC + PTP together with reliable teardown | [E0349](docs/evidence/0349-p1-foreign-get-jpeg-succeeds-in-pc-remote.md), [E0151](docs/evidence/0151-pc-remote-liveview-and-uvc-verified.md) |
| **Composite USB webcam (real camera)** | Camera appears as both PTP and Video device in Windows, and disconnects cleanly without a battery pull | DirectShow times out during the USB control handshake status stage | [E0350](docs/evidence/0350-trackb-transport-enumerates-but-renderstream-fails.md), [E0398](docs/evidence/0398-runb21-status-stage-and-disconnect-verdict.md) |
| **USB Debugger v2** | Persistent Mass Storage debugger for reading live/warm-reboot kernel logs and USB state | Deploying the always-on WinUSB vendor interface | [E0401](docs/evidence/0401-usb-debugger-v2-ring-recover-and-mode-boundary.md), [E0405ab](docs/evidence/0405ab-device-desc-builder-and-msos2-subset.md) |
| **Test UVC video pattern** | Streams a synthetic 720p MJPEG pattern at ~30 FPS; ZV-E10 USB video stack cataloged as reference | Wiring the live camera sensor feed | [E0143](docs/evidence/0143-uvc-720p-test-transport-and-30fps-verified.md), [E0321](docs/evidence/0321-zve10-uvc-enablement-manifest.md) |
| **Multi-camera profiles** | Verified a6400 profile and ZV-E10 reference chain | Only the a6400 is a verified execution target | [`src/a6400/targets/`](src/a6400/targets/catalog.py), [Adding a camera](docs/ADDING_A_BIONZX_CAMERA.md) |
| **Automated checks** | 1531 tests pass offline (structure, profiles, emulator contracts, doc sync) | Proves bounded contracts, not full compatibility | [tests/](tests/README.md) |

## How to help (no camera needed)

**Top 3 open tasks right now**

1. **Resume user-space programs after a page fault in the emulator** — trace why the
   kernel's page-fault handler falls into the Sony exception monitor instead of resuming
   the dynamic linker (`ld-linux.so.3`) so `/bin/ash` can start on the serial console.
2. **Decode the USB control callback packet format** — figure out the remaining message
   layout so an incoming USB configuration request reaches the firmware's USB state machine
   ([`usb_sync_callback.py`](src/a6400/execution/usb_sync_callback.py)).
3. **Unblock the GPU completion signal** — resolve the cross-thread wait condition in the
   emulated graphics driver so the display path can advance on its own
   ([`guest_gles.py`](src/a6400/execution/guest_gles.py)).

More guides: [Contributing to UVC / PTP](docs/CONTRIBUTING_UVC_PTP.md) · [Adding a BIONZ X camera](docs/ADDING_A_BIONZX_CAMERA.md) · [UVC/PTP progress log](docs/UVC_PTP_STATUS.md).

## Quick start

Requires Python 3.10+ and dependencies from [`requirements.txt`](requirements.txt) (no camera needed):

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

| What to check | Command |
| --- | --- |
| Full offline test suite | `python -m unittest discover -s tests -q` |
| Structure, profiles & doc sync | `python -m unittest tests.test_repository_layout tests.test_target_profiles tests.test_research_status_sync -v` |
| Status card matches data | `python -m tools.research.render_research_status --check` |
| Windows launchers | [`scripts/`](scripts/) (`launch_cinemahud_ptp.bat`, `launch_cinemahud_android.ps1`, `launch_cinema_mpv.bat`, `start_camera_shell.bat`) |

Run scripts as Python modules from the repo root (`python -m tools.research.<tool>`).
Firmware images, backups, and captured artifacts stay local and are excluded from Git.

## Repository layout

| Folder | What's inside |
| --- | --- |
| `src/a6400/execution/` | Offline ARM emulator and verified OS, USB, and GPU contracts |
| `src/a6400/targets/` | Device profiles and validation for supported Sony cameras |
| `src/a6400/debug/` | USB debugger protocol, log ring buffer, and WinUSB transport |
| `tools/research/` | Firmware analysis scripts, emulator runners, and status-card generator |
| `tools/native_camera/` | C helpers, kernel-module sources, and USB/UVC transport code |
| `probes/` | Safe, read-only ARM probe for other BIONZ X cameras |
| `tests/` | Automated contract, regression, and structure checks |
| `docs/evidence/` | Dated research logs with exact observations and boundaries |
| `docs/` | Architecture notes, workflows, and contributor guides |
| `android/`, `android-client-ref/` | Android liveview client (`CinemaHUD`) |
| `camera-daemon/` | Camera-side composite USB webcam daemon |
| `firmware/`, `backups/`, `artifacts/` | Local firmware dumps and generated outputs (never committed to Git) |

## Rules & safety

- **Honest claims only:** Host-written UI or camera logic is **not** firmware compatibility. Every claim links to a dated evidence record.
- **No flash writes:** Never modify internal camera flash, install custom firmware, or alter boot partitions.
- **Clean-room emulation:** Original firmware owns application logic; unknown OS services stop and report where they stopped instead of faking success.
- **Safe hardware checks:** Read-only camera inspection is allowed; writes, mode switches, and module loads require explicit scope. Bulk `/dev/mem` memory sweeps are banned because one caused a USB drop and reboot ([AGENTS.MD](AGENTS.MD)).
- **No hardcoded boot addresses:** Memory layouts and file descriptors change on every reboot and are never treated as fixed constants.

## Links & attribution

[Evidence index](docs/evidence/README.md) · [Architecture](docs/ARCHITECTURE.md) · [UVC monitor architecture](docs/ARCHITECTURE_UVC_MONITOR.md) · [Roadmap](docs/ROADMAP.md) · [Live camera / emulator workflow](docs/LIVE_CAMERA_EMULATOR_WORKFLOW.md) · [Contributing](CONTRIBUTING.MD) · [Repository layout](docs/REPOSITORY.md) · [Agent rules](AGENTS.MD) · [Archived README](docs/archives/README-2026-11-09.md)

Independent research; not affiliated with or endorsed by Sony. Sony, a6400, ILCE-6400, and BIONZ X are trademarks of their respective owners.
