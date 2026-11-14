# E0164 — Shared PTP/UVC Module: Build and Lifetime Guards

Date: 2026-11-08. Camera was not contacted in these checks. No uploads, module loads, or camera writes.

## Result

Built standalone candidate `artifacts/native/uvc-ptp-module-e0164/usbg_video_a6400_shared_candidate.ko`, 58,540 bytes, SHA-256 `064fd44486824ea2e1d93729636b7d0408d73e332138f821c26fb6daf5ea952e`. Vermagic is `3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7 `. Manifest intentionally sets `deployable:false` and `physical_test_ready:false`.

Candidate links earlier verified descriptors, copy management, session, and native backend with the original reference video module. PTP stays on interface 0, UVC uses interfaces 1/2 and dedicated Bulk IN `0x82`. Identity is taken via original Sony serializers and strictly checked before changing configuration. Actual RAM layout of identity is not yet physically verified.

This is an enumeration candidate. Video buffer registration, frame submission, and other video commands are rejected. START verifies endpoint selection, but does not call original video START. Module does not prove sensor image or simultaneous Windows UVC/PTP communication.

## Guards

- `file_operations.owner` is bound to `__this_module`; custom export enables additional module retention during an active or incompletely cleaned session.
- STOP and release wrappers finish the session first. If cleanup is blocked, they skip original functions that would free the context. Original release otherwise ignores DMA free errors and proceeds to free the context.
- Status remains available in held state. Overlapping entries into this module are rejected by an atomic guard.
- DMA check uses subtraction after minimum capacity check; `UINT_MAX` can no longer pass via overflow when adding header length.
- Only two explicitly documented original instructions were changed in reference text (three differing bytes). Original init/exit remain identical.

This entry guard does not serialize Sony's independent USB mode-switching task. Its locking contract must be established before a physical test. Failure on restore retains resources rather than guessing ownership.

## Checks and Evidence Boundaries

`artifacts/analysis/uvc-ptp-module-e0164/manifest.json` records 29 passing checks of actually compiled wrappers: file operations wiring, export, video command rejection, status, clean close forwarding, held state, and DMA length bounds. Original core ioctl/release and copy services in this experiment are explicit call recorders. Module loader and real reference counts were not executed.

Native backend regression passes 147 checks in `artifacts/native/uvc-ptp-native-regression-e0164`. Original serializers execute in a controlled ARM environment; hardware services have explicit stubs. This is not a physical USB test.

All 47 imports were found in preserved kernel and module evidence. For eight imports from `dma330.ko` and `osal_uipc.ko`, real export names in original ELF `__ksymtab_strings` sections were additionally verified; result and hashes are recorded in `artifacts/analysis/uvc-ptp-module-e0164/module-export-evidence.json`. Presence in preserved files does not prove current state of loaded modules.

The earlier standalone build mode with owned coherent DMA and probe-only START also builds successfully. Project tests: **605 passed, 15.406 s**, log `artifacts/uvc-ptp-module-e0164-project-tests.log`.

## Next Boundary

First determine original USB mode-change serialization and callback lifetimes, then prepare a bounded physical enumeration experiment with verifiable return to PC Remote. Transfer of real sensor JPEG frames and adapting host detection for the shared device remain separate unfinished steps. E0150 static pattern at 30 FPS remains proof of transport, not sensor source.
