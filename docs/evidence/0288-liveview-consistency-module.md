# E0288 — Liveview-consistency module (opt-in) built and audited

Date: 2026-11-09. Offline implementation + static audit; no camera load.

## Implementation (opt-in `A6400_LIVEVIEW_CONSISTENCY`)

- New shim code in `tools/native_camera/uvc_composite_shim.c`:
  - Runtime scan of the gadgetcore text (`0x602a0000–0x602c0000`) for ARM `BL` instructions
    targeting `usb_gcw_stop` (`0x602bd834`) or `usb_gcw_start` (`0x602bd7f8`); those call sites
    are patched to wrappers (same BL patch technique as `setup_req+0x128`), originals saved.
  - `my_liveview_gcw_stop(gc)`: calls the original stop, then **drops the UVC overlay**
    (`a6400_unhook_make_config_desc` + `a6400_demote_uvc_drivers`) so the app's liveview-start
    gadget re-create stays consistent.
  - `my_liveview_gcw_start(arg)`: calls the original start, then **re-arms EP0 and raises D+**
    (`a6400_arm_ep0` + `a6400_usb_pullup`) so the UDC enumerates after the app's re-create.
  - `a6400_unhook_gcw_calls()` restores the patched BLs during module restore.
- Builder flag: `build_uvc_composite_module.py --liveview-consistency` (requires
  `--shared-ptp-enumeration-candidate`; compiles `-DA6400_LIVEVIEW_CONSISTENCY=1`).

## Build/audit

- Built inside WSL (the Python→wsl.exe subprocess path is denied; the WSL Python path with the
  venv's `site-packages` for pyelftools was used; the builder's step-5 Unicorn import does not
  run in WSL).
- Final module: `artifacts/native/uvc-ptp-module-e0288-liveview/usbg_video_a6400_shared_candidate.ko`,
  73,072 B, SHA256 `7a3e2f59d708712df5fa998aa0e11d63a8a6b7719433028c1276c9afca3e3dac`.
- Manifest written with the exact input hashes; audit split per the established workaround
  (`--prepare-only` → direct WSL gcc/ld → `--linked-elf`).
- Audit: `artifacts/analysis/uvc-ptp-module-e0288-liveview/manifest.json`,
  **`offline_module_audit_passed`, 118 checks**.

## Next

- Physical test with the e0288 module (enumeration candidate + teardown-unconfigure-first +
  liveview-consistency), the 0.2 s capture, the probe and the LCD observation.
- Expected: the app's liveview-start re-create no longer removes the device; the host
  re-enumerates a consistent PC Remote/PTP device (PTP child returns); teardown receipt.
- Fallback: if the device still disappears, inspect whether the wrappers fired (kernel log) and
  which call site/stop path remains unhooked.
