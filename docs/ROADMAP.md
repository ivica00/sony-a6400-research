# Firmware execution roadmap

**Current status lives in the [README research status](../README.md) (E0352, 2026-11-11).**
The entries below are dated history: their test counts and boundaries describe the state at
the time of writing and are not updated retroactively.

UVC/PTP contributor track (2026-11-11, E0331): the USB lane is split into **process-local OSAL queues** (0x00CA8192, bit 15) and **sync-registered callback queues** (0x00CA0288 / 0x00CA01A4, flags=1). The async UIPC model never delivers the latter, so the boundary is `uipc_sync_callback_delivery_unmodelled`. A labelled SET_CONFIG ObjMsg injection reached the original `RcvMsg` and failed closed (OSAL assertion) - no FSM transition is claimed. Scoped workstreams and acceptance criteria are in [CONTRIBUTING_UVC_PTP.md](CONTRIBUTING_UVC_PTP.md); 952 tests pass. See [E0331](evidence/0331-usb-lane-local-queue-vs-sync-callback.md).

Emulator GUI path (E0309): the 308,622,155 / 68-thread state is mapped thread by thread (`artifacts/analysis/e0309-blocked-uipc-map.{txt,json}`): 37 `blocked_futex`, 21 `blocked_uipc` (all wait queues empty, only InfraNfc `0x018104BB` has a callback), 3 `blocked_poll`, 1 `blocked_read`, 4 runnable log/monitor threads. Named wait sites: `StlDateEvtLoop` on libObj date-event queue `0x012C032F`; `THREAD_INFRA1` on libdig_level `0x00A3035A` and `psm_dig_level_ma` on adjacent `0x00A3035B` (candidate request/reply pair); `UsbControl`/`UsbBusPower`/`BusPower` wait inside `libosal_uipc+0x50AF` on an OSAL event, not a queue. The app is service-initialized and idle waiting for producers; no wakeup is fabricated. Next: decode those producers/libdig_level pair and the OSAL event behind the USB tier, or continue the USB lane contracts. 874 tests pass; see [E0309](evidence/0309-blocked-uipc-dependency-map.md).


Emulator GUI path (E0308): the apparent idle state was an emulator artifact - finite `RCV_MSG_TMO` returned immediately, so `StlDateEvtLoop` spun (~167k ioctls / 19M instructions). Under `kernel-e0301`/`kernel-e0303` a positive finite timeout now blocks until a message (expiry not modeled, recorded as `blocked_timeout_not_modeled`; `tmo=0` stays a non-blocking poll; legacy baselines unchanged). Resuming `boot-e0314-live-usbwake.ckpt` (268,757,618) -> `e0315-live-block.json` reaches **308,622,155 / 68 threads** (30M budget) with only two blocking waits (UFW/UIPC ids `0x012C032F`, `0xA3035B`), then continues into `dmpgles2` init/ioctls and nanosleep scheduling. At the budget stop `THREAD_INFRA1` waits on `0xA3035A` and `StlDateEvtLoop` on `0x012C032F`; `UsbControl`/`UsbBusPower`/`BusPower` remain blocked, otgcore `config=None`, no `viewUnified2`/OSD mapping, no GUI frame. Next: identify the receivers/producers of those UFW ids, or continue the USB lane (receive id/inbound SETCONFIG, buspwr port type, `0x008F013A` consumer). 874 tests pass; see [E0308](evidence/0308-uipc-timeout-blocking-and-real-wait.md).


Emulator GUI path (E0307): a third authorized read-only dump captures `/dev/nflasha2` (252:2, 20,971,520 B, SHA-256 `4d3269e5…`, FAT12, 62 files/5 dirs; `/setting`). New opt-in `--setting-service observed-nflasha2` materialises `/setting` read-only from the hash-checked dump; `GuestFilesystem` now supports read-only directory descriptors and bounded `getdents64`; the observed UIPC unregister ioctl `0x80000009` (`{queue 0x4b024e, handle 4170}`) is a `kernel-e0301`/`kernel-e0303` contract with identity/inflight guards. Runs: `e0312-live-setting.json` 235,810,681 stops at the unregister after reading `/setting/updater/dat4`; `e0313-live-setting2.json` serves both unregisters and reaches **254,922,253 / 67 threads** (timeout) with libInfraIPTC/libInfraCacheMgr loaded, ending in an `RCV_MSG_TMO` poll loop (tmo 0 → -1022, no boundary); `e0314-live-usbwake.json` reaches 268,757,618 (timeout) with the verified VBUS body + corrected subtype-2 event accepted but **no USB FSM transition** (UsbControl/UsbBusPower/BusPower blocked, otgcore `config=None`, no viewUnified2/OSD, no GUI frame). Next: USB receive-id/inbound SETCONFIG, buspwr port-type reply, `0x008F013A` consumer, or the poll-loop consumer/timing. 873 tests pass; see [E0307](evidence/0307-nflasha2-setting-namespace-uipc-unregister-and-idle-state.md).

Emulator GUI path (E0304): the pre-MPR injectable base is `boot-e0301-live-receiver.ckpt` (214,289,958, clean timeout). The verified 16-byte VBUS UIPC body on queue `0x012002DA` is now delivered to its original async consumer (handle 4106), which frees the message, and the model completes the callback without touching the message; the run reaches the `/dev/nflasha4` MPR ioctl `0x80014123` at **232,049,966 / 55 threads**. No USB FSM transition: UsbControl/UsbBusPower/BusPower remain blocked, otgcore config is unset, viewUnified2/OSD are not loaded and no GUI frame exists. The `/dev/usb/event` record callback must be the state's registered pointer (`0x562FB0DD` here); a stale value faults in the consumer. A clean pre-fault resume still hits the tzset `memory_boundary` at 185,772,548, so the IT workaround is not a fix. The shared next gate is an authorized read-only MPR content dump; alternatively resolve the relayed-notification consumer (`0x008F013A`) and UsbControl's runtime receive id. 857 tests pass; opt-in `--usb-function-policy descriptor-table` session wiring is in place. See [E0304](evidence/0304-preboundary-usb-injection-and-vbus-delivery.md).

Emulator GUI path (E0302): the E0301 checkpoint's DataflowInfra symbol gate is resolved with a targeted `_dl_fixup` IT-latch workaround (the `mov r4,r0` was skipped; the provider was already in scope). The checkpoint path reaches **231,909,376 / 55 threads**, opens `/dev/dmpgles2`, `/dev/stream2` and the raw MPR `/dev/nflasha4`, answers `lseek(SEEK_END)` from the verified 12,582,912 bytes, and stops at the read-only MPR ioctl `0x80014123` (no preserved MPR image, no writable internal flash). The fresh path passes `/dev/dmpgles2` with a clone-derived per-thread kernel task record and reaches 185,358,896/54 threads under `--stream2-device open-only`. The 185.77M libc tzset stop is a Thumb `pop`/literal-pool CPU-state defect of the same family (U3/U3b). OSD A/B remain unmapped; no GUI frame. 854 tests pass; the [E0303 readiness note](evidence/0303-usb-uipc-otgcore-uvc-ptp-readiness.md) records the UVC/PTP-reusable USB/UIPC/otgcore/MSGID contracts and the exact MPR boundary.

Emulator GUI path (E0301): use the [camera-observed full argument list](evidence/0301-uipc-lifecycle-camera-argv-and-checkpoint-retry.md), not phase `i` alone. Opt-in UIPC completion/sync-wrapper/dynamic-ID contracts and version-2 checkpoint retry controls pass; residual cold-resume divergence remains. Fresh full-argument startup traverses a bounded observed-running kikilog profile. Next establish original phase gating and THREAD_APP; no OSD/GUI frame. 798 tests pass.

Emulator GUI path (2026-11-10): [E0300](evidence/0300-uipc-proxy-start-and-vbus-callback.md) fixes the missing UIPC pool option stores under an opt-in policy. Original firmware starts four proxies and consumes a verified VBUS notification. Next establish callback completion ownership and sync-registered queue 0x009c015b; preserve the completion guard because the VBUS callback frees its message. No GUI frame/OSD mapping. 782 tests pass; E0298's SMAPH-S30 rasterizer boundary remains.

Current UVC/PTP overview (2026-11-09, through E0239): [UVC_PTP_STATUS.md](UVC_PTP_STATUS.md). E0234 physically answered one fixed read-only `IFSYS getdriveinfo A` query. E0236's physical journal write was refused before any file existed, and the camera self-rebooted intermittently around PC Remote entry, so physical collector sessions are stopped. E0237 executed the original path functions offline: the `0x80000041` was the 8.3 normalizer rejecting the long underscored filename, not an empty letter table. E0238 rebuilt the collector with the 8.3 target `A:/A6400J.DAT` and passes 21 ARM admission, 19 mocked collector cases and 624 tests, but it is not physically deployed. E0239 adds the first offline UVC contract: a bounded JPEG SOF dimension parser (15 host cases, ARM compile) that is not yet wired into the Update path. The SD journal remains unwritten; composite child enumeration is proven, sensor streaming and simultaneous camera-control transactions remain unfinished. Earlier entries below retain historical experiment status.

[E0144](evidence/0144-native-jpeg-receiver-ownership-and-dma-allocation.md): Native JPEG receiver/queue ownership source-checked; reference DMM UnitType0x50e absent on a6400. Kernel-owned 256 KiB lifecycle succeeds, but must gain metadata/per-slot bounds before streaming. Next finish synchronous SET_PATH conversion, dimension/capacity and DMM ownership contracts, then acquire one native JPEG. No sensor configuration issued; module unloaded, debugger intact, 599 tests pass.

[E0143](evidence/0143-uvc-720p-test-transport-and-30fps-verified.md): Endpoint/START, decoded MJPEG and ~30 FPS static-pattern transport verified on camera; local monitor HTTP integration works and Mass Storage is restored. Next implement verified native JPEG producer/DMM ownership using the unresolved 0x01670464 receiver. Static test-pattern transport is not sensor LiveView. 599 emulator tests and 53 ARM controls pass.

[E0142](evidence/0142-uvc-bulk-endpoint-bridge-and-physical-boundary.md): Next recover Mass Storage from the final UVC experiment and preserve surviving kernel logs. Resolve the original START/transfer or teardown stall before further deployment; then obtain a decoded host frame, measure delivery, and connect native JPEG production/CinemaHUD. Current feeder repeats a static test JPEG. 599 emulator tests/53 ARM controls pass; physical streaming remains unverified.

[E0135](evidence/0135-uvc-port-device-node-and-gadget-callback-abi.md):
device-table and callback ABI mismatches are verified. A private-node-only
reference object builds offline; next prove the descriptor/callback bridge,
endpoint/DMA lifetime and rollback before any camera installation.

[E0134](evidence/0134-zve10-v203-reference-uvc-stack-and-jpeg-path.md):
ZV-E10 reference now supplies actual Sony UVC stack and720p descriptors.
Audit usbg_video/kernel/devno ABI and gadget type12 registration before any port;
trace reference configuration queue01670464 separately from JPEG-fetch0167046a.
No a6400 UVC module is installed or active.

[E0133](evidence/0133-gadget-infrastructure-ptp-gates-and-liveview-test-plan.md):
no active configfs/UVC function demonstrated; original PTP metadata/transfer
filters are distinct. Next resolve JPEG queue0167046a receiver and buffer ownership,
then baseline one frame before any RAM-only width change. No camera mod armed.

USB monitor investigation (2026-11-07): [E0132](evidence/0132-usb-liveview-jpeg-source-and-width-gate.md)
establishes an original JPEG source path and a normal320/640/1024 width gate.
Next verify the lower-level encoder/path0x20 and frame ownership, capture one
decoded frame, then establish USB transport and measured1080p/30 throughput.
No camera streaming mode is enabled; the configuration-derived width path is
an investigation candidate, not an established1920-pixel capability.

E0113 confirms active-MENU reference1 versus USB0, but also a changed resource
cache head. The narrow release primitive passes; whole activation must wait for
coherent coupled list/model/allocator inputs (E0114). Do not repair this by
setting counters or fabricating/removing list membership on the host.

E0111 supersedes the accounting boundary below: original accounting, locks and
bookkeeping-node free now execute. The next stop is an original zero-reference
release diagnostic for an image pointer retained in MENU but read later in USB.
E0112's verified waiting observer will capture the active menu/resource together;
validate that evidence before changing reference counts or admitting underflow.

Latest checkpoint, 2026-11-06: original active-menu lookup and geometry, model/row
association, geometric hit checks and separate selection controls are established
on retained camera snapshots (E0106–E0108). E0109 activation reaches a guarded
resource-manager write after an explicit main-thread/TLS control; full activation
and the original UI input/thread route remain open. Main-menu touch is incomplete.
Next establish resource-manager side effects and the correct UI context, complete
refresh/activation, then validate a touch modification on the physical camera.
Follow the [camera/emulator workflow](LIVE_CAMERA_EMULATOR_WORKFLOW.md).
The MonDrv checkpoint workaround remains an explicitly unvalidated host-created
queue; original initialization is pending (E0097 output-backpressure evidence).

Sugilite display pipeline handshake and render loop: [E0070](evidence/0070-sugilite-render-loop-and-surface-transfer.md) identifies display panel polling in libObj.so at 0x72baf0 and resolves it by configuring sub_device_id: 1 in GuestGles. Main process reaches continuous steady-state rendering, executing 61,582 complete frame render cycles (123,168 GLES_LOCK_SEMAPHORE, 123,166 GLES_UNLOCK_SEMAPHORE, 61,582 GLES_GET_RESOURCE_SUB, 61,582 GLES_GET_POWER_STATE_ALT) and performing 800-element display surface memory transfers via ARM memcpy in libc at 0x502601c0. 486 tests pass. Next connect media detection pipeline (libInfraMediaDetect.so) for read-only SD E:\ integration.

USB bus power driver contract and 100M instruction milestone: [E0069](evidence/0069-usb-buspower-driver-contract-and-100m-instruction-milestone.md) implements GuestUsbBusPower (/dev/usb/buspwr, major 248, minor 13) with verified ioctl contracts (0xf200-0xf220). Firmware loads all three USB modules (usbg_buspower.ko, usb_darwin.ko, usb_buspwr.ko), opens /dev/usb/buspwr, and executes SetPortState (0xf20c). Execution reaches 100,000,000 instructions (1,013,768 serviced syscalls) with 11 concurrent threads, emitting '!!! GLES Vecgen disabled.' and executing the active Sugilite GPU/display worker (thread 1008, ModelYuvMuteToInstance in libObj.so). 486 tests pass. Next ModelYuvMute state transitions and SD media path integration.

GPIO contract and USB bus power boundary: [E0068](evidence/0068-gpio-contract-and-usbg-buspower-module-boundary.md) advances main process execution to 81,686,763 instructions (1,051 serviced syscalls). The process binds /dev/gpio (fd 12, major 240, minor 0), executes two authentic GPIO_CMD_SET_MODE (0xc0104702) ioctls, closes fd 12, loads libUsbBusPower.so, and maps /usr/kmod/usbg_buspower.ko before stopping at init_module (r7 = 128). 476 tests pass. Next USB bus power module contracts and device integration.

GLES binding and GPIO boundary: [E0067](evidence/0067-gles-kernel-binding-and-gpio-boundary.md) advances main process execution to 81,540,245 instructions. The process successfully binds /dev/dmpgles2 (fd 10), executes 10 authentic Sugilite GLES ioctl/mmap calls (resource queries, lock semaphores, 128 KiB buffer mapping, completion signals), maps /dev/mem, and loads downstream Bluetooth libraries before stopping at /dev/gpio (open flags 2). 468 tests pass. Next establish original GPIO driver contracts and device numbers.

Task copy limits and GRM thread resolution: [E0066](evidence/0066-kernel-task-copy-limits-and-grm-vdf-identity.md) resolves task 358 comm as THREAD_INFRA0 and adjacent dead task 356 as real grm_dn_vdf_if, establishing userland origin via libObj.so and queue 0x0080003b. User space boundary 0x5f000000 verified.

GLES ownership: [E0065](evidence/0065-original-gles-new-owner-lifecycle-and-process-binding.md) verifies original new-owner allocation and full open/query/release lifecycle. Next establish main-process task/address-space creation and driver ownership; observed selected-task identity and address-limit mismatches now stop explicitly. Cache/GPU hardware and framebuffer output remain open.

Original captured GLES: [E0064](evidence/0064-captured-gles-open-kernel-locks-and-queries.md) executes original open and kernel locks to return, verifies ioctl queries through original kernel copy helpers, and identifies captured owner task/stack backlinks. 423 tests pass. Next establish new-process kernel ownership/address space and cache-controller/DMA effects before GPU submission/completion integration. Captured open does not supply a main-process reply; its latest boundary remains E0063 and no framebuffer pixels are available.

Current graphics boundary: [E0063](evidence/0063-backup-nread-decoder-and-gles-boundary.md) resolves backup operation 30, preset descriptor decoding and reply-queue wake defects. The process reaches `/dev/dmpgles2` at 80,739,451 instructions under explicit existing experiment policies; 411 tests pass. Next establish original GLES kernel objects, task/lock and cache/DMA state before GPU command submission and IRQ/completion modeling. Original open/setup prefixes stop at unsupplied kernel/cache contracts; no framebuffer image is demonstrated.

SD callback/ABI: [E0058](evidence/0058-sd-read-ioctl-and-preparation-state.md) connects original configured read callbacks to ioctl10f and kernel descriptor/range/status handling. Next original serialized transfer wiring, card-state reference producer/semaphore/control initialization, then MWF device path.362 tests pass; no completed SD read or main/UI advance.

Current user scope: [E0057](evidence/0057-sd-communication-layers-and-original-read-bounds.md) investigates SD communication, superseding the earlier injection/update direction. Next resolve MWF device-path responder, media read callback+cc, kernel routing to MMCP read and preparation helper16328 before hardware/DMA.361 tests pass; no physical SD transfer or UI advance claimed.

User-directed focus: [E0056](evidence/0056-sd-card-inputs-and-update-surface.md) begins read-only SD/parser/update investigation using card E:\. Next trace actual RAW/JPEG parser reads and the MS-source/boot-marker consumers; separate external-device updates and internal staging from camera-body SD reachability.357 tests pass. UI research is preserved at E0055/E0034, not advanced by this survey.

Trace transport dependency: [E0055](evidence/0055-original-trace-uipc-allocator-runtime-state.md) verifies original queue008f013a selects the kernel wrapper, constructs ioctl8000000a arguments, and stops at uconf descriptor read2898 after32 instruction events. Next establish original UIPC initialization/pool state and driver allocation effects before a reply.354 tests pass; main/UI unchanged.

Client object constructed: [E0054](evidence/0054-original-pthread-constructor-return-and-trace-ipc.md) observes original constructor/pthread return and then trace-message allocation dependency in a direct lookup initializer. Next support original trace allocator/transport under declared UIPC state before physical mapping; kernel callback-thread contract remains independent.354 tests pass; no main/UI advancement.

Loader field resolved for selected probe: [E0053](evidence/0053-original-loader-to-sysconf-constructor-chain.md) executes original loader producer and constructor/libc consumer to pthread_mutex_init. Next identify actual pthread provider and execute null-attribute initialization with bounds; kernel callback thread/transport still separate.351 tests pass; no main/UI advancement.

Client constructor: [E0052](evidence/0052-original-client-constructor-and-page-size-dependency.md) executes guarded original object initialization to sysconf30; source analysis identifies _rtld_global_ro+16 as the preceding page-size dependency. Next establish that state and continue original initialization; callback thread/locking/IPC remain separate.351 tests pass; no main/UI advancement.

Callback state: [E0051](evidence/0051-original-grm-mutex-thread-state-boundary.md) verifies original mutex prefix and stops at unknown kernel-stack state without modifying reply/retain data. Next identify callback-thread context/mutex effects and separately trace original client constructor.348 tests pass; main/UI unchanged.

Client reply handling: [E0050](evidence/0050-original-ma-client-status-consumption.md) verifies original status consumption with fresh producer output under explicit constructed framing. Next establish callback mutex/transport state and original client object construction before any package-WBI process service.348 tests pass; no main/GUI advancement.

Startup lookup path: [E0049](evidence/0049-original-extent-failure-and-startup-lookup-branch.md) observes original allocation return-257/outputffff with cleanup, while original libObj's successful lookup branch skips duplicate open. Next verify lookup-client reply consumption and package-WBI service/mutex/transport effects.345 tests pass; main/UI unchanged.

Original allocation state: [E0048](evidence/0048-original-dmm-allocation-state-transitions.md) observes a new record65/internal handle0441 and eleven original state stores, stopping before inner extent allocation at .text+a658. Next verify that function's ownership/rule effects before permitting further mutations.345 tests pass; no allocation success/main/UI advancement.

DMM ownership: [E0047](evidence/0047-original-dmm-handle-and-captured-ownership.md) connects unit0x280 to captured GRM handle0417 through224 original instructions, distinguishes active/stale records and checks extent ownership. Next bounded original Alloc(280,1) with explicit state-mutation and hardware guards. 342 tests pass; no main/GUI advancement.

Open contract: [E0046](evidence/0046-original-grm-open-and-dmm-handle.md) confirms original open requires DMM even with captured gl_common present. Resolve captured unit0x280/handle construction and original allocation/access-info effects next; returned address/size alone are insufficient. 342 tests pass; no main/GUI advancement.

Original lookup: [E0045](evidence/0045-wbi-page-tables-and-original-grm-lookup.md) executes the captured GRM lookup through a selected page-table root, including original kernel comparison and retain mutation. Next investigate original open for unit0x280/flags0 against existing captured state, including lifecycle/locks. 342 tests pass; main/UI boundary unchanged.

Captured allocator: [E0044](evidence/0044-wbi-grm-reciprocal-list.md) checks a six-node reciprocal list containing gl_common. Next establish VMALLOC/page-table translation and execute original lookup with explicit mutation bounds; captured ownership must be reconciled with startup before a service reply. 339 tests pass; no GUI advancement.

Recovered logging input: [E0043](evidence/0043-wbi-memory-and-recovered-logging-input.md) identifies logging configuration/state inside compressed partition-5 WBI memory and verifies the DMM lookup with 71 original instructions. Next establish an explicit package-WBI state/ownership policy and investigate the captured allocator; timer/device state remains separate. All 339 tests pass; application boundary unchanged.

Latest clarification: [E0042](evidence/0042-elapsed-timer-versus-calendar.md) establishes software microsecond units and separates calendar state from the elapsed timer. Date logic is a consumer, not a substitute for missing hardware state. All 334 tests pass; application boundary unchanged.

Latest timer prerequisite: [E0041](evidence/0041-freerun-existing-state-and-timer-message-abi.md) verifies existing-mode preservation and the registered counter-message layout. Initial counter/control state and device effects remain required; a transport acknowledgement is not a timer result. All 331 tests pass; no application/GUI advancement.

Latest timer gate: [E0040](evidence/0040-utimer-clock-origin-and-rollover.md) resolves original rollover arithmetic and identifies the independent freerun source `0xf240310c`. Establish that source's hardware/epoch contract and dispatch/scheduling state before timer replies; the missing logging input remains independent. All 328 tests pass; application boundary unchanged.

Research tooling: [E0039](evidence/0039-dependency-planner-and-evidence-cache.md) delivers bounded dependency graphs, static cache validation and retained REA reuse. Use [the workflow](DEPENDENCY_WORKFLOW.md) before repeated module analysis; it does not resolve runtime input or hardware gates. All 326 tests pass; no new GUI milestone.

Latest gate: [E0038](evidence/0038-timer-programming-and-setting-partition.md) verifies original timer programming stores and connects the missing logging file to `/dev/nflasha2` mounted at `/setting`. Establish timer effects and an identified logging configuration/producer before DMM allocation replies. All 318 tests pass; no new application/GUI milestone.

Latest prerequisite progress: [E0037](evidence/0037-timer-pointer-producer-and-native-wsl-rea.md) derives timer pointers through original driver slices and composes them with counter reads, stopping at unknown hardware. Next resolve clock-register semantics and the logging configuration's physical backing/subsystem layout. Direct WSL REA is restored; 315 tests pass, with no application boundary change.

Latest dependency trace: [E0036](evidence/0036-dmm-timer-runtime-and-log-configuration.md) identifies the timer runtime table at `0x604be020` and original boot option `ulogio_initfile=/setting/ulogio.bin`. Trace their producers before supplying DMM timestamps or log-memory addresses. No new process/UI milestone; 310 tests pass.

Latest allocator research: [E0035](evidence/0035-dmm-configuration-and-boot-reservations.md) identifies unit `0x280`'s configured 32 MiB extent through original ARM parsing. Finish timer and shared reservation-log prerequisites, original boot reservations, then actual allocation/open before supplying a GRM-MA reply. No application boundary change or GUI milestone is claimed; 306 tests pass.

## Objective and definition of done

Execute original and modified a6400 firmware with observable behavior produced by the original software and validated device interfaces. Publish compatibility per scenario and firmware version, not as a blanket promise of exactness.

A validated scenario requires identified firmware and patch hashes, known persistent state, reproducible external inputs, original code on the affected path, zero undeclared substitutes, and comparison with the physical camera. Timing and image-pipeline equivalence require their own evidence.

## Phase 0 — Preserve and establish an honest baseline

Status: organization, local inventory, initial strict-mode guards and execution reports delivered. See [Phase 0 progress](PHASE0_PROGRESS.md) for commands, evidence, and remaining provenance/loader work. Full Phase 0 exit criteria are not yet complete.

Tasks:

- Preserve firmware, extracted trees, upstream tools, photos, and backups. Separate generated artifacts from source.
- Label the current simulator/HLE harness as legacy research. Preserve old launch commands.
- Record the no-firmware menu experiment and every known interception.
- Inventory Python versions, installed packages, native libraries, upstream revisions, firmware hashes, and licensing/provenance. Produce dependency locks after checking which packages are actually needed.
- Add explicit research and strict modes to the harness. Strict mode must reject unknown symbols, unsupported relocations, unmapped access, dummy widget objects, and unimplemented services.
- Report normal return, execution fault, instruction budget exhaustion, and timeout separately. Record PCs and unresolved symbols.
- Replace optimistic startup messages with measured execution status. Do not imply that existing screens are firmware output.

Deliverables: environment manifest, immutable input manifest, interception inventory, structured execution report, preserved smoke workflow.

Exit gate: a screen cannot be labeled firmware generated without a recorded original rendering path; strict runs stop on an intentionally unsupported dependency. Existing research mode remains usable and clearly labeled.

## Phase 1 — Identify the real platform and boot chain

Dependency: Phase 0 input manifests. This phase gates backend selection.

Progress: initial ELF/platform findings are recorded in [E0001](evidence/0001-platform-and-loader.md). The runtime dependency and TLS/COPY requirements are identified; the original UI-host process and complete boot chain remain open.

Further progress: [E0002](evidence/0002-original-process-startup.md) traces the conditional `init` → `bootin` → `im.elf` path and original module-loader routine, recovers filesystem symlinks, and proposes [original interpreter execution](experiments/0001-original-interpreter.md). Normal mode selection and full boot remain unverified.

Execution progress: [E0003](evidence/0003-original-interpreter-boundary.md) reproduces 1,183 original interpreter instructions to its first `brk(0)` syscall. The probe supplies no syscall responses; application entry, original UI startup, and full-system milestones remain open. This is a bounded Unicorn process experiment, not a selected full-machine backend.

Guest contract progress: [E0004](evidence/0004-guest-brk-contract.md) preserves that baseline and adds optional stateful `brk` handling, reaching `uname` after 2,222 instructions. The original process is not yet fully linked or started.

Identity progress: [E0005](evidence/0005-guarded-kernel-identity.md) uses guarded kernel-image identity data and reaches the first filesystem check at 3,091 instructions. Read-only guest filesystem contracts are next; no application/UI entry has been reached.

Filesystem progress: [E0006](evidence/0006-read-only-guest-filesystem.md) adds bounded read-only image contracts and reaches 5,078 instructions. That policy preserves the stop before successful ARM stat/fstat metadata and a library read.

Metadata progress: [E0007](evidence/0007-guarded-inode-metadata.md) recovers original ext2 inode metadata and implements an explicit guarded ARM stat/fstat subset. The original linker opens and reads 512 bytes of its first library, then stops at unknown `st_dev` after 6,493 instructions. Next: establish the real mount/device identity, then implement the first verified file-backed mapping. Complete runtime metadata and application/UI entry remain open.

Runtime-state correction: [E0008](evidence/0008-runtime-mount-boundaries.md) recovers 22 original mount records and 88 device records. Compressed/direct mount choice remains unselected, and an attempted writable `/etc` overlay makes static absence insufficient. The new mount-aware check stops at unsupplied `/etc` after 3,091 instructions. Prioritize device registration, boot selection, and an identified `/etc` state before claiming a camera-faithful namespace; preserve the deeper snapshot run as a separate research baseline.

Storage consumer progress: [E0009](evidence/0009-storage-driver-consumers.md) traces the original eMMC driver's table copies into disk parameters and establishes conditional decompressed partition numbering. A bounded nine-instruction original window confirms field copying without kernel responses. Next trace compressed-header validation and acquire identified runtime state; mount choice, `/etc` contents, full platform and application startup remain open.

Header progress: [E0010](evidence/0010-compressed-header-comparison.md) traces the sector-read dependency and executes the original magic comparison. Preserved updater images mismatch `TPZL`; a magic-only control demonstrates that a match is insufficient for complete validity. Next establish the updater's physical write/compression representation or obtain identified physical header state. Device selection and the `/etc` runtime overlay remain unresolved.

Updater progress: [E0011](evidence/0011-updater-image-write-path.md) traces the image-copy loop through the common library to `write` and improves ARM PLT identification. No compression call is observed in that loop; virtual input reading and downstream device writes remain untraced, so no end-to-end physical representation is claimed. Resolve those edges before selecting device identities.

Buffer/storage progress: [E0012](evidence/0012-ring-buffer-and-storage-write.md) resolves the RingBuffer dispatch candidates and traces a helper's compressed-write rejection versus ordinary sequence-write branch. Next establish the producer bytes, block-worker callback assignments and final hardware-write path. Static buffer copies and candidate callbacks do not select runtime `st_dev` or supply `/etc` state.
 
Producer and physical storage progress: [E0013](evidence/0013-producer-and-physical-storage-trace.md) connects the updater's `crypter.elf` pipeline (`Dec_Scramble` decryptor to `RingBuffer::WriteData`, loader execution to `UpdaterBody::Execute`) and traces `emmc_blk_kthread` directly into `emmc_write`, establishing the decompression callback guard table (`uz_emmc_do_compress`) versus `emmc_seq_write` -> `write_block_retry` (CMD24/25) -> `exec_emmc_data_cmd` -> `sdhci_emmc_exec_data_cmd` (DMA setup). Nonvolatile flash contents, device identity selection and `/etc` runtime state remain open.

Boot selection and root device progress: [E0014](evidence/0014-boot-selection-and-root-device.md) extracts 88 device entries from `kmod/devno.ko` (`udif_devnodes`) and 22 mount definitions from `sbin/init` (`mnts`). Block major 252 is proven across all `nflasha` / `dnflasha` devices. For `/rootfs` (partition 7, containing `/lib`), Linux ARM EABI `st_dev` resolves to `0xfc87` (compressed `/dev/dnflasha7`) and `0xfc07` (uncompressed fallback `/dev/nflasha7`). For `/etc`, `sbin/init` mounts `/dev/nflasha10` (vfat, read-write, `0xc0ed0490`) over an empty static directory, proving why static firmware images cannot provide `/etc/ld.so.preload` or runtime camera configuration.

Guarded mmap2 and library load progress: [E0015](evidence/0015-guarded-mmap2-and-library-load.md) introduces the explicit `mmap` syscall policy (`GuestMmap`). Supplying verified major-252 `st_dev` (`0xfc07` rootfs, `0xfc0f` usr) resolves the 6,493-instruction linker deduplication boundary. The probe resolves an emulator Thumb-2 IT block quirk and advances through **56,230 instructions**, mapping and loading all 12 shared libraries required by `/usr/bin/im.elf`, before halting at Linux's `__kuser_cmpxchg` kernel helper vector (`0xffff0fa0`).

High vectors and shared library init progress: [E0016](evidence/0016-kuser-helpers-and-shared-library-init.md) introduces the explicit `kuser` syscall policy (`GuestKuser`). The 160-byte kernel helper template is extracted directly from verified `vmlinux.bin` (offset `0x388fe0`, version 5). Servicing `sys_arm_set_tls` (syscall `0xf0005`), thread initialization (`set_tid_address`, `set_robust_list`, `rt_sigaction`, `rt_sigprocmask`, `ugetrlimit`), and GNU_RELRO post-relocation page protection allows the dynamic linker to complete relocations across all 12 libraries and execute library constructors. Execution advances to **2,029,074 instructions**, reaching Sony's `/usr/lib/libosal_uipc.so` constructor calling `open("/dev/uipc", O_RDWR)` before cleanly stopping at the fail-closed unsupported filesystem boundary.

Main application entry point and UIPC progress: [E0017](evidence/0017-application-entry-and-uipc-contract.md) introduces the explicit `uipc` syscall policy (`GuestUipc`). Character device `/dev/uipc` ioctls (`__k_4u_connect`, `__k_4u_valloc_msg_wait`, `__k_4u_snd_sync_msg`, `__k_4u_free_msg`) and shared memory mappings are implemented based on `/usr/kmod/osal_uipc.ko` and `/usr/lib/libosal_uipc.so`. At instruction **2,073,233**, dynamic linking completes and original code **reaches the main application entry point** of `/usr/bin/im.elf` (`0x9140` / Thumb `0x9141`). Sony's application executes task 94 startup (`\t\x00  94 B  Ib 094_main()`) and advances through UIPC message exchanges to **2,107,153 instructions**, stopping cleanly at the standard I/O layer on `fstat64(1)` (`inherited_stdio_not_supplied`).

Standard I/O and thread creation progress: [E0018](evidence/0018-standard-io-and-uipc-callbacks.md) implements the standard I/O contract (`GuestStdio`, verified `/dev/console` metadata and `TCGETS`), UIPC callback registration (`0x80000008`) and direct synchronous messaging (`0x80000006`). After resolving an emulator Thumb-2 IT-block handling issue in `_int_malloc` at `0x50259c24`, Sony's `/usr/bin/im.elf` executes through all five Task 94 initialization phases (`094_0` through `094_4`), registers asynchronous message callbacks, and reaches **2,218,147 instructions**, halting at Linux ARM EABI `sys_clone` (syscall 120 / `__NR_clone`) during `pthread_create`.

Multithreading and infrastructure threads progress: [E0019](evidence/0019-multithreading-and-sys-clone.md) introduces the explicit `threads` syscall policy (`GuestThreads`). Servicing `sys_clone` (syscall 120), `sys_gettid` (syscall 224), `sys_prctl` (syscall 172 `PR_SET_NAME`), `sched_setscheduler` (syscall 156), `sched_setaffinity` (syscall 242), `sys_futex` (syscall 240 `FUTEX_WAIT`/`FUTEX_WAKE`), and `sys_exit` (syscall 1), the engine resolves the thread synchronization barrier in `libosal_utm.so`. All three Sony infrastructure threads (`THREAD_INFRA0`, `THREAD_INFRA1`, `THREAD_INFRA2`) are spawned, executed, and cleanly terminated. Execution surges to **2,367,687 instructions**, reaching the primary Task 94 event loop at `/dev/uipc` ioctl `0x80000001` (`UIPC_CMD_WAI_SEM_TMO` on Semaphore `0x83037a`).

UIPC semaphores, message queues, and continuous event loop progress: [E0020](evidence/0020-uipc-semaphores-and-event-loop.md) implements the UIPC binary semaphore contract (`0x80000000` - `0x80000002`), asynchronous message queue dispatch (`0x80000003`, `0x80000004`, `0x80000007`), TLS context restoration for main thread returns, and Linux ARM EABI `sys_nanosleep` (syscall 162). A 4th infrastructure thread (TID 1004) executes cleanly. The original Sony camera application enters its **continuous 1 Hz event loop heartbeat**, executing **8,777,210+ instructions** and completing over **17,000 heartbeat cycles** without error. All 193 unit tests pass.

Event dispatch and display subsystem discovery progress: [E0021](evidence/0021-event-dispatch-and-display-subsystem.md) decodes the Task 94 message callback (`0x9a5c`), mapping event IDs `0x00940031`–`0x00940037` to camera initialization Phases 1–8. Inspection of `libIMDB.so` (`.data.rel.ro`) recovers 198 camera subsystem definitions, demonstrating that Phase 1 triggers Electronic Viewfinder (`libDpro_EVF.so`), Business Initializer (`libBizInitializer.so`), Application Framework (`appFw.so`), and GUI Windowing (`gui.so`). Discovers the display stack in `libObj.so` (`ux::wgtsys::WidgetSystem`, `GRM_fbrm*`, `ObjDisplay_Create`) using Linux framebuffer `/dev/fb0` and DMA controller `/dev/dmac`. Aligns the UIPC message receive ABI (`out_msg` user destination writing) and proves fault-free processing of injected Event `0x00940031` through state transitions `94 B  Ib 094_0` -> `94 E  Ib 094_0` and clean message deallocation. 195 unit tests passing.


Tasks:

- Inventory every extracted partition and executable: format, ISA, endian order, ABI, entry point, dependencies, and likely role.
- Inspect boot scripts, startup services, kernel/configuration evidence, device descriptions, driver constants, and communication endpoints.
- Identify all relevant processors/firmware domains; determine which are included in the updater and which would require independent dumps.
- Establish CPU configuration, reset/start addresses, memory regions, interrupt architecture, clocks, storage layout, display interfaces, and input path. Mark each item verified, inferred, or unknown.
- Trace one physical button from its input device/service to UI dispatch; trace one UI resource to its loader and renderer.
- Determine required nonvolatile/calibration/model/region data and whether current backup tooling supplies it. Never treat an update package as a proven full-device image.
- Gather passive camera observations and permitted read-only diagnostics. Track uncertainty rather than replacing it with guessed constants.

Deliverables: platform evidence matrix, boot graph, partition map, dependency graph, missing-artifact list, selected UI-path map.

Exit gate: every fact needed for the first execution experiment has a source location or a stated unknown; the team can explain how the target UI starts and what hardware it requires. Unknowns that prevent startup remain explicit blockers.

Package H follow-up: [E0023](evidence/0023-package-h-entropy-boundary.md) reaches the original stack-guard entropy dependency after 41,953,485 instructions. Next establish `/dev/urandom` semantics and authentic boot-event producers/payloads before display initialization. Zero framebuffer transactions were observed; the UI gate remains open.

Entropy contract follow-up: [E0024](evidence/0024-urandom-dispatch-and-read-boundary.md) verifies the static 1:9 node and bounded original kernel dispatch. Optional `--urandom-open` reaches the first entropy read at 41,955,226 instructions and supplies zero bytes. An identified runtime pool or justified replay/model remains required; original display initialization is still unreached.

Boot producer follow-up: [E0025](evidence/0025-boot-producers-and-argument-selected-startup.md) establishes seven argument-selected launch requests in original `bootin.elf`. The `i` process loads `libObj.so` without injected events but stops before entropy bytes; `a` requires thread/context ownership investigation. Use the recovered producer structure to replace guessed stimulus assumptions only as prerequisites become verified. Component log strings and budget exhaustion do not close the UI gate.

Thread-context correction: [E0026](evidence/0026-thread-tls-and-stack-discard.md) restores hardware TPIDRURO as well as software TLS on each switch. An explicit private-anonymous MADV_DONTNEED subset supports original thread-stack cleanup; `a` reaches its event loop after worker termination. The corrected `i` path reaches an unsupplied four-byte entropy read at 41,782,794 instructions during `libObj.so` activation. Resolve identified runtime state and failed original library loads before asserting subsystem startup. No framebuffer transaction is demonstrated.

Startup follow-up: [E0027](evidence/0027-original-clone-return-and-phase-survey.md) replaces direct pthread-function entry with the original clone syscall continuation. `i` reaches its guarded entropy read at 41,782,801 instructions; independent `l` startup stops on unsupplied `st_rdev` metadata while loading `liro.ko`. Continue with identified runtime state and kernel-module contracts; no framebuffer transaction is established.

Metadata follow-up: [E0028](evidence/0028-readonly-inode-metadata-and-module-request.md) advances independent `l` startup to `init_module` for verified `liro.ko` under explicit read-only image metadata policies. The next dependency is kernel-module execution with Sony IPC, backup, thread and DMA services. The loader request is not serviced, and `i` still needs identified entropy state. Earlier disabled-policy boundaries are preserved.

Service-fidelity correction: [E0029](evidence/0029-backup-service-guard-and-liro-entry.md) exposes an earlier backup-service reply boundary before the historical module request. Resolve original backup handler semantics and persistent inputs before accepting startup settings. The UI runner defaults to stopping on that recipient; the deeper historical acknowledgement policy remains explicitly selectable. No camera UI is demonstrated.

Backup-state follow-up: [E0030](evidence/0030-rea-backup-dispatch-and-preset-state.md) establishes operation 8 as a write and executes original read-only lookups against identified package presets using REA-assisted analysis. Continue with the actual backup module arguments, runtime `/setting` inputs and preexisting RAM producer; package defaults do not replace these dependencies. The strict process boundary remains unchanged.

Boot-parameter and RAM-mapping follow-up: [E0031](evidence/0031-backup-boot-parameters-and-ram-mapping.md) extracts `Backup_load=0` from `sbin/init` (`drivers2`), maps kernel `arch_phys_to_cache` (`pa + 0x60000000`), and traces the complete write execution pipeline (`Backup_write_core`) in `backup.ko`. Preset PA `0x02e80000` maps to VA `0x62e80000`, and LIRO PA `0x035c6000` maps to VA `0x635c6000`. When `Backup_load=0`, `backupfile_init` verifies cookie `0xaaaaaaaa` and calls `Data_init` on existing RAM without disk reload. The strict process boundary remains unchanged.
 
Preset-backed backup service follow-up: [E0032](evidence/0032-preset-backed-backup-service-and-liro-module-parameters.md) implements `BK4PresetState` and `PresetBackedBackupService`, providing authentic BK4 preset decoding and memory mutations under `--backup-service preset-backed`. For `im.elf l`, `Backup_read(0xfa, 0x00fa007c)` retrieves `0x035c6000`, causing original code to format authentic kernel module argument `adr=0x35c6000` and reach `init_module` for `liro.ko`. For `im.elf i`, `Backup_write` calls for `0x003e000b` and `0x00940003` are serviced authentically, progressing past Task 94 Phase 0 and spawning worker thread `THREAD_INFRA0`, which loads 30+ infrastructure libraries and executes past 8,000,000 instructions. Strict default `--backup-service stop` remains unchanged; all 280 tests pass.

Stream/DDS follow-up: [E0034](evidence/0034-stream-device-and-graphics-allocator-boundary.md) implements the optional stream ABI and preserves unknown physical memory. Opening stream exposes the missing GRM-MA/DMM allocation contract before any stream mmap/fb0 request. Resolve recipient `0x014c0424`, DMM queue `0x0061003c`, unit `0x280` and their real allocation state next; do not bypass the original assertion or reuse unverified framebuffer defaults.

## Phase 2 — Choose a backend through a bounded experiment

Dependency: sufficient Phase 1 evidence; no CPU/backend assumption is inherited solely from the old harness.

Tasks:

- Compare full-system execution with a custom machine model against a deliberately scoped user-space harness.
- Check support for the observed ISA, privilege levels, memory translation, exceptions, interrupts, and required processor behavior.
- Attempt the smallest original entry sequence with faithful memory placement and an observable early output, such as a verified diagnostic channel.
- If using the existing ELF loader for research, implement and test required relocation addends, symbol scopes, dependency ordering, initializers, ABI conventions, TLS, and permissions as evidenced by the binaries.
- Log unresolved dependencies and device accesses; do not make the experiment pass by returning generic success.
- Document the selected backend, effort drivers, limitations, and fallback triggers in an architecture decision.

Deliverables: reproducible headless launch, backend decision, first trace, minimal required-device backlog.

Exit gate: original instructions reach a specified checkpoint reproducibly; all approximations are listed. A custom board is budgeted if required. Failure produces a specific missing capability rather than a fabricated UI.

## Phase 3 — Execute original startup and foundational devices

Dependency: Phase 2 backend and initial platform contract.

Implement only devices demanded by observed execution, in dependency order:

1. Verified RAM/ROM mappings, reset state, exception handling and architectural control state.
2. Required timers, interrupt controller, clocks/reset controls, watchdog behavior, and diagnostic output.
3. Boot storage/partition access and the original filesystem requirements.
4. Required interprocessor/service communication, scheduling and synchronization behavior.
5. Nonvolatile data access with isolated copy-on-write persistence and reproducible reset semantics.

For each device, record registers, widths, reset values, side effects, interrupt conditions, DMA addressing, and evidence. Implement unsupported operations as explicit failures. Trace event ordering and introduce deterministic virtual time where practical.

Deliverables: boot/service checkpoints, tested device contracts, trace replay fixtures, initialized software dependency chain.

Exit gate: the original stack required by the target screen starts without application-result mocks. If only a user-space slice runs, label it accordingly; the full-system startup gate remains open.

## Phase 4 — First original UI vertical slice

Status 2026-11-10 (E0298): a read-only display contract covers OSD A/B
(camera-verified, 640x480 RGBA4444); a safe ptrace capture of im.elf's existing
mapping produced a complete PlayMemories USB MSC screen. The Sugilite buffer is
internal, not a display; the original GPU is DMP SMAPH-S30 and its private ISA
blocks a bounded rasterizer. The emulator now passes semtimedop(312) and the
observed /setting/gps mkdir and reaches 312M instructions, but it still does
not load viewUnified2/view resources or map OSD A/B; it waits for a verified
USB connect/MSC event. No live guest-rendered UI frame is claimed. The E0297
/dev/stream OSD method must not be repeated.

Dependency: original prerequisites from Phase 3; a research user-space slice may be explored earlier without closing the full-system gate.

Tasks:

- Select one static menu screen with minimal dependence on sensor/lens behavior.
- Run original resource loading, state management, layout, and rendering.
- Implement the actual display interface: buffer formats, strides, palette/alpha, plane composition, buffer swaps, and scanout behavior as required by evidence.
- Present the resulting display output without Python drawing camera widgets.
- Deliver MENU and one navigation input through the identified physical-input boundary, including press/release semantics.
- Capture code coverage/trace evidence for input dispatch, resource reads, rendering, and display submission.
- Test a deliberately changed resource in an isolated firmware overlay. Ensure changes to guest rendering code are observable as well.

Deliverables: original menu capture, matching input trace, original-vs-modified run pair, list of unsupported UI dependencies.

Exit gate: changing a Sony resource or covered rendering instruction changes the displayed result through Sony's executing code, with no host UI logic edit. Disabling the relevant guest renderer prevents that UI from appearing. Compare the baseline to a physical camera under the validation protocol.

## Phase 5 — Differential camera validation and patch workflow

Dependency: first original UI slice. Begin baseline camera capture design in Phase 1.

Tasks:

- Record matched firmware version, region/language, mode, accessory state, settings, storage contents, and input sequences.
- Establish repeatability on the camera before comparing against the emulator.
- Compare decoded display output if available; otherwise calibrate photographic captures and state their limits. Do not claim pixel identity from photographs.
- Separate semantic, visual, storage, and timing assertions. Archive all failures with traces and first-divergence analysis.
- Maintain immutable base inputs and patch overlays with expected preimage bytes, output hashes, and rollback metadata.
- Add controlled cases for text/icon/color changes, one covered code-branch change, and one invalid patch that must fail visibly.
- Treat repacking, checksums, signatures, updater acceptance, and installation as a separate research track. Local execution does not prove installability. Begin that track with offline inspection and round-trip checks; any physical write experiment requires a deliberate test procedure and authorization.

Deliverables: scenario suite, paired captures, compatibility matrix, patch manifests, automated comparison reports where the observation channel supports them.

Exit gate: supported claims have repeatable evidence on baseline and modified firmware; unsupported claims remain visible. Camera validation is not replaced by emulator self-consistency tests.

## Phase 6 — Expand behavior by subsystem

Dependency: Phase 5 loop is working.

Recommended order:

1. More menu pages, language variants, unavailable/disabled options, Fn menu, and persistence across restart.
2. Playback and deterministic card contents, metadata, thumbnails, file operations, and error cases.
3. Live-view buffer delivery and overlays using explicitly recorded/replayed input streams.
4. Exposure/focus controls and lens communication, then capture orchestration.
5. Sensor readout, proprietary processing, JPEG/RAW/video output, thermal/power interactions, and timing-sensitive behavior only as evidence permits.

Each subsystem gets its own model specification, physical observations, baseline/patch scenarios, and supported/unsupported status. Recorded image replay validates a boundary; it does not validate sensor or image-processing fidelity. Consider hardware-in-the-loop where software models cannot reproduce relevant behavior.

Exit gate: each added claim passes its own differential suite. Timing claims specify tolerance and conditions; image-output claims specify inputs and output comparison criteria.

## Phase 7 — Reproducible releases

Dependency: at least one validated capability.

- Package the execution frontend, manifests, dependency versions, and redistributable fixtures.
- Keep proprietary firmware and private backups out of source distributions; document local import steps and required hashes.
- Provide headless runs, structured reports, snapshots, and regression bisect support.
- Run loader/device/trace tests without a physical camera. Separate opt-in hardware validation from ordinary checks.
- Publish a compatibility matrix by firmware, scenario, device-model version, and fidelity dimension.

Exit gate: another environment can reproduce the documented supported scenario from permitted local inputs and inspect the evidence behind the claim.

## Initial work queue

| Priority | Task | Dependency | Completion evidence |
| --- | --- | --- | --- |
| P0 | Inventory and hash local firmware and upstream revisions | None | Manifest with provenance and unresolved origins |
| P0 | Add strict stop/report behavior to existing harness | Preserved baseline | Negative cases for missing symbol, MMIO, fault, timeout |
| P0 | Audit existing ELF loader against actual relocations | Binary inventory | Required relocation inventory and meaningful loader fixtures |
| P0 | Map original startup and first menu dependency chain | Static analysis | Evidence-linked graph and missing-artifact list |
| P0 | Capture repeatable stock-camera menu baseline | Available camera | Scenario record and repeated observations |
| P1 | Backend proof and decision record | Platform evidence | Reproducible original checkpoint |
| P1 | Implement minimum startup devices | Backend proof | Original startup trace and device contract checks |
| P1 | Execute original menu rendering/input | Required services/devices | Guest-produced display and mutation pair |
| P2 | Extend to persistent settings and playback | Validated UI slice | Differential scenario results |

## Scheduling and stop conditions

Use gates rather than calendar promises until the platform inventory and backend experiment are complete. Full machine research can dominate the effort, especially absent documentation for proprietary hardware.

At each gate, record: completed evidence, remaining unknowns, revised scope, owner, and next experiment. Stop claiming progress toward fidelity when a milestone is achieved only by adding a behavioral substitute. If an essential firmware domain or hardware contract cannot be obtained, document the blocker and narrow the supported scenario explicitly.
