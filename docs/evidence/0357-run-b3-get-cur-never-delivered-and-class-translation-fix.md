# E0357 — Run B3: KERNEL TRACE FOUND THE GAP (GET_CUR(PROBE) answered 0, never delivered); daemon parked; CLASS translation fix + Unicorn proof

Date: 2026-11-11. **Physical, user-authorized Run B3.** Module `8ea863ac…` (E0356),
daemon `58ef8e35…` (`--sd-log --sd-mount --dmesg-sd`). Camera ended in the
unknown-device state and required a battery pull; the SD card survived it, so this is
the first Track B run with a complete camera-side kernel trace and receipt.

## Run record

- Fresh boot (uptime 62 s at push), module readback-verified `8ea863ac…`, daemon
  `58ef8e35…`; daemon armed `--arm-transport --wait-pcremote --timeout 900
  --duration 150 --stats-interval 5 --sd-log --sd-mount --dmesg-sd`; INIT, DMA
  (`phys=0x05b40000`, 262,144 B), REG_BUF/ENABLE rc 0.
- Composite enumerated (`Camera ILCE-6400`, `WPD: MTP USB Device`, `USB Composite
  Device`, all OK). Host ETW armed manually with all four providers incl.
  **Microsoft-Windows-USB-UCX** (the capture-script wrapper failed on a relative path;
  the UCX capture itself succeeded).
- `wpd_device_dump.py`: **0 WPD devices** of VID 0x054C (reproduces E0354/E0355).
- One `ffmpeg -f dshow -i video="ILCE-6400"` attempt: failed
  `Could not RenderStream to connect pins`, `I/O error`.
- Daemon SD trace/receipt: `A6400K.LOG` **6,613 B / 129 lines, 0 errors**;
  `A6400RCPT.JSON` written; `A6400LD.LOG` 31,513 B. Host later saw only
  `USB\VID_0000&PID_0002` (CM_PROB_FAILED_POST_START) → battery pull; SD read back
  afterwards through a read-only vfat mount (`mount -t vfat -o ro /dev/mmca1 /tmp_bt/sd`,
  unmount rc 0).

**Decisive receipt:** `status=fatal, stage=parked, exit_code=4,
fail_reason="stop attestation failed state=-1,-1,-1,-1"`, `stop_verified=0`,
`hook_retired=0`, `freeze_tid_count=181`, `get_jpeg_polls=4499` all empty,
`sd_log.trace_lines=129`, `trace_errors=0`. The daemon **parked by design** and froze
181 threads, so the camera never re-enumerated. The battery-pull requirement in the
host-attempt scenario is therefore the daemon's fail-closed park, not (only) gadgetcore
corruption.

## Answers to the three questions

**Q1 — exact CLASS/VENDOR setup packets.** The kernel trace contains **exactly one**
CLASS request in the entire session, arriving during the ffmpeg attempt:

```
[ 194.856177] [a6400_sel] reject args dwc=689e5810 list=(null) count=0
[ 194.856491] [a6400_sel] match wrapper=697832e0 raw=68a1c1c0 ep=0x84 flags=00000001 count=1
[ 194.856750] [a6400_uvc] reference START entry iface=2 count=1
[ 194.856857] [a6400_uvc] reference START returned iface=2 count=1
[ 281.389073] [a6400_uvc] CLASS entry rt=a1 req=81 val=0100 idx=0002 len=001a
[ 281.389252] [a6400_uvc] CLASS exit result=0
[ 344.643240] [a6400_uvc] reference STOP entry iface=2 count=1
[ 344.643452] [a6400_uvc] reference STOP returned iface=2
```

i.e. `GET_CUR` (`bmRequestType 0xA1, bRequest 0x81, wValue 0x0100,
wIndex 0x0002, wLength 26`) — **VS_PROBE_CONTROL**, answered synchronously with
`core_cb_class` return **0**. No `SET_CUR` PROBE/COMMIT and no VENDOR request were ever
delivered: after a successful GET_CUR(PROBE) usbvideo would follow with SET_CUR; it
aborted instead. No CLASS request occurred during enumeration (only reference START).

**Q2 — raw wire wIndex or translated?** The reference class handler received **raw wire
`wIndex=0x0002`** (`idx=0002`; reference primary interface is 1). It did not reject or
misroute observable: it took the T6b GET_CUR-probe path and returned 0. The bridge was
**not** applying `a6400_uvc_ptp_translate_setup` on the CLASS path — that is now fixed
(see below).

**Q3 — did gadgetcore transmit the 26 bytes?** The UCX provider is present but its
payloads are pointer/TRB-level only: 29,977 UCX events sampled in the window
(IDs 26/27/30/31/65/66/69/70), all object/URB/TRB addresses and counters, **no decoded
`bmRequestType` or `USBD_STATUS`**; a direct "control transfer stalled" field is not in
this trace. The indirect evidence is nevertheless conclusive that the data phase did
**not** complete:
- kernel returned from `core_cb_class` at camera uptime **281.389** (host ~19:02:41);
- ffmpeg failed at **19:02:46.045** (≈5.0 s later — the usbvideo EP0 timeout);
- **no subsequent CLASS request ever arrived** (a completed GET_CUR(PROBE) reply would
  be followed by SET_CUR PROBE/COMMIT).
Additional Unicorn evidence: the E0351 harness now records the reference's EP0 `queue`
op call; for `GET_CUR` probe it is invoked with the request/buffer/length arguments and
returns success. So `core_cb_class` **does submit** the request; the failure is in
gadgetcore's EP0 completion/ownership after submission (the shadow/primary EP0 buffer
question), not in the callback.

## Offline fix implemented (and Unicorn-proven): CLASS setup translation

E0351 documents the reference handler expects the **native** interface number
("wire wIndex 2, native 1"). Run B3 showed raw 2 arriving. `uvc_callback_bridge.c` now
translates the setup packet for the non-primary (VS) shadow before invoking the
reference `CLASS` callback, using `a6400_uvc_ptp_translate_setup` (preserves the wIndex
entity-ID high byte, rewrites only the interface low byte), and logs
`[a6400_uvc] CLASS translated wire_iface=2 idx=0002 -> native idx=0001`.

- Module: `artifacts/native/uvc-transport-e0357-xlate/usbg_video_a6400_shared_candidate.ko`,
  **77,376 B**, SHA-256 `2be32cac7ec8429bd6f3e9a296e7a656e57b6107a100347bcd973e4ec1b5e06e`;
  transport audit `offline_module_audit_passed` (**117 checks / 8 skips / 0 failures**).
- Unicorn proof: new tool `tools/research/unicorn_uvc_ep0_select_e0357.py` against the
  new bridge object, with a fixture stub matching the real translation helper
  semantics: **selector 23/23, bridge 12/12** (including the three VS interface-2 cases
  asserting the reference sees `wIndex=1`), **reference-class 10/10**; receipt
  `artifacts/analysis/e0357-runb3/unicorn/unicorn-uvc-e0357.json`,
  `fixture_inputs_match=true`, exit 0.

## Remaining gaps (explicit)

- **Daemon park → battery pull:** on `stop attestation failed` the daemon freezes 181
  threads and stops; a recovery path (bounded unconfigure-first soft disconnect + hook
  retire with a degraded receipt) is required so a host-aborted session can return to
  MSC without a battery pull. Not implemented in this round (safety-sensitive call).
- **EP0 completion mechanism:** the trace proves the reply was not delivered but not
  *which* buffer/owner gadgetcore used. Next instrumentation: log the reference EP0
  buffer/queue arguments from the hardware callback path (or a gadgetcore completion
  hook) and test the translated build.
- UCX payload decoding: the provider is captured but not decodable to setup/status with
  the current tooling; a TMF/symbol-based decode or USBPcap would be needed.

## Next

Run B4 (only after explicit go-ahead): module `2be32cac…` + daemon `58ef8e35…`, same
ETW (UCX, armed through MSC switch), `--dmesg-sd`; check for
`CLASS translated wire_iface=2 idx=0002 -> native idx=0001` and whether a `SET_CUR`
follows the GET_CUR. Success = ffmpeg opens the pins or the log shows the exact
remaining EP0 completion point. If the daemon parks again, the recovery path above is
the next fix.

## Verification

Unicorn exit 0 (23/23, 12/12, 10/10); module audit 117/8/0; `A6400K.LOG` 6,613 B with
129 `[a6400_*]` lines and 0 errors; `A6400RCPT.JSON` complete. Camera touched under the
authorized protocol; one battery pull used as recovery; no flash/SD writes from the
host (read-only SD mount only). No GitHub push.


## Erratum (E0358, 2026-11-11)

Two claims in this record are corrected by the offline E0358 work:

1. The EP0 `queue` call made by `core_cb_class` does not target gadgetcore. The
   a6400 has no `usb_gadgetcore.ko`; `ep0->ops` is `dwc3_gadget_ep0_ops` and its queue
   slot resolves to **`dwc3_gadget_ep0_queue 0x602b2ad0` / `__dwc3_gadget_ep0_queue
   0x602b26ec`**. That UDC function returns 0 on several paths that arm no transfer,
   so "gadgetcore dropped the reply" is imprecise: the reply may never have been armed
   by the UDC. The E0358 module logs the live EP0/UDC state pre/post CLASS to decide.
2. The 181 TIDs were the publish-attestation scope and were resumed at publish
   (`publish_resume rc=0`); `freeze_tid_count=181` is a historical count, not a set
   frozen at park time. The battery pull was caused by the failed teardown + park
   (no re-enumeration), not by frozen threads. E0358 adds the bounded park-recovery
   path that flushes the SD evidence, retries STOP once, retires/resumes and closes.
