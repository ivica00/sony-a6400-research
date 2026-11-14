# E0152: Shared UVC Video and Sony PC Remote Control Boundary

Date: 2026-11-08.

## Scope and Physical Finding

The user requests UVC video while retaining Sony PC Remote control. The camera, according to the user and read descriptors, is connected in Mass Storage mode. The existing debugger responds. Reading `/proc/modules` showed `usbg_storage` and `usbg_stillimage` loaded, without `usbg_video_a6400`. The mere presence of the stillimage module does not prove an active PC Remote interface.

`tools.research.capture_sony_usb_layout` read standard USB descriptors without changing configuration, claiming interfaces, starting a PTP session, or resetting. Result: `artifacts/hardware/uvc-ptp-coexistence-e0152/host-usb-descriptors.json`. Sony VID/PID 054c:0ca8, one configuration, one interface 0 of class 08/06/50, Bulk IN 0x81 and Bulk OUT 0x02, both max-packet 512. No PTP interface exposed. WPD enumeration of Sony devices returned an empty list, matching the MSC state. Windows Get-PnpDevice check failed due to access denied; the mode conclusion is based on the successful libusb read, not that check.

## Current UVC Module Boundary

`a6400_uvc_commit_descriptors` in `tools/native_camera/uvc_composite_shim.c` disconnects USB, stops gcw, swaps the descriptor table, and starts a single-function configuration (`desc_arg.is_dual=0`). Then it reconnects USB. This is a USB configuration replacement; the name composite does not prove UVC+PTP. The existing UVC bridge expects Bulk IN 0x81 (E0142), which is now used by MSC. This proves a conflict when naively adding MSC to the existing UVC, but does not yet prove a conflict with PC Remote endpoints: those remain to be read.

E0150 proves test-pattern transfer through Sony UVC. It does not prove the sensor. E0151 records real sensor over PTP 1024x680. That is not proof of UVC sensor, simultaneous PTP control, or 1280x720 sensor UVC. E0149 physically proves an empty JPEG ring in the tested MSC state; the cause of the full ISP/sensor standby policy remains an interpretation, not a separate measurement.

## Fixing False Control Confirmation

`/api/control` in CinemaHUD previously modified only the host's `camera_state` and returned success without a Sony command. Now it returns HTTP 501 and `applied:false`, without changing state. Status reports that control is unavailable. REC no longer locally lights up the recording indicator or shows a start confirmation. The client displays the real response error. Existing initial exposure values remain unverified display data; they are not camera telemetry.

HTTP regression check for ISO, REC, and attempting to change availability flags confirmed rejection and unchanged state. No physical camera was used for that check and no Sony write command was proven.

## Next Physical Step

Repeat the read in PC Remote mode:

```
python -m tools.research.capture_sony_usb_layout --output artifacts/hardware/uvc-ptp-coexistence-e0152/pc-remote-usb-descriptors.json
```

Then prove the original stillimage callback/endpoint contract and free controller channels before building a shared UVC+PTP table and modifying the bridge. Preserve Sony shooting state and memory ownership. The existing sensor feeder unconditionally sets Rule 5, resets SET_PATH, and restores Rule 0 on exit; that is not a verified contract for a camera already shooting in PC Remote mode. Do not run it in that state without resolving ownership and restoring prior state. Also check actual JPEG dimensions against the UVC profile.

In this step no module was loaded, no feeder was started, no USB mode was changed, and nothing was written to the camera, SD, or persistent storage. UVC+PTP coexistence is not completed.

## Regression Verification

`python -m unittest discover -s tests`: all 600 tests passed in 17.185 s. The first attempt had four temporary-file access errors; the same suite repeated with the required access passed without error. These checks do not prove physical UVC+PTP coexistence or physical SD card access.
