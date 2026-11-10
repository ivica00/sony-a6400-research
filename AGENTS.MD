# Project instructions

## Objective and working scope

Build an evidence-backed Sony ILCE-6400 environment in which original or modified firmware produces application behavior through verified CPU, OS and hardware contracts. Host-written navigation, rendering or camera decisions are not firmware compatibility. Follow the user's current scope; continue authorized work without routine confirmation. Do not spawn subagents unless explicitly requested or required by another applicable instruction.

## Read first: current checkpoint

CURRENT E0300: read docs/evidence/0300-uipc-proxy-start-and-vbus-callback.md, then E0298/E0297 below. Offline only, no GUI frame/OSD mapping. Root cause for absent UIPC proxy threads: shared pool option header was zero; original k_uipc_init sets +0x10=4. Opt-in --uipc-pool-options kernel-e0300 initializes only verified header stores, original priority-query tables (16 ARM controls), and bounded WAIT_CB async delivery; fresh boot required (reject legacy checkpoint retrofit). Phase i fresh replay/checkpoints e0300-i/i2/i3: no-input stops at 91,139,021 on sync-registered queue 0x009c015b. Separate VBUS injection from boot-e0300-i2.ckpt wakes all four proxies and original libInfraUsbCmn callback runs/returns and frees message; at 83,341,353 it stops at uipc_callback_completion_not_implemented (boot-e0300-vbus.ckpt). Next decode finish_callback queue state/refcount/ownership and sync callback protocol; do not double-free or drop guard. CONNECT fourth word still historical zero, original dynamic control queue incomplete. 782 tests OK (20.857 s); status image refreshed. Early VBUS timing is an explicit experiment, not verified physical ordering.

CURRENT E0298: read docs/evidence/0298-safe-osd-capture-and-sugilite-correction.md then E0297. Safe read-only ptrace of im.elf PID149 (no /dev/stream open) captured OSD A/B 640x480 RGBA4444 = a complete PlayMemories MSC screen (A/B identical); OSD A/B are the verified display. gl_common+0x1000 is an internal patterned buffer, not a screen; E0297's 960x540 frame is superseded. GPU identity is DMP SMAPH-S30 (libObj 60ffd2b0...), not PICA200; bounded command/state model possible, rasterizer blocked (private ISA). Opt-in GrmMaService(pool_policy='captured-e0044') and boot gates semtimedop(312)/observed-gps mkdir are in place; a resume reached 312M instructions, no boundary, but no viewUnified2/view resources and no OSD mappings. USB split workstream (E0299 analysis): /dev/usb/event ABI + subtype mapping + verified buspwr VBUS UIPC producer (queue 0x012002da, 16B body) decoded; GuestUsbEvent.inject_record/validate and opt-in verified buspwr/otgcore replies implemented; probe inject_usb_event/inject_uipc_message wired via CLI. Bounded runs: subtype-2 event record accepted/woke TID1013 but no UI; verified VBUS UIPC message enqueued but woken=[] (no consumer read); app 355.9M no boundary, still no OSD. Missing contract: UIPC async callback delivery/libInfraUsbCmn queue 0x12002da consumer (or UI/USB service tier) and exact SETCONFIG_MASSSTORAGE id/dynamic UsbControl receive id; do not host-call the callback. 778 tests OK (policy DLL cached). E0296 snapshot3 paused.

E0297 (superseded display claim): live display contract/GUI and checkpoint extraction; the 960x540 Sugilite frame is an internal buffer. One read-only /dev/stream OSD capture rebooted the camera; do not repeat; E0298 records the safe ptrace method.

Read [E0234](docs/evidence/0234-ordinary-pcremote-ifsys-query-answered.md): ordinary MSC->PCRemote->MSC query answered (`IFSYS getdriveinfo A`,303B reply result0x0/filesystemType0x0003/MWF>), receipt25350B, cleanup verified. [E0233](docs/evidence/0233-preserved-output-prefix-acknowledgement.md) prefix ack physically confirmed on appended/wrapped data; not multi-consumer CAS/ABA. E0232 strict-ack rejection baseline retained.

- E0226 preserved/fsync'ed/read back 30,115 output bytes before one four-byte output-read-cursor acknowledgement. Wrong cursor rejected without header change; post-capture empty. Input and producer cursors untouched. No command submitted. Eight compiled ARM admission cases pass; last full suite is E0225's 617 passing tests. Check/store is not exclusive ownership or multi-consumer CAS; do not roll back uncertain writes.
- E0227 fixed `? GETHOME` probe physically returned38bytes of native help plus `MWF>`; input10/10/outputempty,13compiled ARM admission cases pass. No filesystem command or SD write. Existing Python full617suite passes16.883s; venv full/focused runs have28compiler-invocation errors retained in receipts, cause unresolved. No environment/test changes.
- Next: P0 PC Remote reboot isolation before any P4 physical teardown rerun (the admission build is not deployed). Journal physical retry only after the reboot cause is understood. Camera may be used only for quick read-only USB debugger checks. Journal path/readback remain open. Wrapper1/publication is not operation success. Do not reinitialize MonDrv or guess addresses; checked cursor stores are not exclusive ownership/CAS. Host reader remains USB-dependent.
- E0210 proved Windows parent/PTP/UVC child enumeration with video disabled, then camera froze. Teardown receipt was not recovered; restart restored MSC. Exact hang cause unknown. No further physical activation until configured teardown review and recoverable stage observation; E0211–E0218 are partial offline contracts, not a freeze fix.
- Shared sensor/UVC integration remains unfinished. Keep source storage disjoint from owned DMA destinations, validate bounds/lifetimes and wait before reuse; no legacy feeder or static fallback may count as sensor frames. See E0208 and the [UVC/PTP handoff](docs/UVC_PTP_STATUS.md).

## Device and storage boundaries

- Physical SD `E:\` is read-only for emulator inputs. User authorization (2026-11-05) permits SD writes needed for homebrew scripts, configuration and payloads, not unrelated deletion or formatting.
- Current diagnostic scope: camera writes under `/tmp_bt` except the explicitly authorized small SD diagnostic journal (E0219). Do not ask again for that journal authorization. It remains unwritten and requires verified service ownership, non-overwrite creation, bounded write, flush/readback and restart-survival evidence.
- Revalidate volume/device association before any journal write: E0222 identified `A:/dev/mmca` as SD; `B:/dev/nflasha23` is internal flash and excluded. Do not guess from drive letters, concurrently write-mount the card, initialize a private filesystem stack or issue raw storage writes.
- Ordinary tests must not access USB, invoke service-mode backup, install firmware, replace drivers or change the camera. Stay within authorized physical scope. Preserve complete receipts before removing only owned temporary files. A host monitoring window is not completion, successful STOP, restored hooks, drained DMA or unloaded-module proof.

## Fidelity and evidence

- Separate observations, inference, assumptions, fixtures and physical verification. Bound execution; stop with PC/arguments/reason at unsupported imports, syscalls, devices, memory or metadata. Faults and limits are not success.
- No silent zero/success replies, automatic mappings, fabricated queues/UI or weakened guards to advance execution. Add contracts via explicit opt-in policies; retain default no-response and earlier regression baselines.
- Guest access uses a declared namespace and allowlisted hash-checked inputs, never arbitrary host paths/syscalls. Check memory bounds/permissions and preserve identity/provenance guards. Unsupplied runtime mounts are unknown, not verified absent.
- Original code owns application logic/rendering in fidelity experiments. A bounded instruction probe is not a booted kernel, timing model, complete machine or proof of deployment safety.
- Preserve firmware, backups and captures; modify separate outputs or overlays. Never silently refresh hashes. Keep upstream checkouts and `venv/` in place; do not change their Git state incidentally.
- Material evidence records need input/tool identities, exact command/policy, original instruction support, serviced operations, observation/stop, assumptions, failures, repeatability and next boundary. Preserve failed receipts and mark superseded conclusions. Update README/roadmap when status changes; never publish proprietary inputs or secrets.

## Implementation and checks

Use small components and shared path/memory rules. Prefer `rg`, constructed fixtures and focused ABI/state/error/provenance/ARM checks; avoid tests mirroring implementation. Generated fixtures belong under `artifacts/tests/`. Avoid inaccessible abandoned temporary directories without incidental permission changes or recursive cleanup. Do not guess dependency versions or claim reproducibility from an installed-package snapshot.

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -q
.\venv\Scripts\python.exe -m tools.research.probe_interpreter
```

Run focused checks during work, the full suite after substantive code changes, and real-firmware replays when their path changes. Preserve reports under new output directories; do not regenerate costly inventories just for timestamps. Boundary exits (including the `files` probe's expected exit 2) are not automatically regressions or application success. Use module/root compatibility launch paths.

## Research tooling and references

For substantial ARM/Thumb analysis prefer existing REA/Ghidra via WSL and `tools.research.rea_wsl_batch`; reuse only identity-matched evidence. Read [REA workflow](docs/REA_WORKFLOW.md) for established paths, query limits, address translation and failure handling, and [dependency workflow](docs/DEPENDENCY_WORKFLOW.md) before following call chains. Pseudocode is untrusted: verify instructions, relocations, runtime state and side effects before implementing a response. No incidental setup, upgrades or global configuration changes.

See [CONTRIBUTING.MD](CONTRIBUTING.MD) and [live-camera workflow](docs/LIVE_CAMERA_EMULATOR_WORKFLOW.md). Prior verbose notes are preserved in [the historical archive](docs/archives/agent-notes-2026-11-09.md), which is reference material, not active instructions. Keep updates concise: result, verification and remaining boundary. Refresh `status_a6400.png` for substantive research milestones without inflating compatibility claims; documentation formatting alone is not a research milestone.
