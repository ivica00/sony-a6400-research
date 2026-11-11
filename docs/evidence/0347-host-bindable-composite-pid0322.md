# E0347 — Host-bindable composite achieved: Windows binds PTP (MI_00) and UVC (MI_01) children

Date: 2026-11-11. Physical RAM-only test. This is stage-1 success of the
E0346 roadmap.

## Change

`a6400_uvc_ptp_candidate_identity()` now overrides `idProduct` to **0x0322**
(device descriptor metadata bytes [2..3]) while keeping VID 0x054C, device class
EF/02/01 and the PTP+UVC configuration (PTP interface 0 class 6/1/1 with 3
endpoints; UVC VC interface 1 + VS interface 2 with IAD, 173-byte config).
Rationale: the live PC Remote PID 0x0CAA is associated with the single-function
WPD driver, which prevented Windows usbccgp from starting the composite
(ProblemCode10 in E0207/E0208 and no PnP device in E0344). Enumerating the new
composite under PID 0x0322 makes Windows treat it as a fresh composite device.

- Build: `artifacts/native/uvc-ptp-module-e0347-pid0322/usbg_video_a6400_shared_candidate.ko`,
  **73,052 bytes**, SHA-256 `9a79fd2ee305640b732e10422f14b91f4f6fdb35161a4be83d3e4cf1b4fd940b`.
  Built inside WSL python (Windows→WSL subprocess path was denied); builder
  steps 1–4 succeeded, step-5 guard audit deferred (Unicorn unavailable in WSL).
- Structural verification on Windows passed: fops relocations
  (__this_module / a6400_uvc_shared_ioctl / a6400_uvc_shared_release),
  only documented reference instruction patches (0x116c/0x13e8/0x13ea),
  init/exit text prefixes preserved, vermagic exact, 55 imports all
  module/kernel-resolvable, no GPL-only imports.

## Physical result (e0347 + p4 runner, PC Remote switch)

Host PnP during the active session (ProblemCode all null):

```
USB  USB Composite Device      USB\VID_054C&PID_0322\CF93603BE631
WPD  MTP USB Device            USB\VID_054C&PID_0322&MI_00\...   (PTP child)
Camera ILCE-6400               USB\VID_054C&PID_0322&MI_01\...   (UVC child)
```

DirectShow device list captured during the session:

```
"ILCE-6400" (video)
```

This is the first time the composite PTP and UVC children both bind on Windows
with no problem code. Stage 1 of E0346 is met.

## Still open

- UVC streaming is not enabled yet in this module (`ENUMERATION_ONLY` build,
  REG_BUF/ENABLE rejected) — capture/open after the session reported no video
  device once the overlay was gone, and no frame was obtained.
- PTP client discovery via pmca WPD did not find the composite MI_00 device in a
  quick check; needs a binding test **during** the active window (the device is
  a WPD child of a composite, so it must be enumerated/opened by instance).
- Session boundary: the composite devices persisted after the runner hold in
  this test; camera must return to MSC to read `/tmp_bt/pid.log`.

## Next

1. Build the transport-enabled variant (stage 2): forward REG_BUF/UPDATE/ENABLE/
   WAIT to the original driver and drop the enumeration-only bridge restriction;
   keep the PID-0x0322 descriptor fix.
2. During the active window, test: DirectShow open + frame capture, and WPD/PTP
   binding of MI_00 (PTP client), then sensor feed (stage 3).
