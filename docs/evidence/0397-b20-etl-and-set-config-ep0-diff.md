# E0397 — B20 transition analysis: SET_CONFIGURATION lies between the fast GET_DESCRIPTOR and the stalled GET_CUR; no PTP/interface-0 transfer is visible; teardown hook

Date: 2026-11-12. Offline only. No camera run.

## 1. B20 ETL extraction result (limited)

`usb-capture.etl` 168,886,272 B was converted with `tracerpt` to XML; the XML is
~72 MB / 37,846 events (the conversion was truncated by the run window). Extracted
control URBs: only 48 events and **2 paired control transfers**, both to the audio device
(`0x5973C67A3808`), no Sony 054C:0322 URB. `extract_select` found **0 SELECT_*** events:
the UCX trace does not carry SET_CONFIGURATION/SET_INTERFACE records on this host, so
the B20 ETL cannot prove/deny an EP0 collision from those requests.

What is on disk (B18 full ETL, same device/sequence) is consistent: after the descriptor
reads there is a gap, then GET_CUR; no PTP interface-0 class/bulk/interrupt transfer is
present in the Sony control list, and only the class GET/SET URBs appear. The B20 RAM
ring records no class/queue activity between `RR 32` (last GET_DESCRIPTOR at 128.91)
and `RR 35` (GET_CUR at 136.00), so no class handler ran in that gap; the gap is the
host/driver SET_CONFIGURATION/SET_INTERFACE configuration window.

## 2. Disassembly: configuration changes before GET_CUR

- `setup_set_config_comp 0x602b939c` is the SET_CONFIGURATION completion: it checks
  `req->status==0`, `gc+0x14`/`gc+0x18`, and calls `0x602b5c14` (the gadget config/U DC
  state transition). It does not arm an EP0 status TRB itself.
- The endpoint-enable path is `__dwc3_gadget_ep_enable 0x602b05fc` /
  `dwc3_gadget_ep_enable 0x602b099c`; `setup_req` standard requests use
  `0x602b8ac8(gc,wIndex)` (config/interface handling) and the `gc+0x81` gating.
- The `dwc3_ep0_set_config` symbol is not present under that name in the retained
  kallsyms; the relevant config work is in the setup/delegate path plus
  `__dwc3_gadget_ep_enable`, which changes endpoint DEPCFG/DEPXFERCFG state. In
  particular, configuration changes endpoint resources while EP0 remains the setup
  endpoint. The class path then runs `do_control_status 0x253c` on `eps[0]`, which arms
  `STATUS3 0x0c43`; the status stall implies the post-configuration EP0 resource/ownership
  state is not what the class path assumes, not a data-path or request-flag difference.

A complete field-by-field DEPCFG/DEPXFERCFG comparison would require the full
configuration URBs/registers, which this capture did not expose.

## 3. Safe restore hook

`a6400_uvc_restore_descriptors()` is currently called from module unregister/error paths.
For a mode switch without the debugger, the safe trigger is the gadgetcore
**disconnect** callback (`disconnect_cb` in the bridge), which is invoked when the host
detaches/VDC drops; call `a6400_uvc_restore_descriptors()` there only when
`b->started==0`/no stream is active, so a transient host disconnect does not tear down a
live session. Do not call it from a transient `SET_INTERFACE(alt=0)`.

The B18/B19 mode-switch hangs happened because the host switch was attempted while the
module still controlled the UVC configuration and no disconnect callback ran before the
switch; the debugger was unreachable to `rmmod`. A disconnect/vbus drop hook is the
clean automatic path, but it must be proven to fire on the camera's mode switch.

No camera run or build was performed for E0397. The B20 ETL remains available for a
full (untruncated) decode.
