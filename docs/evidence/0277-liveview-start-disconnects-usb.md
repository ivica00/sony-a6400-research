# E0277 — Liveview start disconnects the composite USB device (Windows "device disconnected")

Date: 2026-11-09. Physical F8-5 observation + read-only MSC checks.

## Observation

- During F8-5 the camera LCD **did show liveview**.
- At the moment liveview appeared, **Windows played the "device disconnected" sound**.
- The session monitor then recorded `pcremote_active=true` but `ptp_count=0` / no PTP child; the
  probe stayed `no_wpd_device`; the teardown nevertheless completed cleanly with a receipt.
- The no-module control (E0256) entered liveview without such a disconnect and delivered frames.

## Interpretation

Entering liveview triggers a **USB disconnect/re-enumeration** of the composite device. The host
loses the PTP child; the probe cannot connect; no frame can arrive. In F8-5 the gadget returned
in a state where teardown still completed; in F7 (probe already connected) the same transition
ended in a stuck gadget (battery restart). This explains the repeated no-frame sessions better
than the PTP pipeline hypotheses: the host is disconnected at the moment liveview starts.

The likely cause is a camera-side gadget reset/reconfiguration on liveview start (the app's
SICD/liveview start, `actionSicdStart` family) interacting with the composite descriptor set:
the device does not re-enumerate with the PTP child (or re-enumerates without it).

## Next

- Capture the transition: Windows USB event log/SetupAPI around the disconnect, and the camera-side
  gadget reset path (which app action resets the UDC; does it re-apply the composite descriptors?).
- Determine whether the module can keep the device enumerated through liveview start (handle the
  reset/re-apply descriptors, or defer liveview start until the host is bound), or whether the
  camera's mode switch fundamentally changes the USB configuration.
- No new physical session without a concrete plan.
