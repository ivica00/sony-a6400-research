# E0153: PC Remote Channels and Original PTP Contract

Date: 2026-11-08. Continuation of E0152 after the user switched to PC Remote.

## Physical Readback

Windows WPD enumeration found Sony `054c:0caa`, serial number CF93603BE631. Windows PnP confirms ILCE-6400, class WPD, status OK. Libusb under that driver did not list the device. An empty `pc-remote-usb-descriptors.json` result is not proof of camera absence.

New tool `tools.research.capture_sony_usb_hub` reads standard descriptors through the Windows USB hub without replacing the driver. It uses only GET_NODE_INFORMATION, GET_NODE_CONNECTION_INFORMATION_EX, and GET_DESCRIPTOR_FROM_NODE_CONNECTION; no resetting, claiming interfaces, or setting configuration. Microsoft documentation for this approach: https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/usbioctl/ni-usbioctl-ioctl_usb_get_descriptor_from_node_connection

Saved original result: `artifacts/hardware/uvc-ptp-coexistence-e0152/pc-remote-hub-descriptors.json`. One configuration, interface 0 of class 06/01/01, 39 bytes total:

| Function | Address | Type | Max packet | Interval |
|---|---|---|---|---|
| PTP bulk IN data | 0x81 | Bulk | 512 | 0 |
| PTP bulk OUT data/commands | 0x02 | Bulk | 512 | 0 |
| PTP events | 0x83 | Interrupt | 32 | 7 |

This confirms a real conflict of the current UVC Bulk IN 0x81 with PC Remote PTP.

## Original ARM Contract

`tools.research.probe_ptp_endpoint_contract` verifies SHA-256 of original `usbg_stillimage.ko` `d4843c6abac908881ef5a96fd570fb345f766fff9ee562413f5f63e9cc7e0ff9`. Three original flat ARM slices from `core_cb_start` write 0x81, 0x02, and 0x83 into requests at offsets +14, +1c, and +24. They stop before the allocator call. Scratch registers and memory are explicit test fixtures; a successful allocator was not simulated nor was the entire START executed. Matching physical descriptors is not proof of equality of all live module bytes.

Eight additional original ARM checks of `dwc3_wIndex_to_dep` show mapping 0x81 -> dwc+dc, 0x02 -> +e0, 0x83 -> +ec, 0x84 -> +f4, and returning zero for an inactive endpoint. Kernel SHA-256 verified against the earlier contract. Slots and enabled flags are explicit fixtures. Lookup 0x84 is not proof that that endpoint is physically allocated, free, or supported by the controller.

Results of all 11 checks: `artifacts/hardware/uvc-ptp-coexistence-e0152/ptp-original-arm-controls.json`.

## Real Sensor Frames over PTP

Sony SDIO handshake returned 2001 for all four steps, ExtDeviceInfo 136 bytes. The first bounded sequence had four empty initial attempts and six JPEG frames. The second sequence got ten frames without empty attempts, all 1024x680, with distinct SHA-256 values, about 101 KB per frame. Duration of the second short sequence 0.294 s is not a measurement of sustained FPS.

Both reports and the first successful frame of the second sequence were saved: `pc-remote-sensor-capture.json`, `pc-remote-sensor-capture-warm.json`, `pc-remote-sensor-frame.jpg` in the above directory. Image visually inspected: real desk, packaging, cables, and speaker; not a test pattern. Exposure or capture changes were not tested. This is PTP, not UVC.

## Implementation Implications

Preserve PTP interface 0 and addresses 81/02/83. Proposed working topology is UVC VideoControl 1 and VideoStreaming 2, with a dedicated Bulk IN endpoint. 0x84 is a candidate for verification, not an approved physical configuration. The current module also has audio interfaces and IAD injection expecting four interfaces; this must be explicitly reworked, along with VC/VS cross-references, callback interface routing, and Windows WPD/usbvideo driver binding. The current START bridge is also tied to dwc+dc and address 81; changing USB descriptors alone cannot suffice.

What remains is proving controller capacity and availability, building a shared descriptor table and callback lifecycle with return to PC Remote, then binding the original JPEG producer with proven ownership. Do not reset active shooting SET_PATH/DMM Rule 5/0 with the existing MSC feeder. Dimensions 1024x680 must not be sent as if they were the advertised 1280x720.

## Checks and Final State

Five parser checks pass: real descriptor and rejection of truncation, zero length, wrong endpoint count, and wrong interface count. All 11 new original ARM controls pass. The previous full suite of 600 tests from E0152 was not re-run because existing runtime did not change. No UVC module was loaded, no feeder started, no USB mode changed, or written to camera, SD, or persistent storage. Camera was left in PC Remote mode. Simultaneous physical UVC+PTP operation remains unproven.
