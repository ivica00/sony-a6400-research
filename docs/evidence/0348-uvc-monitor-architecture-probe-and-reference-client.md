# E0348 â€” UVC monitor architecture, live read-only MSC snapshot, safe DMA probe and reference client (offline)

Date: 2026-11-11. Authoring round with **read-only** physical camera access in Mass
Storage; no module load, no USB mode switch, no frame streamed, no control written,
no flash/SD/boot change. Battery-pull recovery contract retained throughout.

## Claim

1. A decision-grade architecture for a low-latency a6400 Live View + control system
   exists in `docs/ARCHITECTURE_UVC_MONITOR.md`, grounded in four independent recon
   reports and a live read-only snapshot: the verified near-term path is a
   **host-driven pipelined PTP push pipeline** (Android), the higher-ceiling
   **camera-side composite UVC push daemon** is implemented but gated, and
   "<35 ms glass-to-glass" is re-scoped to â‰40â€“55 ms with the reasons stated.
2. A safe, bounded ARM diagnostic probe (`probes/`) was authored, cross-built,
   pushed to `/tmp_bt` with readback verification, executed on the camera in its
   default **observational-only** mode, and its JSON report was schema-validated.
3. Three implementation trees were produced offline and built/verified as far as
   this host allows: `camera-daemon/` (static ARM), `android-client-ref/`
   (host-compiled native + structure-verified Kotlin), `probes/`.
   **None has been deployed to or executed on the camera.**

Status: live observations **verified** (read-only). Implementations **offline,
unverified on hardware**.

## Firmware / camera configuration

Camera in **Mass Storage**, USB debugger `usb_extcmd` (feature 0x23), PID 703 root.
`Linux version 3.0.27_nl-rt106+ â€¦ gcc 4.5.1 (Sony CE Linux 8.2.6.0) #1 SMP PREEMPT RT`.
42 loaded modules; `usbg_video` and `usbg_audio` absent. `im.elf` PID 149,
175 threads, `TracerPid: 0`, CapEff all ones. `/proc/uptime` monotonic across the
session (3464.18 s â†’ 4661.20 s) â€” no reboot.

## Source and artifacts

| Artifact | Bytes | SHA-256 |
| --- | --- | --- |
| `docs/ARCHITECTURE_UVC_MONITOR.md` | 35,070 | `981bb8ca27bb67483ea670397f6abddc9d521c370606d39600fcdeeaef95d067` |

The size/hash above identify the architecture document as it was at the E0348 checkpoint. The
same document was extended by the later records in this cycle (E0349–E0352), so its current
size is larger; the entry records provenance, not the current file identity.
| `artifacts/analysis/recon-e0348/REPO_RECON.md` | 62,167 | `ae44ea32d82b233fd2f8e6261f6f0f323daf78e44214ab02c9e94570be6c3f96` |
| `artifacts/analysis/recon-e0348/LIVEVIEW_DMA.md` | 64,102 | `9f6930237a170aec693ab6b0b9f2d88f69f2fb4a2766a00ccb89f04a2e15a9f8` |
| `artifacts/analysis/recon-e0348/USB_GADGET.md` | 81,024 | `83a35773b4e09a81cc27b078f4527e122e5f2a9dd1ac628d8356f383c1f6afd4` |
| `artifacts/analysis/recon-e0348/CONTROL_IPC.md` | 56,990 | `88a0ef084c470401302ba07e435c6dcfe7741e78c0a19926dc9ec7d355bb56d2` |
| `artifacts/analysis/recon-e0348/camera-mss/manifest.json` (+6 dumps) | 3,366 | `999e4f036317f5099e335b9b8b1fe6af7b6fc6e9180d869129a885435a0879ed` |
| `artifacts/analysis/recon-e0348/camera-probe/uvc_probe_e0348.json` | 18,038 | `d97943ea5fcf75bbaf596e8b563714a55eae220ca559711d95b8c3c54bdd164e` |
| `probes/uvc_dma_probe.c` | 85,127 | `8836ab334c289fe7aab488dadfc244775850d8d7b5d81ed4c2782f1ad4f3b8b0` |
| `probes/build/uvc_dma_probe_arm` (ELF32 ARM, static) | 48,144 | `b32987b943bf66c75befb0e13c242bdb14491fc3b0707572d28a0273f08eb66e` |
| `camera-daemon/build/a6400-lived` (ELF32 ARM, static) | 628,000 | `009f2e213d63cf42783169fd88a16fcf434501c575c5bf503b0ea7e556326238` |
| `camera-daemon/build/host_test.exe` (offline host tests) | 131,796 | `69b9397ea5a0de6bb1d6e1f71c2a88cae806e42fd91200ba058d588a6001682b` |
| `android-client-ref/app/src/main/cpp/shaders/sgsr1_fragment.glsl` | 10,722 | `b187a1913dce3cbcdaa354c1f06c105bc652370aff45ec1f52b7c2204ed62a1d` |

## Method

1. **Four parallel offline recon agents** produced the reports above from the
   repository alone (no camera I/O allowed): repo/firmware map, frame-source and
   interception ranking, USB gadget/transport evaluation, camera-control IPC.
2. **Live read-only camera session** through `tools/camera_debugger.py`
   (`info`, `exec`, `read`): `/proc/uptime`, `/proc/version`, `/proc/cmdline`,
   `/proc/modules`, `/sys/class/udc/*`, `ls -l /dev` + `/dev/usb`,
   `/proc/149/{status,maps,fd,task}`, `/proc/kallsyms` (selected symbols),
   `/proc/osal/{uipc,minfo,ulogio}` (single open, RAM copy, then read back).
   All outputs confined to `/tmp_bt` and fetched before any teardown.
3. **Probe physical run (read-only default mode).** Built in WSL with
   `arm-linux-gnueabi-gcc 15.2.0` (`-std=gnu11 -march=armv7-a -mfloat-abi=softfp
   -O2 -Wall -Wextra -Werror -ffreestanding -nostdlib -static â€¦`), pushed with
   readback hash verification (`b32987b9â€¦`), executed as
   `/tmp_bt/uvc_dma_probe_arm --out /tmp_bt/uvc_probe_e0348.json`, report fetched
   and validated: `schema=a6400-uvc-dma-probe/1 exit_code=0 notes=4`. The
   default mode opens no device node for I/O, performs no `/dev/mem` access, and
   sends no GET_JPEG transaction.
4. **Offline builds**: daemon static ARM build (`-Werror`, 0 warnings) and 299
   host assertions; native Android portable sources host-compiled under MinGW g++
   `-std=c++17 -Wall -Wextra -Werror` with 67 assertions; shader static validation
   PASS; Kotlin/Gradle structure verifier PASS (112 checks); repository suite
   `Ran 1196 tests â€¦ OK`.

## Observation

**Live snapshot (new/changed relative to older evidence):**

- `/dev/uipc` is **251:207**; `/dev/stream` **249:7**; `/dev/stream2` **249:8**;
  `/dev/dmpgles2` **248:29**; all `crwxrwxrwx`. `/dev/usb/video` (248:33) and
  `/dev/usb/audio` (248:32) are **ENOENT**; no `/dev/video*` exists.
- `/proc/kallsyms` (976,469 bytes read): `usb_gadgetcore_ioctl` **0x602b8844**
  (entry-hook target), `usb_gadgetcore_register_driver` 0x602b8610,
  `usb_gadgetcore_unregister_driver` 0x602b8560, `usb_gcw_start` 0x602bd7f8,
  `usb_gcw_stop` 0x602bd834, `dma330_mem_transfer_async` 0x5f49d768,
  `osal_snd_msg` **0x5f04916c**, `osal_rcv_msg_tmo` **0x5f0494f0**,
  `setup_req` **0x602b94a4**, `make_config_desc` **0x602bbc54**;
  `usb_sync_alloc/free_phys_buffer` per-module in `usbg_stillimage`
  0x5f03f038/0x5f03f15c (also `usbg_sen`, `usbg_buspower`, `usbg_storage`).
- UDC `/sys/class/udc/dwc3.0`: `state=configured`, `current_speed=high-speed`,
  `maximum_speed=super-speed`, `is_otg=0`, `active` = ENOENT.
- PID 149: 175 threads, 87 open fds, gadgetcore fd **86** this boot; earlier
  evidence recorded 82/85 â†’ **fd identity is not stable across boots**.
- Maps: `libosal_uipc` 0x0400f000, `libMWF` 0x040f7000, `libInfraUsbCmn`
  0x04161000, `libUsbControl` 0x04857000, `libObj` 0x05d18000, `libInfraRemote`
  0x0d049000, `libInfraPtpControl` 0x0e844000, `libInfraPtpExtCmd` 0x0ecd6000,
  `libptp` 0x10a28000, `viewUnified2` 0x155e6000, `/dev/dmpgles2` mapped at
  0x0b5a2000. `libInfraStreamingServer.so` remains absent.
- `/proc/osal/uipc`: single forward read = 43,737 bytes (not truncated at
  131,072 B cap), multi-stage as before; **the four queue ids are not printed in
  any decodable form** (0 occurrences in ASCII-hex, `0x`, or raw-LE forms) â€” a
  format hypothesis, not an absence of queues. `minfo` head `(27160)?68900000 â€¦`;
  `ulogio` head identifies log name `181H_Dslr-Diadem`, version 2.6.

**Architecture observations (from the recon reports):** the only transport ever to
carry real sensor frames to a real host is stock PC Remote PTP; the composite UVC
descriptor binds but its transport build never produced samples and the most likely
cause is a START-bridge endpoint mismatch (descriptor VS endpoint **0x84** vs bridge
match **0x81**); `0x9207` notch is the only effective control write and `0x9205`
absolute writes are acknowledged but not applied; tracked camera-side PTP control is
virtual UI-key injection; `bk.elf` is a flash-writing backup CLI, not a property
registry; realistic glass-to-glass is 40â€“55 ms, not <35 ms.

## Alternative explanations

- The 42-module set and absent UVC nodes simply confirm E0320/E0321 at this boot;
  they are **not** new UVC capability evidence.
- The probe's successful run proves the **tool** works and the read-only data path
  is safe; it is **not** evidence that UVC or GET_JPEG streaming works.
- Absence of queue ids in the `/proc/osal/uipc` text may be a format mismatch; it
  must not be read as "queues absent".

## Confidence and limitations

- High confidence on every live value above (direct reads, monotonic uptime, no
  reboot; snapshot preserved under `artifacts/analysis/recon-e0348/`).
- The architecture ranking is an evidence-weighted decision, not a hardware
  result: P1 (does a foreign `GET_JPEG` see frames in PC Remote) is **unmeasured**
  and is explicitly the experiment that decides Track B's frame source.
- Offline implementations are untested on hardware. Limitations are recorded in
  each tree's README: daemon (module audit gate B5, START bridge B3, `0xF002`
  semantics B4, single-fd constraint), Android (no SDK/NDK here â†’ Kotlin never
  compiled, APK never built, GL never run, zero latency measurements), probe
  (`--poll-get-jpeg` requires explicit authorization; host-check is synthetic).
- The mission target "<35 ms" is not supported by the evidence base; the committed
  target is â‰¤1.5 frame periods, â‰45 ms typical with measured p95.
- No streaming, no frame, no control write, and no UVC/PTP transfer is claimed.

## Dependent implementation / scenarios

`docs/ARCHITECTURE_UVC_MONITOR.md`; `probes/` (read-only ground truth + P1 experiment);
`camera-daemon/` (Track B, offline); `android-client-ref/` (Track A primary,
host-verified only); `camera-daemon/module/README.md` (module prerequisites, B3/B5);
`android-client-ref/docs/PROTOCOL.md` (PTP wire formats and the 0x9205 caveat).

## Next experiment

1. **P1 (decisive, needs explicit authorization):** fresh PC Remote session, host
   streaming `GetObject 0xFFFFC002`, run `probes/uvc_dma_probe --poll-get-jpeg 100
   --i-understand-foreign-get-jpeg` from `/tmp_bt`; record `err/ready/size`
   distribution and host fps before/during/after. Success = `ready=1` with a
   plausible JPEG prefix and no host-fps impact.
2. **Track A bench (no camera-write risk):** pipelined PTP client on the phone with
   per-stage timestamps; success â‰Ą25 fps for 60 s, control RTT p95, no reboot.
3. **Track B stage 2/3:** fix B3, add the transport-audit mode for B5, then one
   bounded RAM-only session: host UVC open + one sensor frame
   (`sensor_frames>0`) + PTP child usable, clean receipt with `reboot:false`.
4. Cleanup/verify: remove owned helpers from `/tmp_bt`, confirm MSC healthy, 42
   modules, `usbg_video` absent, `TracerPid: 0`.

## Verification receipts

All captured under `artifacts/analysis/recon-e0348/verification/` unless noted.

| Check | Command | Result |
| --- | --- | --- |
| Repository suite | `.\venv\Scripts\python.exe -m unittest discover -s tests -q` | `Ran 1196 tests â€¦ OK` (log `repo-suite-final.log`) |
| Probe ARM build | `python probes\build_probe.py` (system interpreter; WSL) | `built â€¦48144 B`, static ARM, 0 warnings (`probe-build-manifest.json`) |
| Probe host check | `python probes\build_probe.py --host-check` | help/smoke exit 0, report validated (`probe-hostcheck-manifest.json`) |
| Probe physical run | push + `exec /tmp_bt/uvc_dma_probe_arm --out â€¦` | `exit_code=0`, JSON validated (`camera-probe/run-receipt.json`) |
| Daemon ARM build | `wsl â€¦ camera-daemon/build.sh` | 628,000 B static ARM, `-Werror` 0 warnings (`daemon-build-manifest.json`) |
| Daemon host tests | `wsl â€¦ python3 test/run_host_tests.py` | 299 checks / 0 failures / PASS (`daemon-host-tests.log`) |
| Daemon identity check | `python camera-daemon\tools\deploy.py` | hash matches manifest, `built_not_deployed` (`daemon-deploy-check.log`) |
| Android native host compile | `android-client-ref\tests\host_compile.ps1` (MinGW g++) | compile clean, 67 assertions (`android-host-compile.log`) |
| Android structure | `python android-client-ref\tools\verify_structure.py` | PASS, 112 checks (`android-verify-structure.log`) |
| SGSR shader | `python android-client-ref\tests\validate_shaders.py` | PASS (`android-validate-shaders.log`) |

Note on the toolchain: the WSL image on this host has the ARM cross compiler but no
host C/C++ compiler; the daemon host tests and the Android native host compile
therefore use the Windows MinGW compiler (the daemon runner invokes it through WSL
interop, and `host_compile.ps1` is the Windows-native equivalent of
`host_compile.sh`). This is a host limitation, not a source limitation.

## Safety statement

Read-only scope only: no flash (`nflasha*`), no SD, no `/system`, no `/setting`,
no boot/preload change, no `/dev/mem` bulk scan, no external `/dev/stream` open, no
USB mode switch, no module load. All camera-side output confined to `/tmp_bt`;
helpers removed after use; camera left healthy in Mass Storage.
