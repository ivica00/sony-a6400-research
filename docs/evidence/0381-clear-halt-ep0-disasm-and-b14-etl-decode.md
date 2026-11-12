# E0381 — Synthesis: `clear_halt_ep0` cannot re-arm EP0; the 5 s gap is the GET_CUR URB itself; GET status completion is the missing event; SET_CUR then cancels

Date: 2026-11-12. Offline synthesis of two subagent reports:
[E0381 kernel disasm](artifacts/analysis/e0381-kernel-disasm/e0381-clearhalt-and-eventbatch.md) and
[E0381 ETL decode](artifacts/analysis/e0381-etl-decode/timeline.md).

## 1. `clear_halt_ep0 0x602b8f70` (class return 0 path `0x602ba3f4`)

- Exact function: `mov r3,#0; strb r3,[r0,#0x83]; mov r0,r3; return 0` (0x1c
  bytes, no BL/BLX, no MMIO, no TRB, no DEPCMD).
- `r0` at the call site is the **gadgetcore context** `gc` (setup_req's r4;
  `g_bind` stores `dev_get_drvdata(gadget+0x30)` = `gc`, vmlinux `.data` slot
  `0x6051b17c`), **not** usbg_video `this_ex`. `gc+0x83` is a software EP0-halt
  flag; the only writer is this clear (writes 0), the only reader is
  `ep_ctrl_get_ep0_halt 0x602ba9f4` (used by GET_DESCRIPTOR/CONFIG/INTERFACE/STATUS),
  and there is no set-to-1 path in vmlinux or the reference module. The flag is
  always 0.
- The class-return-0 range `0x602ba3f0..0x602ba428` has exactly one BL
  (`clear_halt_ep0`); there is no reachability to
  `dwc3_ep0_stall_and_restart`, `out_start`, `set_halt` or `start_trans`.
  **Class return 0 cannot stall/restart/re-arm dep0; it is not the cause.**
  The 26-byte data arm happens earlier inside `core_cb_class → ep0->ops->queue →
  __dwc3_gadget_ep0_queue 0x26ec → do_control_data 0x25c8 → start_trans 0x2424`.

## 2. DWC3 event-buffer loop (inlined in `dwc3_thread_interrupt 0x602b1378..0x191b`)

- The requested range `0x602afd00..0x602b0200` contains no event-buffer code
  (it is set_link_state/wakeup/giveback/EPCMD). `dwc3_process_event_buf/entry` and
  `dwc3_interrupt` are static/inlined; event processing is inside
  `dwc3_thread_interrupt`.
- At batch start, `evt->count` is a **snapshot** of GEVNTCOUNT
  (`readl(regs+0x30c+0x10*i) & 0xfffc`); `lpos` is the current event, advanced +4
  after each entry (masked 20 bits), with a `writel(4)` ack per entry.
  `evt->lpos` is the currently executing event inside the callback.
- A `cnt=0xc` batch is a delayed-queue snapshot; it can contain completions of
  transfers armed earlier, because count is not per-arm accounting. The kernel report
  resolves B12 batches to `{0x294,0x298,0x29c}`, `{0x2a0,0x2a4,0x2a8}`,
  `{0x2ac,0x2b0}` and the arms: `0x2a0 ← do_control_status 0x25a4` (NRDY STATUS
  path), `0x2a4 ← out_start 0x2b68`, `0x2ac ← ep0 OUT XferComplete after the class
  data arm` — while the single reused `ep0_trb [dwc+4]` at giveback still had
  `HWO=1`. `dwc3_ep0_complete_data` (`0x30a8..0x3348`) **never checks HWO/ownership**
  before giveback at `0x3344`.
- Unresolved contradiction flagged by the kernel report: the batch arithmetic puts
  `0x2a4` (SETUP completion) in a 12-byte batch before the only `out_start` that can
  arm the SETUP TRB (which runs while processing `0x2a0` inside that same batch).
  This is not yet explained; do not build a re-arm/retry/queue-filter fix on it.

## 3. Host ETL (B14, 676 MB): the 5 s gap is GET_CUR itself

`tracerpt` decode of the Sony `054C:0322` (UCX usbdev `0x5973C4452398`, SlotId 15)
gives **exactly five control URBs in the whole 229 s capture**:

| # | host t (s) | dur (s) | setup | result |
|---|---|---|---|---|
| 1 | 6.090881 | **5.010962** | IN A1 81 0100 0002 001A (GET_CUR VS_PROBE) | 0x0 SUCCESS, 26 B |
| 2 | 11.101860 (+17 µs after #1) | **5.009888** | OUT 21 01 0100 0002 001A (SET_CUR) | 0xC0010000 CANCELED |
| 3 | 16.112018 | 0.0023 | IN GET_CUR retry | 0xC0000011 XACT_ERROR |
| 4 | 17.205187 | 0.0023 | IN A1 67 0000 0000 0024 | 0xC0000011 XACT_ERROR |
| 5 | 18.218047 | 0.0025 | OUT 21 66 0000 0000 0000 (0-length, after SET_CUR) | 0xC0000011 XACT_ERROR |

- There is **no host control request between GET_CUR and SET_CUR**; the 5.000 s
  “gap” is the GET_CUR URB itself, pending 5.010962 s and then SUCCESS with the
  correct 26-byte payload. SET_CUR is submitted 17 µs after that completion and then
  hangs 5.0099 s until canceled. No `USBD_STATUS_TIMEOUT`; the ~5 s is the Windows
  control-transfer timeout boundary plus ~10 ms overhead.
- **No SET_INTERFACE/SET_CONFIGURATION/0-length request before SET_CUR** in the
  control-transfer stream; the only 0-length control is #5 after SET_CUR. Caveat:
  UCX emits no `URB_FUNCTION_SELECT_*` records at all, so that absence is partly a
  trace limitation; the camera log has no `core_cb_start` in the window anyway.
- Timebase: `camera_uptime = host_t + 134.5815 s` (two URB↔CLASS anchors agree within
  41 µs; teardown cross-check 17 ms). Host GET completion at 11.1019 s = camera
  145.6834 s = **SET pre**; device GET data completion was logged at 140.677 s
  (host 6.0955 s). So the device had completed the data stage ~5 s before the host
  URB completed.
- The ETL does **not** support the ctrl_req-overwrite premise: no host 0-length
  standard transfer exists in the window, and GET returned its 26 bytes correctly.

## 4. Synthesis / what is now established

1. `clear_halt_ep0`/class-return-0 is not the re-arm cause (§1).
2. The hardware/software arm accounting cannot by itself explain `0x2a4` in the same
   batch as `0x2a0`; that contradiction is open (§2).
3. **Host-side, the actual 5 s failure is the GET_CUR URB**: the host waits ~5.01 s
   for GET_CUR to complete (then success), and SET_CUR is submitted immediately and
   canceled after another ~5.01 s. There is no separate host request to blame.
4. Device-side, GET data completes at 140.677 s but the host URB only completes at
   145.683 s → the **GET_CUR status stage (or its event processing) did not satisfy
   the host until the timeout boundary**. That is now the primary target, not the
   `0x2a4/0x2a8/0x2ac` stale-TRB hypothesis.
5. SET_CUR’s `actual=0`/HWO=1 happens because the SET completion is processed by
   `complete_data` (state=2, next=3 at giveback — the status path `0x334c` would have
   been entered only with ep0state=3), and complete_data lacks HWO/ownership checks.

## 5. Next (no hardware/build yet)

Build read-only `e0381-roprobe` with:
- `ev = *([dwc+0xcc])` double-dereference; verify `dwc->regs` + `0xc30c` against the
  working e0372 build; log `evt->lpos`, `evt->count`, `GEVNTCOUNT0`, and the raw
  `byte0/byte1` of the 6 words around lpos;
- completion caller LR (`0x602b3344` vs `0x602b3364`) and `ep0state/flags/next` at
  GET pre/queue/complete and the status events;
- no ops shadows, no `lr` filtering, no status kicks, no gcguard/drain.

Success criterion: identify whether GET_CUR’s status NRDY (`0x20c0`) was processed and
whether `do_control_status` armed/completed the status TRB promptly, or whether the
IRQ thread/event loop stalled for ~5 s; then propose the minimal fix (status stage),
verify in Unicorn, and only then a hardware run.
