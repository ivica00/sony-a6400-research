# E0390 — e0386 vs e0388 diff and B17 capture-window check: B17 ETL is post-enumeration; XACT_ERROR is the known post-wedge signature

Date: 2026-11-12. Offline only. No camera run.

## 1. Exact e0386 → e0388 code change

Byte-identical core EP0 functions between the two compiled modules (`.text` SHA-256
of the ranges):
- `core_cb_class` (0x17b0, 0x2c0 B): **same** `c6a30181c7277acc`.
- GET helper `0x1390` (0x1d0 B): **same** `3a22bf00addf43a0`.
- probe helper `0x11bc` (0x1d4 B): **same** `4951c9a96d9470e8`.

What differs:
- e0386 had, and e0388 removed from the production path:
  - `g_ep0_ops_shadow` install (`ep0->ops=5f5722f4`, queue `5f5681bc`);
  - `a6400_uvc_ep0_queue_wrap` (OUT `req->dma` mapping + late `req->complete`
    replacement + all GCRO/log/printk/tstamp calls);
  - `a6400_uvc_ep0_complete_thunk`;
  - CLASS-entry LR/state/ev/GCRO/snapshot logging and hot-path timestamps.
- e0388 keeps: `g_class_dir_out` assignment, the local `translated[8]` wIndex
  translation, target callback call, `setup_req` result path, reference
  `core_cb_class`/GET helper/probe helper (byte-identical).
- e0388 also changes the reference rodata 26-byte template (new bytes at module
  `0xaa7e`) and the VS frame descriptor max buffer (1,843,200).

No required state is skipped by the trace removal:
- `req->dma`: the e0386 queue wrapper set it **only for OUT** (`g_class_dir_out`
  true). GET_CUR is IN; e0386 left `dma=00000000`/`mapped=0` and still got
  `actual=26` (`GET queue` B12/B16), so GET does not depend on the wrapper.
- `g_ep0_last`/`g_class_lr`/snapshots were log-only; `g_class_dir_out` is still set.
- With no shadow installed, `ep0->ops` is the stock kernel `603dfb4c` with queue
  `602b2ad0`, which is the reference path used by the physically streaming build.
- `core_cb_class` returns 0 for GET/SET in both modules; `setup_req` maps 0 to
  `clear_halt_ep0`/return 0.

## 2. B17 ETL capture window

`usb-capture.etl` first events:
```
06:57:14.997946900  EventTrace header
06:57:14.998903700  USBHUB3 id6  "USB Device Information" (rundown; device already present)
06:57:14.999085300  USBXHCI id4  "USBXHCI Device Information" (rundown)
06:57:14.999086800  USBXHCI id5  endpoint rundown: 0x0, 0x81, 0x2, 0x83, 0x84...
06:57:15.161297300  UCX 53 GET_CUR A1 81 0100 0002 001A
06:57:15.164222200  UCX 21 GET_CUR -> 0xC0000011 XACT_ERROR (2.925 ms)
06:57:15.164476900  UCX 53 GET_CUR retry
06:57:15.167335200  UCX 21 retry -> 0xC0000011 XACT_ERROR (2.858 ms)
```
The capture starts with **rundown** events (device already enumerated/configured), not
plug-in or port connect. No enumeration GET_CUR/SET_CUR is in this ETL; only ffmpeg's
two 2.9 ms retries after the device was already in the wedged state.

B17 camera log confirms the same sequence: `reference START entry iface=2` at
117.551 and a second START/STOP later; the initial PC-Remote enumeration happened
before ETW was started. B14's ETL has the corroborating sequence:
`GET_CUR #1 5.010 s -> SUCCESS 26 B`, `SET_CUR #2 5.009 s -> CANCELED`, then
`GET_CUR #3 2.3 ms -> XACT_ERROR`. The 2.9 ms XACT_ERROR is therefore the
**post-wedge retry signature**, not evidence that e0388 broke GET_CUR.

## 3. Answer

- e0388 did **not** alter `core_cb_class`, helper 0x1390, or helper 0x11bc; it only
  removed logging/shadow wrappers (not required for GET IN, where e0386 also had
  `dma=0`) and changed the probe template/descriptor. The class path and return
  values are unchanged.
- B17's ETL was started **after plug-in enumeration**; it captured only ffmpeg's
  retries on an EP0 that had already been wedged by the initial enumeration
  GET_CUR/SET_CUR. The XACT_ERROR is the same post-wedge behavior as B14 URB #3.
- To decide whether e0388 caused a real initial-enumeration regression, the next
  run must start ETW **before** the camera is switched/plugged in, or add a single
  `STOP`-time counter log (no hot-path printk) with `class_call_count`,
  `get_cur_count`, `set_cur_count`; zero counters would mean the host never reached
  the class handler in that capture.

No camera run or build was performed for E0390. Suite remains **1312 OK**.
