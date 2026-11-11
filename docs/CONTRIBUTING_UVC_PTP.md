# Contributing to UVC / PTP mode

This is the focused entry point for work on **UVC video** and **PTP (PC Remote) mode**
for the Sony ILCE-6400. Read the top-level [CONTRIBUTING.MD](../CONTRIBUTING.MD)
and [AGENTS.MD](../AGENTS.MD) first; they define the scientific and physical
safety rules. This page explains where the UVC/PTP work actually stands, what is
missing, and how to claim a piece.

## Mission and honest status

The target is a retail ILCE-6400 producing real **UVC video** while PTP control
continues to work. The reference implementation is the Sony **ZV-E10 v2.03**
firmware, whose UVC stack (`usbg_video.ko`, `usbg_audio.ko`,
`libInfraStreamingUsb.so`, its `libInfraUsbCmn.so` and `devno.ko`) does not exist
on the a6400. The a6400 UVC path is therefore a porting and contract problem, not
a setting toggle.

What is established (all with evidence records under
[`docs/evidence/`](evidence/)):

- The ZV-E10 UVC + PTP configuration descriptor is byte-verified (173 bytes) and
  cross-checked against the ZV-E10 source images
  ([E0315](evidence/0315-usb-ptp-descriptor-firmware-evidence.md),
  [E0316](evidence/0316-zve10-uvc-chain-inventory-and-a6400-enablement.md),
  [E0317](evidence/0317-zve10-uvc-descriptor-byte-crosscheck.md)).
- The `usbg_video` driver contract is decoded: ioctl registration, core
  callbacks, endpoint lists, transfer family and the physical-buffer RPC
  ([E0319](evidence/0319-zve10-usbg-video-ioctl-buffer-contract.md)).
- The a6400 enablement diff is hash-pinned and evaluated as **not enabled**:
  `/dev/usb/video` 248:33 and `/dev/usb/audio` 248:32 do not exist; the modules
  are absent ([E0320](evidence/0320-zve10-devno-usb-video-node-and-guest-usb-video-contract.md),
  [E0321](evidence/0321-zve10-uvc-enablement-manifest.md),
  [E0322](evidence/0322-zve10-uvc-overlay-plan.md)).
- The MWF message path from `RcvMsg` to the USB FSM is decoded, including the
  inbound SET_CONFIG mapping `CategoryId 0x6103 / MessageId 0x0A4001 ->
  FSM event 0x13`
  ([E0323](evidence/0323-usbcontrol-msgid-eventid-map.md),
  [E0324](evidence/0324-mwf-objmsg-layout.md),
  [E0325](evidence/0325-mwf-param-parammap-layout.md),
  [E0326](evidence/0326-mwf-typed-param-and-serializer-header.md),
  [E0327](evidence/0327-mwf-objmsg-wire-format.md)).
- The USB lane delivery mechanics are now precisely bounded: `0x00CA8192` is a
  **process-local** OSAL queue, and the kernel→user notifications for
  `0x00CA0288` / `0x00CA01A4` use **sync-registered callbacks** (`flags=1`), which
  the async UIPC `WAIT_CB` model never delivers
  ([E0328](evidence/0328-emulated-setconfig-objmsg-injection-and-osal-gap.md),
  [E0329](evidence/0329-libosal-receive-queue-protocol.md),
  [E0330](evidence/0330-libosal-queue-object-layout.md),
  [E0331](evidence/0331-usb-lane-local-queue-vs-sync-callback.md)).

**Current bottom line:** PTP (PC Remote) physically works and is demonstrable.
UVC is 0% physical because the ZV-E10 modules are not loaded and physical module
load is outside the owner's current read-only scope. The emulator path has all
message formats and dispatch maps but still needs the sync-callback delivery
model before a SET_CONFIG notification can reach the USB FSM.

## Workstreams you can take

Each item is scoped so it can be reviewed like a normal software change. Pick
one, open or comment on the matching issue, and say which part you are taking.
If you cannot run the Windows `venv`, you can still contribute decoders, tests
and documentation in a plain Python environment for most items.

### 1. Model kernel to user sync callback delivery (highest impact)

- Boundary: `uipc_sync_callback_delivery_unmodelled`.
- Context: [E0331](evidence/0331-usb-lane-local-queue-vs-sync-callback.md),
  [E0330](evidence/0330-libosal-queue-object-layout.md),
  [E0329](evidence/0329-libosal-receive-queue-protocol.md).
- Do: decode `handle_snd_sync_msg` / `handle_snd_sync_direct` in
  [`src/a6400/execution/guest_uipc.py`](../src/a6400/execution/guest_uipc.py)
  and the `libosal_uipc` sync wrappers, then add an explicit opt-in policy that
  delivers a kernel-originated message to a `flags=1` registered callback and
  lets the original guest callback run.
- Acceptance: the original UsbControl code posts and consumes a message; the
  FSM event is observed without host-side message fabrication, or a precise new
  boundary is recorded. Keep default baselines unchanged.
- Files: `guest_uipc.py`, `interpreter_probe.py`, `tests/test_guest_uipc*.py`,
  `tests/test_interpreter_probe.py`.
- Difficulty: medium.

### 2. Host-side UVC enumeration / SET_CONFIG contract

- Boundary: gap #1 — host enumeration is not modelled end to end.
- Context: E0316/E0317 descriptor evidence and the
  [`usb_video_contract.py`](../src/a6400/execution/usb_video_contract.py)
  decoders.
- Do: build an opt-in host enumeration harness (GET_DESCRIPTOR device/config,
  SET_CONFIGURATION, interface/endpoint selection for UVC+PTP) that consumes the
  byte-verified 173-byte descriptor and drives the already-decoded SET_CONFIG
  message into the FSM once workstream 1 lands.
- Acceptance: descriptor bytes prove the UVC function is addressed; a SET_CONFIG
  event either reaches FSM event `0x13` (documented observation) or stops at a
  named boundary. No host-invented descriptors.
- Difficulty: medium-hard.

### 3. `usbg_video` buffer and transfer contract

- Boundary: `ctx+0x2D` writer, `0xD0` request object, `0x24` DMA-info object,
  buffer-table/blob semantics and the JPEG/DMM frame source are still open.
- Context: [E0319](evidence/0319-zve10-usbg-video-ioctl-buffer-contract.md).
- Do: extend [`usb_video_contract.py`](../src/a6400/execution/usb_video_contract.py)
  decoders and [`guest_usb_video.py`](../src/a6400/execution/guest_usb_video.py)
  fail-closed contracts with evidence-derived structures; unit-test parsing,
  bounds and provenance.
- Acceptance: decoders are unit-tested against extracted source evidence;
  unknown fields still stop explicitly.
- Difficulty: medium.

### 4. ZV-E10 overlay hygiene and device-node namespace

- Context: [E0321](evidence/0321-zve10-uvc-enablement-manifest.md),
  [E0322](evidence/0322-zve10-uvc-overlay-plan.md),
  `src/a6400/execution/zve10_uvc_*.py`.
- Do: improve the hash-pinned overlay plan and devno namespace modelling for
  248:32/33 without ever making an install executable by default; add
  verification checks for hashes/vermagic and node registration.
- Acceptance: plan remains `executable: false` unless the owner explicitly
  authorizes a physical load; tests cover namespace parsing and refusal paths.
- Difficulty: easy-medium (good first issue).

### 5. PTP controls and liveview robustness

- Context: [`sony_ptp_controls.py`](../tools/research/sony_ptp_controls.py),
  [`ptp_liveview_client.py`](../tools/research/ptp_liveview_client.py),
  `docs/CINEMAHUD_STOCK_PTP.md`.
- Do: expand offline PTP control mappings/tests, harden reconnect and teardown
  handling, document tested camera configurations.
- Acceptance: offline decoding tests pass; any physical test is a separately
  authorized read-only observation with receipts.
- Difficulty: easy-medium (good first issue).

### 6. Physical composite lifecycle (owner authorization required)

- Context: E0210–E0218, E0289, E0296 in [`docs/UVC_PTP_STATUS.md`](UVC_PTP_STATUS.md).
- Do: design a reviewed PTP+UVC activation/teardown plan with recoverable stage
  observation. Do not run it without the owner's explicit scope.
- Acceptance: a plan reviewable by the owner; no unapproved device writes.

## Rules that make a contribution mergeable

1. **No proprietary inputs.** Never commit firmware, extracted `.so`/`.ko`,
   dumps, backups or generated payloads; reference hashes instead
   ([.gitignore](../.gitignore) already excludes them).
2. **Evidence first.** A behavioral claim needs an evidence record with input
   hash, method, observation and limitations. Use the format in
   [`docs/evidence/README.md`](evidence/README.md).
3. **Fail closed.** Unknown services return a named boundary, not a success
   value. New behavior is an explicit opt-in policy; defaults and earlier
   baselines must keep passing.
4. **No fabricated messages or host-side camera decisions.** The original
   firmware code must own logic in fidelity experiments.
5. **Read-only camera.** Physical observations require the owner's standing
   authorization; no mode changes, module loads, SD writes or bulk `/dev/mem`
   sweeps. Module loading is currently excluded.
6. **Tests.** Run `.\venv\Scripts\python.exe -m unittest discover -s tests -q`
   and report the real result. On Linux/macOS, `python -m unittest discover -s
   tests -q` works for most unit tests.
7. **Small PRs.** One contract or one boundary per pull request, with the
   evidence link in the description.

## Where to start

- Browse issues labeled
  [`uvc`](https://github.com/ivica00/sony-a6400-research/issues?q=label%3Auvc)
  and
  [`good first issue`](https://github.com/ivica00/sony-a6400-research/issues?q=label%3A%22good+first+issue%22).
- Read [`docs/UVC_PTP_STATUS.md`](UVC_PTP_STATUS.md) for the consolidated
  closeness matrix and remaining boundaries.
- If you are unsure where a question belongs, open a discussion or a
  "question" issue. Proposing an experiment that fails cleanly is valuable
  research here; a wrong guess is fine, an unlabelled assumption is not.
