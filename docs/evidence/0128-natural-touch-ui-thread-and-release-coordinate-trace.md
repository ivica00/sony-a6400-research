# E0128: Natural touch UI thread and release coordinates

Physical callback, 2026-11-06. Selection remained disabled throughout. The finite
E0127 forwarding logger observed six natural release-consumer calls. BOTH the
decoded receipt and exact 1184-byte state were archived before removing the hook:

- `artifacts/hardware/menu-touch-trace-read-20261106-195941.json`
- `artifacts/hardware/menu-touch-trace-read-20261106-195941.state.bin`
- `artifacts/hardware/menu-touch-trace-remove-20261106-195942.json`

## Verified outcome and cleanup

All six committed records have TID **380 (Appframework)**, WidgetSystem `0x956f0`,
mouse/button 0, queued transport tag 2. Header count6/inflight0/error0/capacity24.
This establishes the natural release consumer's thread for these touches. It
does not establish that every camera UI operation belongs to that thread. The
old explicit TID149 offline controls remain controls, not physical UI provenance.

| Release | Framebuffer position, before AND after original consumer | Raw position after |
| --- | --- | --- |
| 1 | 293,163 | 32767,32767 |
| 2 | 333,148 | 32767,32767 |
| 3 | 328,259 | 32767,32767 |
| 4 | 328,253 | 32767,32767 |
| 5 | 343,345 | 32767,32767 |
| 6 | 343,343 | 32767,32767 |

Canonical `WidgetSystem+mouse*20+0x4a8/+0x4aa` coordinates survive release; raw
`+0x4ac/+0x4ae` already contain the sentinel. Do not use raw release coordinates
or uninitialized press/release event parameters as the hit point. Button state
after original release is zero. Original r0 is zero in every record; its meaning
is opaque here and does NOT indicate selection success. Clock units are not
derived from these raw values.

Guarded removal returned `REMOVED ... code_restored=1 state_restored=1`, END
result0/op2, all175 CPU threads resumed (1242ms). Original twelve-byte entry,
owned RX payload padding and RW state were restored and readback-verified.
`menu-touch-trace-active.json` now says installed:false/removed:true. **No hook or
snapshot observer is armed.** Own helper files remain inert in `/setting`; no
boot/preload/SD change was made. Successful receipt errno17 is stale errno,
not a failure when result0 and verified restoration are present.

## Retained-geometry control and unresolved mapping

`python -m tools.research.menu_touch_trace_hit_probe` executes 36 original ARM
row-hit checks on retained V12 PID1175 geometry using these observed points.
Report: `artifacts/analysis/menu-touch-trace-hit-e0128.json`.

Results are rows **1,1,3,3,5,5**, with exactly one hit per point. The requested
physical sequence was rows1/3/6 twice. Do not invent scaling, infer user error,
or claim a contemporaneous row6 hit: V12 geometry was captured earlier, and
native framebuffer-to-widget transformation during this test was not logged.
The probe explicitly reports contemporaneous_geometry_proven:false and
live_selection_enabled:false. Geometry-cache writes happen only in emulator
copies. No selection or refresh is invoked by this probe.

Next binding work must validate the current menu/row geometry and native input
transform on the natural UI thread, plus exclude inactive/popup contexts and
invalidate stale menu/page lifetimes. Then connect original selection and visible
refresh. A fabricated generation or direct cursor write would not resolve those
contracts. Full popup activation remains unnecessary for the limited row tap mod.
