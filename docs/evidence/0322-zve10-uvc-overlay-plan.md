# E0322 — Declared ZV-E10 → a6400 UVC overlay plan (data-only, blocked)

Date: 2026-11-11. Offline only. Input: E0321 enablement manifest
(`artifacts/analysis/e0321-uvc-enablement-manifest.json`). Output:
`artifacts/analysis/e0322-uvc-overlay-plan.json` (builder
`tools/research/uvc_overlay_plan.py`). No camera access, no module load, no
target file writes, no mode change.

## 1. Result

The enablement work is now expressed as an explicit, hash-pinned overlay plan:

| Action | Component (ZV-E10 2.03) | Target path | a6400 status |
| --- | --- | --- | --- |
| add | `usbg_video.ko` (`d385a051…`, 20,668 B) | `/usr/kmod/usbg_video.ko` | missing |
| add | `usbg_audio.ko` (`8f735727…`, 20,456 B) | `/usr/kmod/usbg_audio.ko` | missing |
| add | `libInfraStreamingUsb.so` (`0a9448e3…`, 52,524 B) | `/usr/lib/libInfraStreamingUsb.so` | missing |
| replace | `libInfraUsbCmn.so` (`af830315…`, 94,612 B) | `/usr/lib/libInfraUsbCmn.so` | hash mismatch (a6400 build) |
| replace | `devno.ko` (`273db657…`, 4,368 B) | `/usr/kmod/devno.ko` | hash mismatch (lacks 248:32/33 nodes) |

**Readiness: `blocked`** — `executable: false` in the plan. Blocking reasons:
missing A6400-side components (`usbg_video.ko`, `usbg_audio.ko`,
`libInfraStreamingUsb.so`) and absent device nodes `/dev/usb/audio` (248:32) /
`/dev/usb/video` (248:33).

## 2. Prerequisites (declared)

- `usbg_cmn.ko` present in both models and exporting `usbg_cmn_reg`/`dereg` and
  the sync physical-buffer APIs (E0320/E0321).
- Module load order `usbg_cmn` → `usbg_video`/`usbg_audio` (implied by
  `usbg_cmn_reg`, not physically proven).
- PTP `usbg_stillimage` stays in the same gadgetcore configuration.

## 3. Open items (must stay explicit)

1. **Device-node namespace:** `/dev/usb/audio` 248:32 and `/dev/usb/video`
   248:33 must exist after replacing `devno.ko`; whether the a6400 rootfs
   creates them from the table or an explicit node overlay is required is not
   yet proven.
2. **Physical load** of ZV-E10 modules changes camera runtime — needs separate
   explicit authorization, recovery plan and teardown receipts.
3. **Register/transfer contract:** context `+0x2D` writer (count read by
   `usbg_cmn_copy_probe_info`), buffer table/blob semantics and the 0xD0/0x24
   object contents remain undecoded (E0319); `GuestUsbVideo` stays fail-closed.
4. **Host USB enumeration/`SET_CONFIG`** contract (E0318) is orthogonal.

## 4. Code/tests

`src/a6400/execution/zve10_uvc_overlay.py` (`OVERLAY_TARGETS`,
`OVERLAY_PREREQUISITES`, `OVERLAY_OPEN_ITEMS`, `build_overlay_plan`), builder
`tools/research/uvc_overlay_plan.py`, tests
`tests/test_zve10_uvc_overlay.py` (blocked/ready verdicts, hash-pinned
operations, never-executable invariant). Full suite: **932 tests OK**.

## 5. Boundaries

- Plan is data only: no file was written to an a6400 target, no module loaded,
  no camera access performed.
- No UVC function/frame is claimed; no compatibility success is implied by the
  plan's `ready` branch either (the plan never sets `executable: true`).
