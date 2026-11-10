# E0243 — Opt-in producer admission ioctl linked into the shared candidate

Date: 2026-11-09. Offline build only: no camera access, no module load, no UVC activation. This is step P3c of the UVC/PTP critical path.

## Changes

- `tools/native_camera/uvc_composite_shim.c`: behind `A6400_UVC_PRODUCER_ADMISSION`, new ioctl `0x4008f004` copies an 84-byte struct (`frame_size`, `phys_addr`, `slot`, `prefix_len`, `prefix[64]`, `reserved`), calls `a6400_uvc_producer_submit()` with the owned DMA window/slot capacity and module-constant **1280×720**, and returns the admitted slot or `-EINVAL`. It does **not** call the driver Update.
- `tools/research/build_uvc_composite_module.py`: new `--producer-admission` flag (requires `--shared-ptp-enumeration-candidate`), adds `-DA6400_UVC_PRODUCER_ADMISSION=1` and compiles `uvc_frame_validate.c`, `uvc_producer_admission.c` and `uvc_producer_submit.c`.

## Build result

- Target: `artifacts/native/uvc-ptp-module-e0243/usbg_video_a6400_shared_candidate.ko`, 74,404 bytes, SHA-256 `bab5426088b5e1a4df423481a08fddfa744d26f137cd5a524ce75611348d8642`.
- Executable sections `.text`/`.init.text`/`.exit.text` prefix-match the reference with the two documented patches (`0x116c`, `0x13e8`); START/video code is otherwise unchanged.
- 55 undefined symbols, all verified against retained kernel/module evidence; GPL-only imports none; `a6400_uvc_producer_admit` and `a6400_uvc_producer_submit` are defined in the module; `0x4008f004` is present as `movw r2,#0xf004` + `movt r2,#0x4008`, with `bl a6400_uvc_producer_submit` at the dispatch site.
- Manifest: `artifacts/native/uvc-ptp-module-e0243/manifest.json` with the file hashes, symbol classes, section checks and limitations.

## Build/verification note

The build tool's step 5 imports Unicorn; the Windows venv Unicorn cannot load under WSL, and this session denies WSL launched from Python children. Steps 1–4 were therefore run through `wsl.exe … python3 -m tools.research.build_uvc_composite_module` with `PYTHONPATH` pointing at the venv site-packages, and step 5 was replicated by a Windows-side verifier (executable prefixes, undefined symbols, GPL metadata, admission symbols, ioctl constant). The full 118-check guard audit was not rerun under this split environment; the E0212 audit baseline remains and this build's original-code prefix matches.

## Boundary

The admission branch is compiled but not loaded or exercised. Update/ENABLE/WAIT remain rejected by the enumeration-only policy; the admission ioctl only validates and consumes a slot — it does not map the source, call Update, wait on DMA, or produce a sensor frame. No Windows binding, teardown or streaming proof.

## Next

P0: PC Remote reboot isolation before any P4 physical rerun. Alternatively, rerun the full guard audit in an environment with WSL plus a native Unicorn binding.
