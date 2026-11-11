# E0318 — Live 8.2.6.0 reaches service-idle; verified VBUS wakes proxies, no USB FSM transition

Date: 2026-11-11. Inputs: live 8.2.6.0 overlay runs resumed from retained
checkpoints; verified 16-byte VBUS UIPC body from E0304
(`00000000010000000000000000000000`, queue `0x012002DA`). No camera writes, no
mode change, no module load; emulator-only, opt-in injection of a
previously-verified physical body.

## 1. Live 8.2.6.0 now boots to service-idle without any boundary

With the signature-guarded IT repairs (live libc `0x50259bfc` literal repair,
live libObj `0x104E4E`/`0x104E56` r2 repairs, live libc post-IT clear at
`0x5026ECFC`/`0x5026ED06`):

| Run | Resume point | Result |
| --- | --- | --- |
| e0666-live-itfix2 | fresh, live libObj | passed 77,164,879; stopped at 140,140,849 (live-libc malloc.c:3684, later fixed) |
| e0672-live-full2d | fresh, full live overlay | **181,787,893 instructions, boundary null** |
| e0673-live-full2e | resume e0672 checkpoint | **557,079,079 instructions, boundary null** |
| e0674-live-usbwake | resume e0673 + VBUS injection | **834,751,499 instructions, boundary null** |

State at e0673/e0674 (56 threads): full service layer initialized —
`main`/`THREAD_INFRA0` blocked_futex, `THREAD_INFRA1` running (libmpr path),
`UsbControl`/`UsbBusPower`/`BusPower` blocked_futex on their own futexes
(`0x10FFED3C`/`0x5E23ED54`/`0x1282ED3C`), GPS (`GpsRsMainThread`,
`gps_main_thread`), `MMgrCtrl`, `CameraBackground`, `WlanResource_*`,
`NetServiceMainTh`, `DVDFlashBackup`, plus `grm_dn_vdf_if`. No
`THREAD_APP`/Appframework yet, semaphore `0x0083037A` absent, no
viewUnified2/OSD mapping.

## 2. Verified VBUS injection on the live build (E0304 body)

Injection at instruction 557,079,079 into queue `0x012002DA` (16 B, SHA-256
`c363a7bc…`):

- `woken = [1001, 1002, 1003, 1006]` — the four `uipc_proxy_*` threads wake,
  matching the extracted-build E0304 observation.
- After the injection the proxies return to `blocked_uipc`; the USB service
  threads **do not leave their futex waits**: `UsbBusPower` still
  `0x5E23ED54`, `UsbControl` still `0x10FFED3C`, `BusPower` still
  `0x1282ED3C`. No new FUTEX WAKE on the local-queue futexes and no otgcore
  `SET_CONFIG`/mode transition is observed.
- The run continues to 834,751,499 instructions with `boundary = null`; no
  new service/UI thread beyond `grm_dn_vdf_if`/`thread_1055` appears.

This reproduces, on the live 8.2.6.0 build, the extracted-build E0304
conclusion: the verified VBUS producer wakes the async proxies but is **not**
sufficient to move the USB FSM. The missing part is the host-side
enumeration/`SET_CONFIG` path (the inbound `{0x6103, 0x0A4001, param 0x1006=0}`
switch), not the VBUS delivery contract.

## 3. Boundary state

- `usb_vbus_changed_mwf_0x0a4000_producer_not_derivable` — unchanged; no
  construction of MWF `0x0A4000` observed.
- Host USB enumeration / `SET_CONFIG` / descriptor-request sequence remains
  unmodelled: no legitimate host transaction stream exists in the emulator, so
  injecting guest-internal `ObjMsg` bytes would be fabrication and is not done.
- Live 8.2.6.0 is nevertheless a **stable, boundary-free platform** for future
  host-control contracts (UVC/PTP descriptors are already verified, E0316/E0317).
- No `viewUnified2`/OSD/GUI frame; UVC/PTP still not functional.

## 4. Next evidence-backed work

1. Host-control contract: model the USB enumeration/`SET_CONFIG` transaction
   sequence as an explicit opt-in device contract (descriptor requests served
   from the verified E0154 UVC+PTP descriptor and MSC baseline), then observe
   whether the original firmware 8.2.6.0 moves its USB FSM — no fabricated
   guest messages.
2. UVC activation sequence and video buffer/DMA contracts from E0316.
3. Keep the live-build repairs signature-guarded; no physical camera writes.
