# Main-menu touch prototype

Current scope: six visible rows, one selection after a matching press/release, original camera hit/selection/refresh. Full option activation is not a prerequisite for this limited adapter. Physical selection is NOT enabled yet.

## Implemented policy core

`tools/native_camera/menu_touch_policy.{c,h}` is explicit new MOD logic, not an emulation of Sony navigation. It delegates position, hit, selection and refresh to bindings. No firmware addresses or cursor-memory writes occur in this core. It rejects unknown UI thread, inactive/changed MENU/page/generation, ambiguous hits, drags leaving the row, mismatched mouse/button, missing callbacks and failed selection. One release produces at most one selection; same highlighted row is a no-op.

Natural release calls now establish Appframework TID380 for six physical touches (E0128). Native bindings remain to be completed: current visible main-menu context and lifetime invalidation, original row/model methods, native row-focus handling and native visible refresh. Do not set an invented generation/thread ID merely to bypass guards. Do not bind only the empty PAS_MenuListTab mouse callback and expect touch to arrive: native routing excludes passive widget modes before that callback.

## Event contract

Original MouseEvent getters prove mouse byte0, button byte1, signed16 params+2/+4/+6, u32 type+8, time at+16. Native press builder6309e54 sets type5; release builder6309d48 clears button state and ultimately emits type6 when a target exists. These are DIFFERENT from queued postMouse* tags0/1/2. Params are not always coordinates: postMousePress/Release do not initialize x/y params. Original getMousePosInFramebuffer6309018 reads WidgetSystem+mouse*20+4a8/+4aa. Logger retains this coordinate before and after release, plus raw+4ac/+4ae, to validate release sentinel/timing behavior.

## Validation

-28 policy tests use explicit mocks and prove policy only.
-18 ORIGINAL ARM MouseEvent getter controls pass.
-C policy composed with48 ORIGINAL hit checks and5 ORIGINAL model row changes on retained V12 data passes; same-row/outside handling passes. Refresh is explicitly recorded only, not executed, in this composition test.
-599 project unittest tests pass.
-ARM policy object compiles; it is not a deployable camera hook by itself.

## Finite live trace, selection disabled

The camera kernel returnsEIO for PTRACE_GETHBPREGS index0; do not equate this with proof that the CPU lacks debugging hardware. Read-only idle stack candidates did not prove the UI thread. A narrow temporary RAM trace is therefore used at the original release consumer6309d48, BEFORE any assumption that the main menu receives a native widget mouse callback.

`menu_touch_trace.c` forwards to the EXACT original prologue/trampoline/body, preserves returned r0, and records up to24 natural release invocations. It does not link/invoke the selection policy. Five explicit instrumentation ABI tests use a consumer-body TEST DOUBLE; they prove argument/register/stack/result forwarding and logger bounds, NOT original release behavior. Six natural camera release invocations have now been captured; see E0128.

`native_menu_touch_trace_guard.c` supports check/install/remove, fixed exact-version addresses only. Original12-byte prologue must match; real libObj ELF must declare RX memory end700d708 and RW memory end7143920; actual mapped zero page padding is checked.408-byte code occupies previously zero RX padding,1184-byte state occupies previously zero RW padding. This avoids remote mmap/dlopen calls and does not register a boot hook. All PID149 CPU threads pause for guarded mutation; PC must avoid modified entry/payload. Code writes use PTRACE_POKETEXT. Rollback requires exact owned code/entry/state identity, no inflight call and clear PCs; it restores original entry and zero padding with readback.

Actual install/read/remove cycle passed on camera, all175 threads resumed. Final trace was installed for the user test, then archived and removed with entry/code/state restoration verified; all175 threads resumed. No hook is armed. Active record `artifacts/hardware/menu-touch-trace-active.json` preserves the exact payload needed for removal even if a later build changes. Capture is RAM-only and finite; after24 releases recording disables but the forwarding hook remains until removed. No cross-power-cycle behavior is claimed.

## Physical result (E0128)

Six natural releases all ran on Appframework TID380, mouse0/button0. Canonical framebuffer positions survive original release, while raw coordinates already read32767/32767. The exact trace/state were archived before verified removal. See [E0128](evidence/0128-natural-touch-ui-thread-and-release-coordinate-trace.md).

36 original hit checks with the observed points on retained V12 geometry yield rows1/1/3/3/5/5. The requested sequence was1/3/6 twice; live geometry/transform were not captured with these events. Do not infer scaling or user error. Physical selection remains disabled. Next validate contemporaneous geometry/transform, main-menu/popup/lifetime guards, then original selection and visible refresh.

## Current coupled result (E0130)

Read-only observer PID1673 completed and both outputs were archived before decoding. No observer or hook is armed. Current mouse position300,413 and actual MENU geometry were captured in the same CPU freeze. Original geometry/isHit resolves exactly row6. Separate original model selection1->6 succeeds in emulator copies; no physical selection is enabled.

Actual UI TID380 TLS and ListTab virtual refresh slot+1ac=15b92111 are now captured. Separate refresh replay progresses to a mutable global read709a38c and stops honestly. See [E0130](evidence/0130-coupled-touch-row-six-and-original-selection.md).

No new physical gesture is needed now. Remaining bindings must retrieve the current native menu/model, exclude inactive/popup contexts, invalidate stale lifetimes, and call original selection/visible refresh on UI thread380.

## Native binding implementation (E0131)

`menu_touch_native.{c,h}` now connects policy callbacks to original registry, position, hit, selected-index/indexed-child, selection, binding and refresh methods. The module is built for offline execution and has not been installed. Original popup flag/state guards are derived; six compiled negative controls return correctly. The positive active-menu control stops at an uncaptured outer parent-tree sentinel, with no invented parent data.

Refresh requires two arguments: the original controller supplies0 for resourceA056F604. Both binding and refresh harness now preserve this ABI. Real lifetime invalidation and final consumer integration remain. See [E0131](evidence/0131-native-bindings-popup-guards-and-refresh-argument.md).
