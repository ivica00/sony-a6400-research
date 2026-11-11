# E0338 — Console log sink, message-teardown boundary, and the /dev/usb/event map

Date: 2026-11-11 (continuation of E0337). Emulator-only: no camera access, no
camera write, no USB mode change, no GitHub push.

## 1. /dev/tty console log sink (new)

e0687 stopped at `open("/dev/tty", flags 0x902 = O_RDWR|O_NOCTTY|O_NONBLOCK)`.
New opt-in `--tty-device log-sink` (`src/a6400/execution/guest_tty.py`):

- serves the observed flag subset only (0x902), returns an fd; write serves
  bounded guest buffers, writev gathers ≤16 iovecs and ≤64 KiB, and records the
  text; read/ioctl are explicit `unsupported_tty_contract` boundaries;
- default `--tty-device stop` is unchanged.

Observed: e0688 served the open and a writev (7 iovecs, 80 bytes); e0690 also
persisted the log in the report, capturing the original glibc abort message:

```
*** glibc detected *** /usr/bin/im.elf: free(): invalid pointer: 0x5046FFD4 ***
```

## 2. Message teardown boundary (new)

- `0x5046FFD4 = injected ObjMsg + 0x68` — the **in-image ParamMap array**
  (`array*` field of the map at body+0xC); `ParamMap::Clear` frees it during the
  original `~ObjMsg` teardown (agent 182's documented risk).
- Moved Param and the ParamMap array to guest OSAL allocations (E0338 run
  e0691): the invalid free moved to `0x5043164C` — the **Param payload**; the
  teardown deletes the parameter with libc `free`/`operator delete`, so an OSAL
  fblock pointer is not a valid libc allocation.
- A labelled libc-free suppression hook was implemented and tested (e0692-
  e0694) but caused an earlier execution fault (0x5368298E) because returning
  from free() changes caller-saved state; it is **disabled by default**.
- Boundary: **`mwf_message_teardown_allocation_unmodelled`** — to continue past
  the original teardown, the injected ObjMsg/ParamMap/Param must be allocated
  the way the original code allocates them (guest libc heap), or teardown must
  be modelled explicitly. The dispatch/notify work itself (event 0x13 and the
  0x0A4002 broadcast, E0337) happens before this boundary.

## 3. /dev/usb/event bridge subtype map (agent task-189)

`artifacts/analysis/e0338-usb-event-subtype-map.md/json` decodes the reader and
the bridge tables in live libInfraUsbCmn/libUsbControl:

- reader (libInfraUsbCmn 0xC464) validates record+0 context against its
  registry and calls `record.callback(context, subtype, payload_len, payload+12)`;
  the e0673 state accepts only context **0x30CE8** (E0311's 0x2E878 record would
  be dropped).
- bridge selector (libUsbControl 0x12E54): sel 1→0x0A6001, sel 2→0x0A6003,
  **sel 4→0x0A4001 (param 0x1006=int32 arg0)**, sel 6→0x0A4008, sel 8→0x0A4007,
  sel 9→0x0A6000 (0x1002/0x1003), sel 10→0x0A6002 (0x1004), sel 12→0x0A6004,
  sel 13→0x0A6005; sink = EventListner → SendEvt → `osal_snd_sync_msg(0x00CA8192)`.
- class/subtype: OTG 0..7 → events 0..7 → only 0x0A6000/1/3; **gadget subtype 0
  → event 8 → sel 4 → 0x0A4001** (only producer of event 8); gadget 3/4 →
  0x0A4007/8; host connect → 0x0A6002.
- **0x0A4001 is explicitly absent from /dev/usb/event in the e0673 state**: the
  gadget class is not registered/enabled (`CUsbSvc+0x9C=-1`, `+0xC0=0`,
  `+0x114=-1`), matching the E0331 `gadget_event_context_not_enabled` boundary.
- 0x0A4000 is not from /dev/usb/event: handler 0x13054 builds it from the kernel
  OSAL-queue callback 0x131A4 on queue 0x00E942CD (registered in doInitialize).
- state-valid sync-lane rehearsal record for the OTG class:
  `e80c0300ddb02f560200e80c` (context 0x30CE8, callback 0x562FB0DD, subtype 2 →
  event 2 → sel 1 → 0x0A6001); a second mirror record reproduces E0311.

## 4. Status

The emulator preparation is complete for everything reachable with current
evidence: host enumeration module, Param/guest-allocation, SETCONFIG → event 0x13
→ 0x0A4002 broadcast, console log sink, usbg_video gap decoders, overlay hygiene,
PTP hardening. Two boundaries remain for a physical-producer-faithful SETCONFIG:

1. **`gadget_event_context_not_enabled`** — 0x0A4001 requires gadget-class
   registration/port state that does not exist in the retained state (no
   fabricated registration).
2. **`mwf_message_teardown_allocation_unmodelled`** — libc-heap allocation or a
   teardown model for the injected message objects.

Full suite: **1181 tests OK**. No camera write/USB mode change; changes are
local (no GitHub push).
