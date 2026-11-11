# Current state (historical checkpoint)

**This page is a historical snapshot.** Current status lives in
[the README research status](../README.md) and [UVC/PTP status](UVC_PTP_STATUS.md)
(through E0352, 2026-11-11). The audit below is kept for provenance only.

## Historical checkpoint: 2026-11-06

This document's older audit remains historical. Current native-menu findings are
in [E0109](evidence/0109-original-activation-thread-context-and-resource-boundary.md):
original lookup, geometry and geometric hit checks run on real captures, but
physical menu touch and completed activation are not demonstrated. The installed
normal-USB debugger supplies evidence, not invented firmware decisions. See the
[workflow](LIVE_CAMERA_EMULATOR_WORKFLOW.md) and Current native-menu findings are
in [E0109](evidence/0109-original-activation-thread-context-and-resource-boundary.md):
original lookup, geometry and geometric hit checks run on real captures, but
physical menu touch and completed activation are not demonstrated. The installed
normal-USB debugger supplies evidence, not invented firmware decisions. See the
[workflow](LIVE_CAMERA_EMULATOR_WORKFLOW.md) and
[publication audit](evidence/0110-research-checkpoint-and-github-publication.md).


# Current state audit — 2026-10-18

## What exists

1. `tools/research/unpack_firmware.py` locates a UFU container and delegates extraction to bundled fwtool. Extracted partitions are available locally. Extraction is useful evidence, but does not validate a bootable or installable modified package.
2. `tools/research/firmware_analyzer.py` inspects container chunks. `tools/research/analyze_hardware_drivers.py` inspects driver symbols and strings. These are discovery tools, not implemented device models.
3. `legacy/cxd90045_hle_emulator.py` creates a Unicorn ARM context, maps memory, loads selected ELF libraries, resolves a subset of relocations, and calls selected screen factories.
4. Sony widget/model services are intercepted with mock objects. Unknown symbols return zero. `ioctl` and mutex handlers return success; MMIO has no implemented device state machine; unmapped accesses allocate memory.
5. Python controls navigation and camera settings. Pillow creates the display and writes it to the configured framebuffer address. A photo supplies the apparent sensor image.
6. The GUI accent control edits Python camera state, not an executable firmware patch. `legacy/test_authentic_screens.py` generates images without camera comparison assertions.
7. Backup tooling exists, but the emulator's backup dictionary is not a validated persistent camera-state implementation. The local backups directory was empty during the audit.

## Reproduced evidence

Instantiating `CXD90045_HLE_Emulator`, without loading either Sony library, then sending `KEY_TACT_MENU` produced:

```text
modules=[] instances={} screen=MENU image=(960, 540)
```

This proves that the menu path can operate without Sony screen execution. It does not establish whether any particular Sony factory succeeds when loaded.

## Claims that remain unverified

- Exact SoC identity, CPU model/configuration, core count, memory map, and device registers. Names and source comments are hypotheses until backed by evidence.
- Guest OS/boot architecture and the relationship between all processors, services, firmware images, and update-only content.
- ABI correctness, full dependency loading, symbol binding, initialization, TLS, and concurrency behavior.
- Original UI rendering, physical input dispatch, storage, interrupt delivery, image processing, autofocus, and timing.
- Acceptance and installation of a repacked modified update by a camera.

## Reuse decision

Keep the HLE code as a reverse-engineering harness and the simulator as a visual reference. Reuse parsers and observations only after validating them. Do not gradually promote visual prototype behavior into the authoritative execution backend.

The organization change moved implementation into `legacy/` and `tools/research/` and redirects generated images to `artifacts/legacy/`. The former root entry points were removed on 2026-11-11; the supported launch paths are the `legacy.*` / `tools.research.*` module paths in [REPOSITORY.md](REPOSITORY.md). Firmware and upstream trees remain untouched.
