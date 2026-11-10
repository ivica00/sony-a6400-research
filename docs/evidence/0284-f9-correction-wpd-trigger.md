# E0284 — Correction of F9: no LCD liveview; the liveview-start trigger is host WPD activity

Date: 2026-11-09. Operator correction + offline analysis.

## Correction of E0283

- In the F9 observation the camera LCD **did not show liveview**.
- The 0.2 s capture timeline is therefore: parent at 21:01:48, composite+PTP+UVC children at
  21:01:58.7, children gone at 21:02:54.4, all gone at 21:03:07.6.
- The session duration was 60 s from PC Remote detection (~21:01:48), so **21:02:54 is the
  session teardown**, not a liveview start. The composite stayed healthy for the whole session
  and was dismantled by the runner's teardown.
- E0283's "children vanish at liveview start" interpretation is **superseded**. The
  liveview-start disconnect observed in F7/F8-5 remains real, but F9 did not reproduce it.

## Revised hypothesis

The liveview start (and its USB disconnect) is triggered by **host WPD/MTP client activity**,
not by the camera's PC Remote UI alone:

| Session | Host WPD client | LCD liveview | Disconnect |
| --- | --- | --- | --- |
| F9 | none (session monitor only) | **no** | no (children survive to teardown) |
| F8-5 | probe polling `listDevices` (never connected) | **yes** | yes |
| F7 / F5b-2 | probe connected (handshake) | yes | yes |

So the probe's **WPD enumeration** (`MtpContext.listDevices(0x054C)`) may itself start the
camera's PC Remote liveview, which re-creates the gadget and disconnects the device. The PTP
handshake may be incidental.

## Next probe design (offline first)

Separate the trigger:

- **P1 — WPD enumeration only**: poll `listDevices` (no open, no PTP), with the 0.2 s capture and
  LCD observation. If liveview starts and the disconnect occurs, enumeration is the trigger.
- **P2 — WPD open only**: `openDevice` + close (no PTP commands), same capture.
- **P3 — full probe**: current handshake/GetObject probe.

The next physical test should be P1 (smallest trigger), then P2/P3 as needed.
