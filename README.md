# Sony a6400 firmware execution research



An evidence-backed execution environment and homebrew research project for the **Sony ILCE-6400**. We investigate original ARM/Thumb code, Linux and Sony service contracts, and physical camera behavior. A complete camera emulator and a finished sensor-to-UVC webcam are still goals.



**Host-written navigation, rendering, UI and camera decisions are not firmware compatibility.** Custom graphics, static test patterns and passing fixtures demonstrate only their own bounded contracts.



## Status

**2026-11-10 — [E0300](docs/evidence/0300-uipc-proxy-start-and-vbus-callback.md):** corrected the opt-in UIPC pool options so original firmware starts four proxy threads. A verified VBUS notification now reaches and returns from the original USB callback. Callback completion/ownership and sync delivery remain explicit boundaries; **no emulator GUI frame or OSD mapping**. 782 tests pass. The E0298 display/GPU corrections below still apply.



![Research status: measured milestones and remaining boundaries](docs/images/research-status.svg)



These are independent, dated research results, not a percentage of firmware compatibility. **Updated 2026-11-09, through E0298.** Latest boundaries: offline + Mass Storage debugging only; **PTP is not reimplemented offline** — the original camera stack stays in charge. [E0298](docs/evidence/0298-safe-osd-capture-and-sugilite-correction.md) corrects the display claim: OSD A/B (640×480 RGBA4444) are the camera-verified display and were captured safely through im.elf's existing mapping (a PlayMemories MSC screen), while the 960×540 Sugilite buffer is internal. The GPU is DMP **SMAPH-S30**, not PICA200, so a bounded rasterizer is blocked without the private ISA. Boot gates `semtimedop` (syscall 312) and the observed `/setting/gps` mkdir now pass; the app reaches 312M instructions but still waits for a verified USB connect/MSC event before it instantiates the view/OSD tier. [E0297](docs/evidence/0297-live-display-contract-and-camera-reboot.md) records the failed `/dev/stream` OSD attempt; do not repeat it. [E0258](docs/evidence/0258-offline-descriptor-diff-pc-remote-vs-composite.md) shows the original PC Remote descriptor vs the composite with an **identical PTP interface**. [E0260](docs/evidence/0260-liveview-dispatch-and-wpd-selection.md)–[E0270](docs/evidence/0270-liveview-flag-internal-param.md) trace the app liveview path to **event 17** and `s_LiveViewStatus`. [E0271](docs/evidence/0271-f7-liveview-active-no-ptp-frame.md) is F7: the LCD **did show liveview**, yet the probe received **no PTP frame**. [E0272](docs/evidence/0272-f8-0-close-and-getobject-path.md)–[E0273](docs/evidence/0273-f8-1-liveview-handle-translation.md) resolve the liveview chain to MTP object `0xFFFFC001`. [E0274](docs/evidence/0274-f8-2-enumeration-gate-and-runbook.md)/[E0275](docs/evidence/0275-session-host-enum-gate.md) correlate stuck teardowns with host enumeration loss. [E0276](docs/evidence/0276-f8-5-clean-teardown-probe-no-wpd.md) F8-5: clean teardown, probe never connected. [E0277](docs/evidence/0277-liveview-start-disconnects-usb.md) liveview start played the Windows "device disconnected" sound. [E0278](docs/evidence/0278-f9-0-liveview-start-gadget-path.md)–[E0282](docs/evidence/0282-f9-2-mismatch-hypothesis.md) trace the UDC restart and the mitigation options. [E0283](docs/evidence/0283-f9-observation-children-vanish.md)/[E0284](docs/evidence/0284-f9-correction-wpd-trigger.md) correct the F9 interpretation. [E0285](docs/evidence/0285-p1-enumeration-no-liveview.md)/[E0286](docs/evidence/0286-p2-open-no-liveview.md) rule out WPD enumeration and open/close as triggers. [E0287](docs/evidence/0287-p3b-liveview-removes-device.md) shows the handshake › liveview › whole device disappears. [E0288](docs/evidence/0288-liveview-consistency-module.md) implements the opt-in liveview-consistency mitigation, audited 118 checks. [E0289](docs/evidence/0289-e0288-keeps-device-enumerated.md) is the first success: the composite stays enumerated through liveview, with a clean teardown and full receipt. [E0290](docs/evidence/0290-ptp-response-diagnostics.md)–[E0292](docs/evidence/0292-reconnect-retry-timing.md) add GetObject response diagnostics, identify the WPD COM shutdown at liveview start, and fix the reconnect retry. [E0293](docs/evidence/0293-wpd-list-empty-pnp-child-present.md) shows the PTP child in PnP while the WPD API list is empty; [E0294](docs/evidence/0294-setupapi-wpd-child-installed.md) confirms the MI_00 WPD install succeeded; [E0295](docs/evidence/0295-snapshot-timing-fix.md) fixes the snapshot timing. [E0296](docs/evidence/0296-snapshot2-reconnect-budget-teardown.md): enumeration stayed stable, but the camera became unresponsive after liveview (operator restarted it); the reconnect budget was too short, and the e0288 start-wrapper re-arm is the hang candidate. [E0259](docs/evidence/0259-msc-log-harvest.md) harvested retained logs read-only: no session logs survived; the camera was unchanged.



| Area | Demonstrated (bounded) | Remaining boundary / evidence |

| --- | --- | --- |

| Guest emulation | `im.elf` entry reached; event phase 1/8; 36/36 ARM syscalls, 20/20 ext2, 14/14 mmap, 13/13 uIPC, 12/12 linker, 8/8 event dispatch | Full boot is not claimed; 1/8 task phases and 0/198 static plugin definitions initialized — counts from [status data](tools/research/a6400_status_data.py) |

| Firmware surface | 474 inventoried ELFs; 74,134 exported function symbols (63,992 unique); 8,658 unique imports; 289 functions with retained static analysis | Internal/static functions and unused tables remain unenumerated; 10/37 drivers, 28/88 device nodes, 7/30 partitions, 15/22 boot mounts — counts measured locally with [elf_inventory](tools/research/elf_inventory.py); the inventory artifact is excluded from publication |

| Emulator display | OSD A/B (640×480 RGBA4444) verified as the camera display and captured safely via im.elf's existing mapping; read-only display contract, live GUI and headless capture; boot gates `semtimedop`/`mkdir` pass to 312M instructions; verified USB event/reply injection implemented | The app reaches 355.9M but its UIPC async consumer/UI tier never reads the verified buspwr VBUS message, so OSD A/B stay unmapped; the Sugilite buffer is internal and the SMAPH-S30 rasterizer is blocked by the private ISA — [E0298](docs/evidence/0298-safe-osd-capture-and-sugilite-correction.md) |

| Custom menu (framebuffer) | A custom interface is visibly drawn on the camera display | **Host-written; not firmware compatibility, original-menu navigation or settings proof** — [framebuffer photo](docs/images/framebuffer-camera-menu.png) |

| PTP liveview | Sensor JPEG 1024×680 transferred over PTP in PC Remote | PTP control transactions, simultaneous UVC/PTP control and teardown remain unproven — [E0151](docs/evidence/0151-pc-remote-liveview-and-uvc-verified.md) |

| UVC transport | Static MJPEG 1280×720 at 29.9592 FPS over 180 frames | Static pattern only; sensor feeder unwired, admission ioctl compiled into an undeployed candidate — [E0143](docs/evidence/0143-uvc-720p-test-transport-and-30fps-verified.md), [E0239](docs/evidence/0239-offline-uvc-frame-metadata-contract.md), [E0243](docs/evidence/0243-opt-in-producer-admission-module.md) |

| Composite USB | Windows parent + PTP + UVC children OK, Status OK, with the endpoint-84 fix; clean STOP/retire/unload and Mass Storage return with the unconfigure-first candidate (E0252) | Camera froze on the earlier teardown path (E0248/E0249); PTP transactions, streaming and repeated teardown trials remain open — [E0207](docs/evidence/0207-first-physical-composite-pcremote-enumeration.md), [E0210](docs/evidence/0210-original-endpoint-number-conflict.md), [E0252](docs/evidence/0252-f4-unconfigure-first-clean-teardown.md) |

| Native monitor | Bounded help command and one fixed `IFSYS getdriveinfo A` query returned original replies | General command results, per-event mode timing and competing-consumer ownership remain open — [E0227](docs/evidence/0227-physical-native-monitor-help-roundtrip.md), [E0234](docs/evidence/0234-ordinary-pcremote-ifsys-query-answered.md) |

| Native storage / journal | A: mapped to SD `/dev/mmca`; 8.3 journal path validated offline; three idle PC Remote switches stable | Journal unwritten; the earlier reboot used a `/dev/mem` probe, so the teardown/enumeration path is next — [E0222](docs/evidence/0222-physical-sd-volume-device-association.md), [E0238](docs/evidence/0238-8.3-journal-rebuild-offline.md), [E0245](docs/evidence/0245-p0-idle-isolation-trials-1-3.md) |

| Validation | 778 tests; 21 compiled ARM admission cases; 19 mocked collector cases | Bounded checks, not every physical path — [E0238](docs/evidence/0238-8.3-journal-rebuild-offline.md) |



### Emulation (guest contracts)



The bounded guest executes original ARM/Thumb code through verified CPU, Linux and hardware contracts. It reaches the `im.elf` entry point and the first event-dispatch phase, with complete contract coverage for the tested syscalls, ext2 surface, mmap, uIPC, NPTL threads and linker paths. It does **not** boot the camera: 1 of 8 task phases is observed and none of the 198 static plugin definitions is initialized. Instruction counts and passing fixtures are not a timing model, complete machine or deployment-safety proof.



### Physical modes: UVC, PTP, composite, native monitor, journal



Physical work is deliberate and evidence-bounded. Static 720p UVC transport and a 1024×680 PTP liveview JPEG have been demonstrated separately; with the endpoint-84 fix the shared composite session enumerated both children OK (Code 0), but the camera then froze and teardown was not recovered, and the sensor feeder is not connected. The native monitor answered a fixed `IFSYS` query in an ordinary PC Remote cycle with a verified receipt. The authorized small SD journal is still unwritten: the 8.3 path and collector are ready offline, but an intermittent PC Remote self-reboot stops further collector sessions until the cause is understood.



### Host-written artifacts (not firmware compatibility)



The custom menu drawn on the camera display and the static UVC test pattern are artifacts we wrote. They show framebuffer/display-surface writing and static transport respectively; they do not establish original Sony menu behavior, live sensor frames, settings labels or application compatibility.



## Current work



The current work is the emulator display path. A read-only contract now covers OSD A/B (camera-verified, 640×480 RGBA4444) and keeps the Sugilite buffer internal. A safe ptrace capture of im.elf's existing OSD mapping produced a complete PlayMemories USB MSC screen without opening `/dev/stream`. Boot gates `semtimedop` (syscall 312) and the observed `/setting/gps` mkdir pass. The USB workstream decodes the `/dev/usb/event` ABI and subtype mapping, implements exact record injection plus opt-in verified buspwr/otgcore replies, and identifies the verified buspwr VBUS UIPC producer (queue `0x012002da`, 16-byte body). The subtype-2 event record is accepted and wakes TID 1013, and the VBUS message is queued, but no consumer thread reads it (`woken=[]`); the app reaches 355.9M instructions with no boundary and no OSD A/B mapping. The next contract is UIPC async callback delivery / the libInfraUsbCmn consumer (or the UI/USB service tier), not more event bytes; a host-forced callback is not allowed. The E0297 `/dev/stream` OSD method must not be repeated.



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
