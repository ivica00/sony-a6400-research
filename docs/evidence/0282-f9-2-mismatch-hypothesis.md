# E0282 — F9-2: mismatch hypothesis and the next test boundary

Date: 2026-11-09. Offline analysis; no new physical session yet.

## Shim state (from `uvc_composite_shim.c`)

- `a6400_uvc_commit_descriptors`: saves the MSC desc_tbl, `setup_disconnect` + `usb_gcw_stop`,
  installs the UVC descriptor bundle (`save_desc_tbl` 0x602bc550), calls `usb_gcw_start(0)`,
  arms EP0, hooks `make_config_desc` (patch `setup_req+0x128`), promotes the shadow UVC drivers,
  pullup(1).
- The hook is **global**: every config-descriptor request returns the composite (3 interfaces)
  as long as the hook is installed.
- The app's liveview/PTP start (`CUsbGadgetStill::on_create` → gadgetcore ioctl) goes through
  `usb_gcw_stop` / `usb_gcw_start` and re-creates the stillimage gadget with **its own**
  descriptor table/function set.

## Mismatch hypothesis

After the app's re-create, the module's `setup_req+0x128` hook still returns the composite
configuration, but the re-created gadget has only the stillimage function/drivers. Windows then
sees a configuration whose interfaces 1/2 have no matching functions — a descriptor/function
mismatch. That would explain: disconnect at liveview start, no PTP child afterwards, and no
probe connection. It is a stronger explanation than enumeration timing alone.

## Mitigation options

A. **Consistency on re-create:** hook `usb_gcw_stop`/`usb_gcw_start` (or the stillimage create)
   and temporarily **unhook** `make_config_desc` around the app's re-enumeration, so the host
   sees a consistent stillimage-only PC Remote device (PTP child returns; probe can connect).
   After the host binds/liveview, re-install the composite hook and trigger a controlled
   re-enumeration for the UVC+PTP combination.
B. **Re-apply the UVC function set** after the app's start (install the module's desc table and
   promote the shadow drivers again) so the composite stays consistent. Harder: requires the app
   function list and careful ordering.

## Next test boundary

A bounded PC Remote test is now needed to discriminate:

1. `capture_usb_events` at 0.2 s (E0281) started before the switch.
2. e0251 session + fixed probe (or no probe, to avoid cross-effects) with the camera LCD observed.
3. After liveview start, inspect the transitions: does the re-enumerated device appear as
   PTP-only, composite, or descriptor-failed (VID_0000/problem)? Does the PTP child return?

That result selects mitigation A or B. No code change is made before this observation.
