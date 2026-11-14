# UVC Mode Development & A5KU Virtual USB Testing Guide

This guide summarizes the clean-room A5KU ("USB over TCP") stack and how it connects to the `CXD90045` UVC+PTP contracts for local development and testing.

## Architecture

1. **Wire Protocol (`src/a6400/execution/a5ku_protocol.py`)**
   - Implements the 16-byte little-endian A5KU framing (`magic=0x5541`, `HELLO`, `RESET`, `CONTROL`, `OUT`, `IN`, `CANCEL`, `EVENT`) adapted from `Oein/a5000-emulator` (`docs/RE_USB_HOST_PATH.md` §5).
   - `A5kuDeviceSession` enforces attachment state, monotonic `generation` counters, and fail-closed `NODEV` / `STALL` responses.

2. **Verified UVC+PTP Enumeration (`src/a6400/execution/a5ku_host_enum.py`, `usb_host_enum.py`)**
   - `A5kuHostClient.enumerate_uvc_ptp()` executes the 6-step USB enumeration sequence (`RESET`, `GET_DESCRIPTOR(DEVICE)`, `SET_ADDRESS`, `GET_DESCRIPTOR(CONFIG)` x2, `SET_CONFIGURATION`), validates the 173-byte `E0154`/`E0317` UVC+PTP composite descriptor (`cc99cbd9...`), and produces the `UsbControl` `0xA4001` -> FSM event `0x13` plan.

3. **TCP Server & UVC Test Handler (`src/a6400/execution/a5ku_server.py`)**
   - `A5kuTcpServer` serves one host client at a time (`127.0.0.1:7643` by default) without requiring kernel USB/IP drivers on Windows.
   - `A5kuUvcTestHandler` supports UVC 1.1 26-byte `VS_PROBE_CONTROL` / `VS_COMMIT_CONTROL` (`SET_CUR`/`GET_CUR` on interface 2), `SET_INTERFACE(2, 0|1)`, and explicit caller-queued frames on endpoint `0x82` (failing closed with `STALL` when empty).

4. **Relationship to Track B (`DWC3` / `E0476`) & Guest `/dev/usb/video`**
   - Track B physical camera experiments (`E0476` `a6400_uvc_status_prearm`) target the `CXD90045` Synopsys `DWC3` hardware controller (`dwc->ep0state`, `__dwc3_ep0_do_control_status`), which is distinct from `CXD90014`'s Fujitsu `F_USB20HDC` controller.
   - Guest `/dev/usb/video` kernel ABI boundaries remain governed by `src/a6400/execution/usb_video_contract.py` and `src/a6400/execution/guest_usb_video.py`.

## Quick Verification

Run the self-test harness:

```powershell
.\venv\Scripts\python.exe -m tools.research.a5ku_uvc_harness --self-test
```

Run the A5KU & UVC unit tests:

```powershell
.\venv\Scripts\python.exe -m unittest tests.emulator.test_a5ku_protocol tests.emulator.test_a5ku_host_enum tests.emulator.test_a5ku_server -v
```
