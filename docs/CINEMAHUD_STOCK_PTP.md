# CinemaHUD with original a6400 firmware

Current focus (2026-11-10): stock PC Remote PTP liveview and a two-way settings
menu. The camera remains in MSC for the debugger until the physical PC Remote
test is arranged. No camera writes or mode switches were performed for this change.

## Launch

After selecting USB Connection -> PC Remote on the camera, run
`scripts/launch_cinemahud_ptp.bat`, then open http://127.0.0.1:8080/ .
The launcher selects PTP explicitly and never launches the UVC module/feeder.
MSC debugger access is unavailable while using PC Remote.

## Implemented, awaiting physical validation

- Sony handshake response validation, existing PTP JPEG liveview.
- Read Sony extended property descriptors (`0x9209`) once per second.
- Populate shutter, aperture, ISO and EV from camera values and enumerations.
- Send absolute values using `0x9205` with the datatype reported by the camera.
- Refresh restrictions before writing; require successful response AND matching
  camera readback before reporting a confirmed change.
- Poll body changes back into the menu, without forcing PC-priority mode.
- Serialize commands and liveview on the WPD/COM owner thread. HTTP handlers
  queue requests; they never operate the COM camera object.
- Disable unsupported/restricted values; do not invent ISO, lens, or battery data.
- Serve locally, reject cross-origin commands, cancel expired queued commands.

This is an initial settings backend, not a claim of full PTP coverage.
Recording, focus and white balance controls are not implemented. REC stays
disabled. Whether body controls remain usable
in the selected PC Remote mode requires a physical test.

## Physical update, 2026-11-10

After the operator manually selected PC Remote, Sony WPD connected and all four
handshake stages returned 0x2001. Captured JPEG: 1024x680, 123091 bytes. The full
1730-byte 0x9209 payload parsed successfully (raw and decoded receipts retained).
Initial values: shutter 1/100, aperture f/2.8, ISO Auto.

Absolute ISO 0x9205 returned OK but failed readback; Auto remained confirmed.
Implemented legacy ISO stepping via 0x9207 with a signed one-byte notch,
enumeration-order direction, bounded progress and readback after every step.
Physical test: Auto -> 800 (confirmed), liveview frame 1024x680/158853 bytes,
then Auto restored (confirmed). Repeated through the running CinemaHUD HTTP API:
status=confirmed, value=800, then restored value=16777215 (Auto).
24 focused tests now pass, including the legacy Auto/number ordering regression.

CinemaHUD is running at http://127.0.0.1:8080/ . Body-to-HUD changes and EV writes
have not yet been physically validated. Shutter/aperture are range-only in the
observed descriptors and remain disabled for writing in this implementation.
Receipts: artifacts/hardware/cinemahud-stock-pcremote-20261110/ .

## Exposure control correction, 2026-11-10

User reported ISO mostly working and other controls unavailable. Reviewed the
requested upstream SonyUSBBackend.swift `setValue`, `setShutterSpeed`,
`setFNumber` and SonyPTP.swift candidate tables:
https://github.com/shivvyas2/Sony-Alpha-A6400-Cinema-Monitor/blob/main/Sources/SonyCameraKit/USB/SonyUSBBackend.swift

Cause: this client had only implemented legacy notches for ISO and disabled
range-only shutter/aperture descriptors. EV also required legacy notches rather
than an acknowledged but ineffective absolute command.

Generalized the independent Python implementation: 0x9207 one-byte signed steps,
shutter direction by negative exposure time, aperture/EV by numeric value, ISO
by enumeration position. Candidate shutter/aperture pickers now work for range
descriptors; candidates are not a claim that every lens/mode supports every value.
Readback remains mandatory, with settling, no-progress, overshoot and time bounds.
Nearest/skipped values never report exact confirmation.

Physical tests via the running CinemaHUD HTTP API all returned confirmed:
- shutter 1/100 -> 1/125 -> 1/100;
- aperture f/2.8 -> f/3.2 -> f/2.8;
- EV 0 -> +0.3 -> 0.

All originals restored. Receipt: `exposure-controls-roundtrip.json` in the same
hardware directory. 25 focused tests pass, including range-property roundtrips
and EV direction independent of its non-monotonic enumeration. Running owned
server process updated from PID29756 to PID27704. No firmware/module changes.
Earlier statements that shutter/aperture writes remain disabled are superseded
by this physical validation.

## Validation

23 focused tests passed on the delivered version. Tests cover malformed
descriptors, wire datatype, valid/restricted values, camera rejection, missing
readback, body changes, queued cancellation, HTTP control boundary, frame parsing,
device selection and close/diagnostics. JavaScript syntax passed `node --check`.
These are simulated transport checks, not physical compatibility proof.

Windows WPD device inventory returned `[]` on 2026-11-10, consistent with the
operator's confirmation that the camera is currently in MSC for the USB debugger.
No PC Remote handshake, settings write, or frame capture was attempted this cycle.

## Next physical acceptance test

1. Select PC Remote manually; retain original firmware and use the PTP launcher.
2. Capture actual `0x9209` bytes and compare current values/options with the body.
3. Confirm a real JPEG frame; record its actual dimensions without assuming 1080p.
4. Change one advertised ISO value in CinemaHUD; compare PTP readback and camera.
5. Change ISO using body controls and observe CinemaHUD update; restore starting ISO.
6. Repeat for shutter/aperture/EV where camera mode and lens permit them.
7. Verify rejection in a restricted mode and disconnect handling.

Protocol references (wire facts; implementation is independent Python):
- https://github.com/gphoto/libgphoto2/blob/master/camlibs/ptp2/ptp.h
- https://github.com/gphoto/libgphoto2/blob/master/camlibs/ptp2/ptp-pack.c
- https://github.com/gphoto/libgphoto2/blob/master/camlibs/ptp2/ptp.c

Existing physical stock-PTP liveview evidence: E0256, 1024x680 JPEG.
