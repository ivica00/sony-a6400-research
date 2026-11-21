# Sony BIONZ X Universal Emulator, Modding & Custom OS Platform

An open, evidence-backed reverse-engineering, emulation (**QEMU** + **Unicorn**), and runtime modding platform for Sony **BIONZ X (`CXD90045`)** cameras—starting with **`ILCE-6400`** and scaling across 13 mapped camera bodies.

> **Canonical upstream:** [ivica00/bionz-x-research](https://github.com/ivica00/bionz-x-research). This research branch contributes native Unicorn continuation, bounded USB/GPU and A6400A packet experiments, and toolchain/QEMU updates. Original upstream research, code and contributor attribution are retained.

**You don't need a camera to contribute.** Roughly 90% of the work is offline Python & C. Every claim below is strictly labelled by what was actually demonstrated (offline emulation, read-only observation, or physical RAM-only run), and nothing is presented as a percentage of "full firmware compatibility."

> **[🪟 1-Click Windows Mod Manager GUI](docs/MOD_MANAGER_GUI.md)** · **[📦 Install & Use Camera Mods (Mod Loader v2, Touch Menu, ARRI Look)](mods/README.md)** · **[🖥️ Run QEMU Emulator (`sony-a6400`)](qemu-a6400/README.md)** · **[🔬 Develop & Hot-Reload Mods in QEMU](qemu-a6400/MOD_DEVELOPMENT.md)** · **[📷 Add a BIONZ X Camera](docs/ADDING_A_BIONZX_CAMERA.md)** · **[🎥 UVC / PTP Liveview](docs/CONTRIBUTING_UVC_PTP.md)**

---

## Project Goals

Stock USB attach boundary: original startup code inhibits the physical USB
key; messages reach Linux input processing but its live subscription is
suppressed. Paired captured-code traces identify the native owner/store and
the initialization release path. Its original readiness check is blocked by
`ModelCamera` (`0x0B`); native stores change readiness `1,0,1,0`, while
`ModelStillRec` is ready. The exact state dependency remains open. No ready
flag, application event or new hardware response was supplied
([E0619](docs/evidence/0619-native-usb-release-model-camera-readiness.md)).

Contributor boot scores for the merged read-back windows and the v11 speed
patches are filed with the pull-request comments:
[E0614](docs/evidence/0614-f280-clock-readback-contributor-boot-score.md),
[E0615](docs/evidence/0615-f350-readback-contributor-boot-score.md),
[E0616](docs/evidence/0616-tb-jmp-cache-bits-14-contributor-boot-score.md),
[E0617](docs/evidence/0617-v11-sd-insert-check-contributor-boot-score.md),
and [E0618](docs/evidence/0618-f388-readback-contributor-boot-score.md).
They keep captured step 26 (`0x0323`/`0x0320`). This workspace did not re-run
that scorer, and no physical camera result is claimed.
[E0637](docs/evidence/0637-camcore-f301-contributor-boot-score.md) records the
same kind of score for the merged CamCore window at `0xF3010000`: unmodelled
addresses 2,322 to 1,310, still step 26.
[E0643](docs/evidence/0643-cxd90045-miscreg-efuse-and-a6400a-jiritsu-chunk-planner.md)
decodes `DGU5` `MISCREG`/eFuse (`0xF2915000=0x00000500`, `0xF2915010=0x0c01002b`
on live `ILCE-6400`), confirms no kernel signature verification in `a6400`/`a6400A`,
documents synchronous `libJiritsu.so` `dlopen` (`0x5D08`), and adds the offline
`<= 512 KiB` RAM-chunk partition dump planner (`--mode plan-chunk-dump`).
[E0644](docs/evidence/0644-a6400-liro-ram-section-is-avcam-data.md) supersedes
[E0642](docs/evidence/0642-a6400-f30a-fill-engine-and-liro-ram-section.md)'s
sub-core inference, confirming the LIRO `ram` section is `av-cam` RW data.
[E0647](docs/evidence/0647-ilce6400-devmem-reboot-root-cause-and-policy.md) traces a
single-page `/dev/mem` camera reboot to PA `0x000F8000` (external abort `FSR 0x008` in the
persisted `/proc/klog`, which Sony's exception monitor turns into a warm reboot), enforces
`tools/devmem_policy.py`, models the abort opt-in in QEMU (`lowmem-abort=on`), and confirms
a `SIGBUS`-catching reader (`ro_page` v2) survives the read on the camera.
[E0648](docs/evidence/0648-ilce6400-bl-lens-focus-command-ids.md) decodes body–lens
focus command IDs (`0x41`–`0x4A` and first-generation `0x1C`–`0x3C`) and their capability
bitmap gate in `av-cam.bin`, and
[E0649](docs/evidence/0649-ilce6400-live-lens-info-linux-side-negative.md) confirms via a
read-only check on live `ILCE-6400` with a Sigma 18-50 F2.8 DC DN that ORIL lens capability
records are not retained in Linux `im.elf` memory.

Camera Wi-Fi on a physical `ILCE-6400` 2.00 (over its own AP): the packaged `orb-server`
carries 221 ScalarWebAPI camera methods, and what the camera advertises follows its state. At
drive mode `Continuous` it offers 47 with burst shooting instead of the shutter; at `Single` it
offers 50 with `actTakePicture`, and a photograph was taken over Wi-Fi
([E0658](docs/evidence/0658-wifi-scalarwebapi-and-its-missing-settings.md),
[E0659](docs/evidence/0659-camera-advertises-47-of-221-methods.md),
[E0664](docs/evidence/0664-shutter-works-drive-mode-decides.md)). Sony's decompiled Android
client grades what is portable from the 47-method state
([E0660](docs/evidence/0660-imaging-edge-mobile-control-sequence.md),
[E0661](docs/evidence/0661-what-could-be-ported-from-imaging-edge-mobile.md)). File transfer is
a different camera mode that no network call switches
([E0662](docs/evidence/0662-file-access-is-a-camera-mode.md)). Tools:
`tools/research/camera_remote.py`, `camera_panel.py` (browser panel with live view) and
`camera_transfer.py`.

Correction to the application-layer IPC table: [E0663](docs/evidence/0663-callgraph-plt-correction-and-real-ipc-table.md)
shows that the 29 call sites of E0483 called other imports (a fixed-stride PLT map gave each
import its neighbour's name) and fixes four call-graph decoding defects. The a6400 `libObj.so`
holds 763 IPC call sites, 544 with a constant queue id or command; six ids match ids observed at
runtime in the emulator, and the input handler sends to queue `0x014A0429`. E0484's finding that
no `ObjDisplay_*` symbol has a direct caller holds on all thirteen bodies.

QEMU without a camera capture: `tools/research/qemu_packaged_inputs.py` builds the boot
inputs from Sony's public a6400 updater, including a byte-identical `emmc.img` and powered
sub-micro frames from the packaged warm-boot image; only `ulogio.bin` still comes from the
ZV-E10 updater. The stock firmware draws its P-mode OSD and stops at the packaged step-32
wait, which QMP `xp` reads directly
([E0665](docs/evidence/0665-qemu-boots-from-the-public-updater.md)).

QEMU EP0 milestone: original firmware now completes six host-driven standard
control transfers to address 1, configuration 1 and UDC `configured` in two
fresh runs. The optional mode preserves the older descriptor replay and
rejects unsupported ownership/DMA cases. The enumerated original function
is bus-power/HID; UVC remains unverified
([E0598](docs/evidence/0598-qemu-token-driven-ep0-configuration.md)).

| Goal | What it means | Current milestone |
| :--- | :--- | :--- |
| **1 · Emulate Every BIONZ X Model** | Run original bootloaders, Linux kernels (`ARM-CXD900X0`), and `im.elf` UI/ISP stacks offline in **QEMU** and **Unicorn** across the `CXD90045` family | **13 bodies / 9 kernels mapped** ([`PLATFORM_MODEL.md`](docs/PLATFORM_MODEL.md)); **8 registered profiles** (`ILCE-6400` verified execution target + 7 sourced reference profiles, [E0570](docs/evidence/0570-ilce-7rm4a-offline-sourced-profile.md)) |
| **2 · Universal Modding Across Models** | Position-independent (`SMOD v2`) runtime mods with per-library relocation (`--reloc-layout`), hot-reloadable in QEMU and RAM-only on physical cameras | **Mod Loader v2 (`MLCR`)** runs in QEMU ([E0577](docs/evidence/0577-qemu-real-mods-relocation-and-hot-reload.md)) and `ILCE-6400` RAM ([E0555](docs/evidence/0555-arrivederci-menu-exit-recompute-and-cc8-refill.md)); ships **MTF2 Touch** ([E0520](docs/evidence/0520-mtf2-full-menu-touch-verified-on-a6400.md)), **Arrivederci ARRI Look** ([E0556](docs/evidence/0556-arrivederci-classic-fitted-matrix.md)), and **Open Gate 3:2** feasibility ([E0578](docs/evidence/0578-a6400-open-gate-3-2-recording-feasibility.md)) |
| **3 · Custom OS & Open Camera Stack** | Replace closed camera bottlenecks with open, verified kernel/userspace modules—native composite USB webcam (UVC+PTP), persistent WinUSB debugging, custom OSD/ISP pipelines, and an open replacement OS layer | **USB Debugger v2** ([E0401](docs/evidence/0401-usb-debugger-v2-ring-recover-and-mode-boundary.md)), **29.8 FPS PTP Liveview** ([E0349](docs/evidence/0349-p1-foreign-get-jpeg-succeeds-in-pc-remote.md)), **Composite UVC+PTP enumeration** & EP0 pre-arm bridge ([E0476](docs/evidence/0476-status-prearm-fix-build-audit-unicorn.md)) |

---

## Emulation Architecture & Progress: QEMU vs. Unicorn

This project uses two complementary emulators:

- **QEMU ([`qemu-a6400/`](qemu-a6400/README.md)) — Full-System Board (`sony-a6400`):** Out-of-tree QEMU v11.1.3 machine emulating 4× Cortex-A5 SMP cores, native eMMC partitions, 40 kernel modules, `av-cam.bin` (LIRO RTOS), `im.elf`, Sugilite P3D/PPF OSD, and an interactive browser rear panel (`rear_panel.py`) with live mod hot-reload. The earlier v10.1.0 build and evidence remain preserved.
- **Unicorn (`src/a6400/`) — Deterministic Contract & Instruction Engine:** Fast Python + Unicorn harness split into **L2** (`UnicornMachine` kernel boot & MMU/TLB), **L3** (`InterpreterProbe` user-space syscall/IPC/thread engine), and **isolated ARM/Thumb unit harnesses** for verifying mods and kernel patches in CI without booting a full VM.

### Compact Stage Matrix

Legend: `🟢 Verified` · `🟡 Partial / Opt-in` · `⚪ Open Boundary` · `⛔ Not Supported`

| Stage / Subsystem | QEMU (`sony-a6400` Full Board) | Unicorn (`L2` Kernel / `L3` Userspace) | Key Evidence & Docs |
| :--- | :--- | :--- | :--- |
| **CPU, SMP & Boot** | 🟢 4× Cortex-A5 SMP, `kemco` handoff, CXD4115 timers | 🟢 L2 boots both `nflasha1` updater ([E0653](docs/evidence/0653-unicorn-updater-child-cow-and-hwcap.md)) and captured `nflasha3` main firmware ([E0656](docs/evidence/0656-unicorn-main-firmware-boot.md)) through stock `/sbin/init`, 39 `.ko` modules, `LIRO` `entry_main`, `im.elf` `DMP_2D_Initialize : 0`, and `/bin/ash` | [E0522](docs/evidence/0522-qemu-a6400-smp-four-cores-and-cxd4115-timers.md), [E0653](docs/evidence/0653-unicorn-updater-child-cow-and-hwcap.md), [E0656](docs/evidence/0656-unicorn-main-firmware-boot.md) |
| **Storage & Mounts** | 🟢 18 captured partitions, CMD1 sector mode, qcow2 overlay | 🟢 Read-only ext2 (`nflasha7`/`15`), FAT12 `/setting` (`nflasha2`), 88 devnodes | [E0524](docs/evidence/0524-reproducible-captured-qemu-boot-and-liro-waits.md), [E0307](docs/evidence/0307-nflasha2-setting-namespace-uipc-unregister-and-idle-state.md) |
| **RTOS (`av-cam` / LIRO)** | 🟡 40 `.ko` loaded, `entry_main`, captured and reconstructed packaged `VD_Sequence` reach step 42 with distinct opt-in hardware replies | 🟢 Static & slice execution of CC 3D-LUT, EC Gamma, DMM & Open Gate 3:2 tables | [E0591](docs/evidence/0591-qemu-a6400-first-live-view-frame.md), [E0505](docs/evidence/0505-av-cam-cc-3dlut-and-ec-gamma-pipeline.md), [E0578](docs/evidence/0578-a6400-open-gate-3-2-recording-feasibility.md) |
| **UI & Display (`im.elf`)** | 🟢 With `REAR_CONTROLS=1`, stock `FINDER/MONITOR` (`Auto` / `Monitor(Manual)`) renders Rear-LCD & Menu (`640×480`) without overlay patch; late blank traced to guest `add_off_factor: 0x8` | 🟡 L3 runs unmodified `im.elf` to `1.50B` insns (`120` threads, `0` heap ownership errors without padding), completes `24` Sugilite GPU/IRQ 76 jobs, and presents transparent `viewRootPowerSw.uxc` `640×480` OSD A/B frames; populated child views await RTOS `CheckerBootState`/`CheckerBootType` | [E0651](docs/evidence/0651-qemu-a6400-stock-finder-monitor-rear-lcd.md), [E0652](docs/evidence/0652-qemu-a6400-late-black-screen-scanout-capture.md), [E0657](docs/evidence/0657-unicorn-l3-allocator-gles-init-and-sugilite-gpu.md) |
| **Inputs & Touch** | 🟢 MENU and directional presses in the original menu; 🟡 wheel and AF/MF–AEL reach guest input, application response unverified; ⛔ **No touch panel** | 🟢 Isolated harnesses for touch press/release (`MTF2`) & menu vtables | [E0573](docs/evidence/0573-qemu-a6400-rear-panel-controls.md), [E0520](docs/evidence/0520-mtf2-full-menu-touch-verified-on-a6400.md) |
| **Mod Loader & Mods** | 🟢 `Mod Loader v2` installs in guest `im.elf`, relocates & hot-reloads `.mod` files; native tab and swipe inputs change the guest menu only with MenuTouchFull ON | 🟢 15-scenario `MLCR` core + `SMOD v2` relocation & trampoline checks | [E0577](docs/evidence/0577-qemu-real-mods-relocation-and-hot-reload.md), [firmware qualification and native replay](docs/evidence/mods/2026-11-19-firmware-qualification.md) |
| **Live Sensor / YUV** | 🟡 Opt-in deterministic luma reaches the stock guest's CamPig/Ydet, RC0 DMA and rear LCD via VPH ch51 | ⚪ Sensor feeder unwired; DMM `0x0167046a` JPEG queue contract decoded | [E0591](docs/evidence/0591-qemu-a6400-first-live-view-frame.md), [E0349](docs/evidence/0349-p1-foreign-get-jpeg-succeeds-in-pc-remote.md) |
| **USB, Wi-Fi/BT, HDMI, Lens** | 🟡 Opt-in DWC3: original bus-power/HID reaches configured through six EP0 controls; no UVC/data endpoints, radio, HDMI, lens or audio qualification | 🟡 Original-process USB startup reaches FSM state 7 and gadget registration, then stops at guarded OTG `SET_MODE`; ⛔ no radio/HDMI/lens | [E0598](docs/evidence/0598-qemu-token-driven-ep0-configuration.md), [E0534](docs/evidence/0534-original-process-usb-gadget-registration-and-otg-boundary.md), [E0476](docs/evidence/0476-status-prearm-fix-build-audit-unicorn.md) |

### Parallel Offline Contract Follow-Ups

- **Native Unicorn updater & main firmware:** [E0653](docs/evidence/0653-unicorn-updater-child-cow-and-hwcap.md) verifies `nflasha1` continuation past the post-`uname` child/COW fault and D16 `AT_HWCAP` parity (`0x0000E0D7`). [E0656](docs/evidence/0656-unicorn-main-firmware-boot.md) boots captured `nflasha3` main firmware on `UnicornMachine` (`--mmio stop`, read-only `emmc.img`) through stock `/sbin/init`, 9 partition mounts, 39 `.ko` modules, `LIRO` `entry_main`, `im.elf` `DMP_2D_Initialize : 0`, and `/bin/ash` (`uname -a`, `/proc/cpuinfo`, `mount`, `/proc/modules`); single-core execution leaves `av-cam` CPUs 1–3 offline and claims no Unicorn GUI frame.
- **USB delivery versus startup:** [E0524](docs/evidence/0524-original-local-osal-setconfig-route.md) executes isolated synchronous-to-asynchronous SETCONFIG delivery with balanced fixture ownership; startup state 0 does not handle that event. [E0534](docs/evidence/0534-original-process-usb-gadget-registration-and-otg-boundary.md) uses the process's own heap and reaches states `1 -> 5 -> 6 -> 7`, but `created=0` at OTG `SET_MODE`. No event or hardware acknowledgement is fabricated.
- **Allocator and GPU corrections:** [E0526](docs/evidence/0526-stella-allocator-size-isolation-and-padding-trial.md) shows that the isolated log constructor fits its `0x4C` request; padding is not a verified fix. [E0530](docs/evidence/0530-gles-tgid-completion-and-shared-memory-boundary.md) verifies TGID completion/reset and distinguishes 128 KiB software-shared memory from the GPU BAR. [E0657](docs/evidence/0657-unicorn-l3-allocator-gles-init-and-sugilite-gpu.md) traces all former L3 heap aborts to Unicorn 2.1.4 Thumb-2 stale-`ITSTATE` skips (`1.50B` instructions, `0` ownership errors without padding), recovers `sugilite_open` 4-byte + `rm_rqueue_init` 128 KiB shared initialization, and verifies `24` Sugilite GPU jobs + `24` IRQ 76 completions presenting `viewRootPowerSw.uxc`'s transparent `640×480` OSD A/B root frames (`DefRootView` `CheckerBootState`/`CheckerBootType` await RTOS `av-cam.bin` producers).
- **A6400A service packets:** [E0525](docs/evidence/0525-a6400a-jiritsu-senser-offline-packets.md) maps all 18 Jiritsu commands and seven repeatable packet fixtures. Opt-in [E0532](docs/evidence/0532-a6400a-dmm-metadata-bounds-and-lifetime.md) adds bounded single-extent DMM metadata/lifetime and an eighth synthetic reply. USB, authentication, filesystem operations and authentic allocation remain unsupported; the profile stays `reference`.
- **Earlier captured-profile waits:** [E0527](docs/evidence/0527-qemu-task43-initialization-flag-wait.md) identifies Task 43's first display wait as mask 3, not its later `0x3373` loop. That no-peripheral observation is retained separately from the later QEMU device models and rear-panel progress.

### What Is Not Supported Yet

- **Live camera sensor, shutter & recording (QEMU & Unicorn):** The QEMU frame uses synthetic luma, not a real sensor stream or validated RAW/color ISP. AF/AE, still capture and movie recording to SD are unverified (see [QEMU checkpoint](qemu-a6400/STATUS.md)).
- **Touch-panel hardware in QEMU:** The `sony-a6400` board has no emulated touch controller, so touch mods (`MTF2`) cannot be exercised via clicks in QEMU ([`MOD_DEVELOPMENT.md`](qemu-a6400/MOD_DEVELOPMENT.md)).
- **USB Gadget (UVC / PTP / MSC) in QEMU:** The stock view-driven server-start gate remains unqualified ([E0589](docs/evidence/0589-qemu-usb-mode-gate-and-defrootview.md)). Explicit diagnostic commands and optional captured-register/host-token policies now enumerate the original bus-power/HID function to UDC configured ([E0598](docs/evidence/0598-qemu-token-driven-ep0-configuration.md)). A genuine UVC function, non-EP0 data endpoints, transfer chains, packetization and video remain unqualified; the USB Streaming Test item still only counts loader lifecycle calls.
- **Removable media in QEMU:** The [virtual SD slot and USB scenarios](qemu-a6400/README.md#offline-sd-and-usb-scenarios) verify SD hotplug and sector persistence separately from eMMC. Sony firmware mounts the SD filesystem; playback and still capture remain unverified. A separate non-Sony virtual USB Mass Storage fixture enumerates and reads ([E0650](docs/evidence/0650-qemu-virtual-media-gates.md)).
- **Peripherals & Radios (QEMU & Unicorn):** Wi-Fi / Bluetooth (`BCM4339`), HDMI output, E-mount lens communication, audio I/O, are unmodelled; the hardware watchdog (`0xF2402000`) is modelled only as opt-in `watchdog=on` ([E0636](docs/evidence/0636-qemu-cxd4115-hardware-watchdog-opt-in.md)).
- **Populated Unicorn L3 shooting/menu GUI & Non-a6400 Boot:** `InterpreterProbe` (Unicorn L3) presents `viewRootPowerSw.uxc`'s transparent `640×480` RGBA4444 OSD A/B root frames via Sugilite `PSC0`+`PPF` ([E0657](docs/evidence/0657-unicorn-l3-allocator-gles-init-and-sugilite-gpu.md)), while populated shooting/menu screens await RTOS `av-cam.bin` / sub-micro boot-mode producers, and only `ILCE-6400` is a verified execution target (other `CXD90045` bodies are reference profiles).

---

## Universal Modding & Available Mods

**[Mod Loader v2 (`MLCR`)](docs/MOD_LOADER_V2_DESIGN.md)** installs a tiny permanent RAM shim in `im.elf` (`viewUnified2.so` hooks) and loads a position-independent core (`core.bin`) plus relocatable **`SMOD v2`** `.mod` packages—requiring **zero flash writes** and restoring stock behavior on reboot. Using `--reloc-layout`, a single `.mod` binary shifts its library addresses at load time to run across both QEMU and physical camera memory layouts ([E0577](docs/evidence/0577-qemu-real-mods-relocation-and-hot-reload.md)).

| Mod | What it does | Status |
| :--- | :--- | :--- |
| **[MenuTouchFull (`MTF2`)](mods/menu_touch_full/README.md)** | Full-menu touch navigation: tabs, page dots, swipe paging, row select/open, popup scroll & apply | v1 verified on `ILCE-6400` ([E0520](docs/evidence/0520-mtf2-full-menu-touch-verified-on-a6400.md)); v2 tab taps and swipes verified from the [native guest touch queue](docs/evidence/mods/2026-11-19-firmware-qualification.md#native-touch-follow-up). **`ZV-E10`**: hardware-verified full main menu + 12-tile Fn menu touch via direct RAM injection ([details](tools/native_camera/zve10/README.md); *Mod Loader is untested on ZV-E10 at the moment*) |
| **[Arrivederci](mods/arri_isp/arrivederci/README.md)** | ARRI LogC3 Classic tone curve + fitted Q10 color matrix for S-Log3 / S-Gamut3.Cine | Usable in Modset v2 ([E0555](docs/evidence/0555-arrivederci-menu-exit-recompute-and-cc8-refill.md), [E0556](docs/evidence/0556-arrivederci-classic-fitted-matrix.md)); turn OFF before power-off |
| **ModsTabLook** | Renders the custom `MODS` tab icon artwork (`E0522`) | Auto-enabled in QEMU mod-dev mode ([E0522](docs/evidence/0522-mods-tab-icon-and-uxd-image-container.md)) |
| **Command items** (`--action`) | A Mods row without ON/OFF: pressing it starts the mod and closes the menu to the shooting screen, like the ZV-E10 "USB Streaming" entry | Loader feature verified in Unicorn and QEMU ([E0592](docs/evidence/0592-mod-loader-command-items-usb-streaming-entry.md)); no UVC streaming mod uses it yet. The QEMU virtual USB host reaches the DWC3 model, but the guest never starts a gadget ([E0593](docs/evidence/0593-qemu-dwc3-virtual-host-and-gadget-start-gap.md)) |
| **Open Gate (3:2)** | Candidate `IMX284` 3:2 (`1620×1080` / `3240×2160`) recording path via `DMM` & `ZIMA DVENC` | [Buffer selection verified; recording unproven](docs/evidence/mods/2026-11-19-firmware-qualification.md#stock-recording-and-open-gate). The stock guest mounts virtual SD but did not save an AVCHD clip. |

👉 **[Read `mods/README.md` for step-by-step installation (QEMU & physical `ILCE-6400`)](mods/README.md)**

### 🪟 Quick Start for Camera Owners (1-Click Windows GUI — No Coding Required)

If you just want to install mods or unlock camera tweaks on your **`ILCE-6400`** without using the command line, use the **[BIONZ X Mod Manager GUI](docs/MOD_MANAGER_GUI.md)**:

1. **One-time prerequisite (Windows 10/11):** Install **[Python 3.11+](https://www.python.org/downloads/)** and check **"Add python.exe to PATH"** at the bottom of the installer (or use a prebuilt `BionzX-Mod-Manager.exe` release bundle if you downloaded one).
2. **Start the app:** Open this project folder and double-click **[`scripts/launch_mod_manager.bat`](scripts/launch_mod_manager.bat)**. On first run it automatically prepares its own isolated environment (`.venv-gui`) and opens the **Sony BIONZ X Mod Manager** window (or browser tab if WebView2 is unavailable).
3. **Download official tools (first run only):** If a yellow banner appears at the top, click **Download Official Release** (or open the **Tools & Setup** tab and click **Download / Prepare Tools**). The app automatically downloads and verifies Mod Loader v2, the USB helper, and Arrivederci v5.
4. **Connect your camera:** On the camera, go to `MENU → Setup (briefcase icon) → USB Connection` and select **Mass Storage**. Plug the camera into your computer with a data-capable USB cable and click **Scan Camera**.
5. **Toggle mods & install in 1 click:** Switch your desired **Runtime Mods** (such as *Menu Touch Full* or *Arrivederci v5*) or **Permanent Tweaks** (such as *Unlimited Video Recording* or *Unlock All 35 Languages*) **ON** or **OFF**, then click **1-Click Install to Camera** and follow the on-screen prompt. *(On a brand-new camera, the first click sets up the USB helper and asks you to turn the camera OFF and ON once, then click **1-Click Install to Camera** one more time.)*
6. **Use your mods on the camera:** Unplug the USB cable and open `MENU → Mods (tab 7)` on the camera to switch installed runtime mods on or off at any time. Turning the camera off clears RAM-only runtime mods back to stock firmware (**important:** always toggle **Arrivederci OFF** in `MENU → Mods` before turning the camera off).

👉 **Full guides:** **[Windows Mod Manager GUI Guide (`docs/MOD_MANAGER_GUI.md`)](docs/MOD_MANAGER_GUI.md)** · **[Detailed Mod & CLI Guide (`mods/README.md`)](mods/README.md)**

### 📷 Sony ZV-E10: MenuTouchFull & Fn Touch Mod (Direct RAM Injection)

A native ARM touch layer ported and verified on physical **Sony ZV-E10** (`WW356015`, FW 2.02 / 2.03, `body_version = 100.110.035`). It hooks `postMousePress` and `postMouseRelease` in `/libObj.so` and dispatches touch events into the camera's internal UI framework.

> [!IMPORTANT]
> **Mod Loader is currently untested on Sony ZV-E10:** Mod Loader v1 and v2 (SD-card `.mod` loader and the 7th `Mods` menu tab) have not yet been ported or tested on the ZV-E10. At the moment, this touch mod is deployed via **direct volatile RAM injection** into `im.elf` (`libObj.so` RX zero padding) using the camera's USB Senser terminal mode.
> - **Zero flash writes:** `/dev/nflasha*` is completely untouched.
> - **100% volatile & reversible:** A camera power cycle restores completely stock firmware behavior.

**Verified Live Hardware Capabilities:**
- **Main Menu Navigation:**
  - Tapping tabs 1..5 immediately switches tabs.
  - Tapping page indicator dots or swiping horizontally pages left/right.
  - Single tap selects/highlights any menu row.
  - Double tap opens level-2 dropdown popup dialogues (via native synchronous `openLevel2Popup`).
- **Popup Dialogues:**
  - Tapping an item selects and applies the setting, closes the popup, and refreshes the parent menu.
  - Vertical swiping scrolls multi-item dialogues.
  - Tapping outside the popup cancels/dismisses it without changes.
- **Fn (Function) Menu in Live Preview:**
  - Tapping any of the 12 tiles (2×6 grid) selects that tile using shortest circular path ring navigation (`ViewFnMenu::ProductAction`).
  - Second tap (or double tap) opens the tile's setting dialogue (`Decide` action).
  - Tapping upper screen area (`y < 260`) cancels and dismisses the Fn overlay (`KEY_FN`).

**Current Status & Limitations:**
- **Mod Loader Untested:** Mod Loader is not yet ported for ZV-E10; deployed directly to volatile DRAM over Senser terminal shell.
- **Fn Continuous Sliders:** Fn tiles that open continuous scrolling slider dialogs (e.g. ISO slider) crash on tap (investigation in progress).
- **My Menu (Tab 6):** Touch on Tab 6 is unhandled (matching upstream a6400).

**Quick Deploy (via Senser Terminal):**
```powershell
# 1. Switch camera to Senser mode (bind libusb-win32 if needed via Zadig)
python -m tools.research.deploy_zve10_menu_touch --switch-only

# 2. Build payload and request structures (requires Zig or arm-linux-musleabi)
python -m tools.research.build_zve10_menu_touch

# 3. Upload and perform live DRAM injection into im.elf
python -m tools.research.deploy_zve10_menu_touch
```
Full technical details: [`tools/native_camera/zve10/README.md`](tools/native_camera/zve10/README.md) and [`docs/porting/zv-e10/`](docs/porting/zv-e10/README.md).

---

## Multi-Camera Support (`CXD90045` Platform)

Registered profiles live in [`src/a6400/targets/`](src/a6400/targets/catalog.py) and share the cross-body `CXD90045` model ([`PLATFORM_MODEL.md`](docs/PLATFORM_MODEL.md)). Guide: **[Adding a BIONZ X camera](docs/ADDING_A_BIONZX_CAMERA.md)**.

| Body | Kernel Group | Status | Notes / Evidence |
| :--- | :--- | :--- | :--- |
| **`ILCE-6400`** | `a6400` / `a6600` source | **Verified Execution Target** | Full QEMU & Unicorn L2/L3 execution, physical RAM-only mods |
| **`ZV-E10`** | Shared build | **Verified Execution Target (RAM)** | Full Main Menu touch + 12-tile Fn menu touch verified on physical hardware (FW 2.02/2.03) via volatile direct DRAM injection into `im.elf`. Mod Loader currently untested on ZV-E10. UVC stack cataloged ([E0321](docs/evidence/0321-zve10-uvc-enablement-manifest.md)) |
| **`ILCE-6400A`** | `1.01` packaged | **Sourced Reference** | Native `GetModelInfo` (`0032858730`), packaged Jiritsu command map and bounded offline DMM replies ([E0554](docs/evidence/0554-a6400a-v101-jiritsu-command-dispatch.md), [E0525](docs/evidence/0525-a6400a-jiritsu-senser-offline-packets.md), [E0532](docs/evidence/0532-a6400a-dmm-metadata-bounds-and-lifetime.md)) |
| **`ILCE-6600`** | `a6400` / `a6600` source | **Sourced Reference** | Identical 14,401 kernel function symbols; `0x413b` command delta |
| **`ILCE-7C`** | Shared build | **Sourced Reference** | Identical 14,460 kernel function symbols |
| **`ILCE-6100`**, **`ILCE-7M3`**, **`ILCE-7RM4A`** | Shared symbol list | **Sourced Reference** | `ILCE-7RM4A` 1.13 gadget-core symbols decoded ([E0570](docs/evidence/0570-ilce-7rm4a-offline-sourced-profile.md)); `GetModelInfo` command binaries byte-identical to a6400A (opcode `0x7A` confirmed offline; SCSI-side routing still needs the camera), read-only probe generalized ([E0645](docs/evidence/0645-ilce-7rm4a-getmodelinfo-extcmd-chain-identical.md)); physical read-only on 1.13: Mass Storage `054C:0D9D`, PC Remote `054C:0D9F`, native `GetModelInfo` `ILCE-7RM4A` after one BUSY ([E0646](docs/evidence/0646-ilce-7rm4a-physical-usb-identity-and-getmodelinfo.md)) |

---

## Live Status Telemetry

Recorded integration baseline: **2091 tests**, with 88 skip records and no failures/errors ([rebase validation and limits](docs/TOOLCHAIN.md#upstream-rebase-integration-2026-11-18)). Skips are not passes. The [late black-screen capture](docs/evidence/0652-qemu-a6400-late-black-screen-scanout-capture.md), [LIRO RAM section analysis](docs/evidence/0644-a6400-liro-ram-section-is-avcam-data.md), [CamCore contributor score](docs/evidence/0637-camcore-f301-contributor-boot-score.md), [USB mode gate](docs/evidence/0589-qemu-usb-mode-gate-and-defrootview.md), and [first firmware-driven live-view frame](docs/evidence/0591-qemu-a6400-first-live-view-frame.md) are separate findings. Earlier narrative highlights are preserved in [docs/archives/readme-latest-progress-2026-11-18.md](docs/archives/readme-latest-progress-2026-11-18.md) and [docs/archives/readme-latest-progress-2026-11-15.md](docs/archives/readme-latest-progress-2026-11-15.md).

![Research status: demonstrated results and remaining boundaries](docs/images/research-status.svg?v=a0e92f46cb39)

![Daily automated test suite growth: 2091 tests across 32 days](docs/images/test-growth.svg?v=7c3d215972bb)

---

## How to Help (No Camera Needed)

Please bring BIONZ X research, fixes, and camera support to this repository early. Reuse the tracking issue for your camera model and open a draft pull request with your first verified result. Shared evidence and fixes can then help every compatible body. See the [contribution and attribution policy](CONTRIBUTING.MD#work-in-the-main-repository).

**Top 3 open tasks right now:**

1. **Prove stock SD playback and still capture (QEMU):** Captured startup reaches step 42 with an opt-in lens rail reply; the older packaged step-32 Ydet wait is a separate replay ([E0591](docs/evidence/0591-qemu-a6400-first-live-view-frame.md)). Stock firmware mounts SD, but the original display of a seeded JPEG and a new photo surviving restart remain unverified ([E0650](docs/evidence/0650-qemu-virtual-media-gates.md)).
2. **Complete native USB gadget startup (Unicorn / UVC):** The opt-in original FUSB path enters the bound DWC3 reset and stops before PL310 sync ([E0655](docs/evidence/0655-qemu-first-view-ptp-and-native-dwc3-reset.md)). Qualify reset and gadgetcore commit, then prove process-owned SETCONFIG delivery and teardown. The isolated local route is already executable.
3. **Establish GPU shared backing and rendering (Unicorn L3):** TGID completion/reset is verified, but strict replay stops on unsupplied shared bytes. Recover initialization and functional GPU work without assumed success ([E0530](docs/evidence/0530-gles-tgid-completion-and-shared-memory-boundary.md)).

More guides: [Contributing to UVC / PTP](docs/CONTRIBUTING_UVC_PTP.md) · [UVC/PTP progress log](docs/UVC_PTP_STATUS.md) · [USB Debugger v2](docs/NATIVE_USB_DEBUGGER.md).

---

## Quick Start

Requires Python 3.11+ and dependencies from [`requirements.txt`](requirements.txt) (no camera needed).
The current research environment uses Python 3.15.2 in `.venv`; the previous
`venv/` remains available for rollback. See [verified toolchain setup and upgrade
results](docs/TOOLCHAIN.md) for REA 6.9.0, Ghidra 12.2 and patched QEMU 11.1.3.

```powershell
# Windows (PowerShell)
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

```bash
# Linux / macOS
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -q
```

| What to check | Command |
| :--- | :--- |
| Full offline suite (2091 tests) | `python -m unittest discover -s tests -q` |
| Structure, profiles & doc sync | `python -m unittest tests.test_repository_layout tests.test_target_profiles tests.test_research_status_sync -v` |
| Status card matches data | `python -m tools.research.render_research_status --check` |
| Windows launchers | [`scripts/`](scripts/) (`launch_cinemahud_ptp.bat`, `launch_cinemahud_android.ps1`, `launch_cinema_mpv.bat`, `start_camera_shell.bat`) |

Run scripts as Python modules from the repo root (`python -m tools.research.<tool>`). Firmware images, backups, and captured artifacts stay local and are excluded from Git.

---

## Repository Layout & Safety Rules

| Folder | What's inside |
| :--- | :--- |
| [`qemu-a6400/`](qemu-a6400/README.md) | Out-of-tree QEMU v11.1.3 `sony-a6400` machine, browser rear panel & mod-dev hot-reload |
| [`mods/`](mods/README.md) | RAM-only camera mods (`MenuTouchFull`, `Arrivederci`, `ModsTabLook`) & install guide |
| `src/a6400/execution/` | Unicorn L2/L3 ARM emulator and verified OS, USB, and GPU contracts |
| `src/a6400/targets/` | Device profiles and validation for supported Sony `CXD90045` cameras |
| `src/a6400/debug/` | USB debugger protocol, log ring buffer, and WinUSB transport |
| `tools/research/` & `tools/native_camera/` | Firmware analysis scripts, Mod Loader v2 (`mlv2/`), C helpers, and status-card generator |
| `probes/` | Safe, read-only ARM probe for other BIONZ X cameras |
| [`a6400-lut-converter/`](a6400-lut-converter/README.md) | Offline ISP table fitting, ARRI presets, and 8-bit 4:2:0 preview |
| `tests/`, `docs/`, `docs/evidence/` | Automated contract checks, architecture notes, and dated evidence logs |
| `android/`, `camera-daemon/` | Android liveview client (`CinemaHUD`) and camera-side composite USB webcam daemon |
| `firmware/`, `backups/`, `artifacts/` | Local firmware dumps and generated outputs (never committed to Git) |

**Safety & Epistemic Rules:**
- **Honest claims only:** Host-written UI or camera logic is **not** firmware compatibility. Every claim links to a dated evidence record.
- **No flash writes:** Never modify internal camera flash, install custom firmware, or alter boot partitions.
- **Clean-room emulation:** Original firmware owns application logic; unknown OS services stop and report where they stopped instead of faking success.
- **Safe hardware checks:** Read-only camera inspection is allowed; writes, mode switches, and module loads require explicit scope. Bulk `/dev/mem` memory sweeps are banned ([`AGENTS.MD`](AGENTS.MD)).

---

An opt-in [ZV-E10 adapted-menu integration](docs/ZVE10_ADAPTED_MENU.md)
runs prepared private inputs on the upstream QEMU board, with native event and
scanout checks. This does not qualify stock boot or physical controls.

External comparison: [ZV-E10 adapted-menu receipt](docs/evidence/external-zve10-menu/README.md)
records an original English Sony menu under an AP-only adapter. It is separate
from upstream stock-firmware boot progress and does not advance the a6400
compatibility or test-count claims.

## Links & Attribution

[Documentation index](docs/INDEX.md) · [Current state](docs/CURRENT_STATE.md) · [Evidence index](docs/evidence/README.md) · [Related research repositories](docs/RELATED_REPOSITORIES.md) · [Architecture](docs/ARCHITECTURE.md) · [Roadmap](docs/ROADMAP.md) · [Contributing](CONTRIBUTING.MD) · [Repository layout](docs/REPOSITORY.md) · [Agent rules](AGENTS.MD) · [Archived README](docs/archives/README-2026-11-09.md)

- **Cross-generation BIONZ X research:** [Oein/a5000-emulator](https://github.com/Oein/a5000-emulator) by Park SungHyun (Oein) — clean-room reference for DMP SMAPH/P3D command-list format and 8×8 Morton tiling (`docs/RE_GPU_P3D_CMD.md`, CC BY 4.0), `GICD_ITARGETSR` bootloader pre-routing (`docs/HARDWARE.md`), and `im.elf` UI bringup gates (`docs/RE_UI_BRINGUP.md`).

Independent research; not affiliated with or endorsed by Sony. Sony, a6400, ILCE-6400, and BIONZ X are trademarks of their respective owners.
