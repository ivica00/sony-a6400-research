# E0250 — Original unconfigure ends in a no-op gadget ioctl; the module's direct pullup is the suspect

Date: 2026-11-09. Offline only: no camera access, no module load.

## Resolved vtable

From `dwc3_gadget_ops` at `0x603dfbf0` (pinned kernel SHA-256 `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707`):

| Offset | Entry |
| --- | --- |
| `+0x14` (index 5) | `dwc3_gadget_pullup` `0x602b1d3c` — the module's `pullup_target` check |
| `+0x18` (index 6) | `dwc3_gadget_ioctl` `0x602afcd8` |
| `+0x20` (index 8) | `dwc3_gadget_start` |
| `+0x24` (index 9) | `dwc3_gadget_stop` |

## What the original clear-configuration does

Disassembly of `0x602b90cc` and a new probe (`tools/research/probe_uvc_ptp_unconfigure_ioctl.py`) show:

1. Configuration 0 returns immediately.
2. It looks up the current tree, prepares stop, calls original interface stop `0x602b8f8c` for interfaces 0/1/2, and clears configuration/alternate bytes at `gc+0x74`/`gc+0x82`.
3. It then loads `gadget->ops+0x18` and calls `dwc3_gadget_ioctl(gadget, 1, 0)`.
4. For code 1 (and 2/3) the original ioctl returns **0 without touching the UDC**; code 0 and code 4 with param > 5 return `-0x203`. There is **no pullup(0) and no hardware reset** in the unconfigure body.

Probe result: 9 vtable/flow checks and 5 ioctl cases pass; manifest `artifacts/analysis/uvc-ptp-unconfigure-ioctl-e0250/manifest.json`.

## Consequence for the P4b hang

The module's `uvc_ptp_session_end` calls `ops.quiesce`, and the native backend's `quiesce` performs **`pullup(gc, 0)` directly** (E0184's unbounded busy wait) *before* the session's bridge/interface consumers are quiesced and *before* the original interface stops. The original teardown instead stops interfaces 0/1/2 and clears configuration, leaving the UDC pullup to the later mode switch.

Revised hypothesis: during a configured session the original PTP (and possibly UVC) interface is still active with pending host requests when the module pulls the UDC down; the DWC busy object cannot clear, so `pullup(0)` waits far beyond the session and the camera never returns to Mass Storage. This is consistent with the children disappearing at ~118 s and the later descriptor-request-failed state.

## Fix candidates (to be probe-backed before any build)

- **A. Unconfigure-first:** call the original clear-configuration (`0x602b90cc`) after stopping the module's own callbacks and before `pullup(0)`, so the original PTP/UVC interface stops and config clear happen first.
- **B. Interface-stop-before-pullup:** invoke the original interface stop for interface 0 (PTP) and the session's UVC interface, drain in-flight state, then pullup.
- **C. No custom pullup:** stop the module's consumers, restore the original descriptors/config, and leave the UDC stop to the original mode switch; only fall back to `pullup(0)` if the mode switch cannot proceed.

All candidates must preserve the no-forced-unload/no-timeout-cancel rules and be validated with call-order fixtures before a module build.

## Limits

Control-flow proof only; the DWC busy-bit producer and the real interface callbacks remain service fixtures. The session's exact in-flight state at STOP is unknown because the P4b receipt was lost. This record does not claim the revised hypothesis is confirmed.

## Next

F2: probe/fixture the candidate ordering (unconfigure-first vs interface-stop-first) against the session teardown state, then implement the chosen order behind an opt-in flag with ARM audit.
