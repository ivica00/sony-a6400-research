# E0127 — Touch selection core, native event ABI and live forwarding trace

Date2026-11-06. User says continue the limited touch-to-row prototype. Full physical selection is not yet implemented/enabled. See docs/MAIN_MENU_TOUCH_PROTOTYPE.md for contracts and recovery.

## Work delivered

New C policy menu_touch_policy.{c,h}, host harness,28 meaningful policy tests. Cross-compiled ARM object.599 total unittest tests pass. Original getter probe18 controls and native-hit/selection composition48 hit checks/5 actual original row changes pass on retained V12 data; the latter records refresh request only. No host-drawn highlight or direct model-selection write substitutes for original firmware. Live UI bindings remain unvalidated.

Camera/file-equal WidgetSystem input component6308000/4000 captured, plus InputService touch/raw callbacks. Identified dispatcher6309118 (r0system,r1target,r2MouseEvent); original calls +6c mouse hook or+68 mouse handler. Private press6309e54 sets button state and builds UI event5; private release6309d48 clears it and builds6. Public transport tags0/1/2 are not UI event tags. UI MouseEvent params are not reliably x/y; native framebuffer coordinate getter reads system+mouse*20+4a8/+4aa. Type/field getter contracts are ORIGINAL ARM execution, not guessed C layout.

Hardware-breakpoint capability request29/index0 on tid149 returned-1/errno5; no debug registers were written.175 resumed1479ms/END0.11 selected read-only stack samples (all175 threads paused/resumed1479ms) yielded no primary WidgetSystem input-frame candidates; no UI-origin thread ID claimed from this. TID149 in host fixtures is explicit, not a discovered live UI identity.

## New deliberate RAM instrumentation scope

Earlier snapshots were read-only. This round introduces a temporary forwarding-only RAM hook for the explicitly requested touch prototype. The helper does not remotely invoke application functions; natural original release calls go through a tested trampoline. No selection policy is linked into the payload. No SD/boot/preload modifications. Own helpers/request files uploaded under/setting.

Actual ELF RX/RW segment ends and mapped zero tails verified:700d708..700e000 (2296 bytes),7143920..7144000 (1760 bytes). Original release prefix `2de9f04788b04ff014080122` is12 complete Thumb bytes with no PC-relative instructions. Trampoline replays those exact instructions and jumps to6309d55. Payload entry700d709/408bytes, SHAd4a8473935238f199e50d50c47e698cfb8efe701c88d476c4e429080ac288f83. State1184bytes/capacity24. Original body is NOT emulated by the live payload.

Five isolated instrumentation tests explicitly replace consumer BODY with a deterministic test double, proving forwarding once, original result, callee-saved registers, stack alignment/restoration, no application-state writes, disabled/invalid context and before/after coordinate capture. These are not firmware compatibility or hardware-execution claims.

Guarded dry-run op0 passed; then install/read/remove cycle passed: install175resumed1413ms, removal175resumed1317ms, entry/code/state restoration readback. Initial trace count0, no natural release body exercised by this cycle. Successful END result0 is authoritative; errno17 in success receipt is stale, not operation failure.

## Pending user physical trace

Final installation: menu-touch-trace-install-20261106-195337.json, all175 resumed1266ms/result0. Read195340 confirms hook bytes `dff800f009d7000700bf00bf`, magic/version/enable1/count0/inflight0/cap24/error0/system956f0. Active recovery metadata/payload copy: `artifacts/hardware/menu-touch-trace-active.json`. Compile manifest's deployed:false describes its build stage; active record/live hook_installed:true describes CURRENT installation.

User unplugUSB/no poweroff/openMENU/tap center rows1,3,6 twice each about1s gaps/reconnect. This is logging only; selection remains disabled. FIRST `python -m tools.research.menu_touch_trace_control read`, then `... remove`, preserving state/committed events and restoring original bytes BEFORE other camera work. Ring stops after24 events; hook still forwards until removed. No separate long-running snapshot observer is armed. Capture successful removal receipt and all threads resumed; never fake inflight0 or force return to bypass a busy removal.

Trace records actual TID, mouse/button, canonical framebuffer before/after release, raw coordinates, final button state, opaque original clock and returned r0/transport tag. Native result is opaque, not proof of selection. Before physical trace arrives, UI-thread origin, release coordinates and visible refresh are NOT proven. Next: bind policy to validated original coordinates/hit/model/native refresh and current-main-menu lifetime guard. Original private activation resource exploration remains preserved but is not the prerequisite for the minimal prototype.
