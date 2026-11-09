# E0131: Native bindings, popup guards and refresh ABI

No observer/hook is armed. No new application call or RAM patch was made on the
camera. The native bindings below are built for offline checks, NOT deployed.

## Popup and main-menu state evidence

Live/file-equal PAS_MenuPopup open15b8cd44/close15b8b158 show the open flag:
setter15b8b14a stores byte+648e; getter15b8b258 reads it. Open sets1, close clears0.
Artifacts `native-popup-open-close-e0131.json` and
`native-popup-state-accessors-e0131.json` retain code/disassembly.

The embedded PAS_MenuListPopup has its OWN corresponding methods in the existing
source-equal ListTab component: open15b96e20 calls setter15b95a56(1), close15b95a64
calls it with0, and getter15b95b60 reads byte+648e. Activation15b92044 passes
menu+fb20 as that popup. Thus its actual flag is menu+15fae; the E0130 coupled
main-menu snapshot has flag0/model0. This is not inferred from widget presence:
the closed popup object is already present in the native tree.

After successful embedded popup open, original activation sets menu+1e0 to3 via
15b90520. Captured main menu has state2. Original predicate15b90534 returns
whether state==2; 15b90548 tests3. These support exclusion of this option-list
path. They do NOT yet prove exclusion of every camera overlay.

Original Widget::setMode63054cc stores the mode byte and, for mode3, calls the
visibility slot withfalse and updates Element visibility. Original inherited-mode
helper631e814 traverses native parents and returns the maximum mode. Its actual
512-byte live/file-equal code window is
`native-widget-ancestor-mode-e0131.json`. The binding also requires this native
ancestor check rather than relying solely on the menu's own mode2.

## Implemented native binding module

`tools/native_camera/menu_touch_native.{c,h}` now supplies the policy callbacks:

- current menu through ORIGINAL lookup62e27de with IDs AADCA2C7/DFDC8DDD/A056F604;
- original state/popup/ancestor predicates; row-focus-only restriction;
- current page via original selected-index16925c16 + indexed child16925bc6,
  twice from actual provider, with count/type/index checks;
- canonical mouse position6309018, ORIGINAL float-point isHit6305080;
- original row setter169260da, binding15b91430 and refresh15b92110.

The regular getSelectedItem16925bd2 NORMALIZES and stores selected+18 even when
the value is unchanged. Initial offline write guards caught that; the context
resolver now uses original read-only selected-index/indexed-child methods. No
application-memory write is allowed by the context-control harness.

UI identity is obtained by real gettid in the compiled module, requires380.
Module rejects unknown/zero epoch and revalidates menu/page/row/generation for
callbacks. It does not manufacture lifetime tokens. The caller MUST supply an
epoch driven by verified lifetime/transition instrumentation; this caller is
not implemented/installed yet. Constant7 in tests is an EXPLICIT test token,
and the Unicorn gettid224 reply is an explicit kernel-contract fixture.

Build: `python -m tools.research.build_menu_touch_native`. ARMv7 Thumb,
VFPv3-D16/softfp, freestanding, no unresolved runtime helpers. ELF is an OFFLINE
module, not an installable payload; no claims that the final combined hook fits
the existing code padding. Deployment must recheck every exact-version contract.

## Refresh requires its second argument

Refresh15b92110 saves r1 and passes it into per-row refresh15b91a80/15b91890.
It is NOT a one-argument method. Original ViewSettingMenu at157edd56 loads
resource literalA056F604, gets/casts that widget, then at157edd86 explicitly
sets r1=0 before virtual+1ac. The source-equal live window and literal are saved
in `native-controller-refresh-zero-e0131.json`.

The binding now calls refresh(menu,0), and the separate refresh harness also
sets r1=0 explicitly. Earlier refresh-only controls inherited an unrelated r1
from selected-node traversal: that was not a validated refresh argument. They
stopped before this argument's downstream use and must not be cited as complete
refresh ABI tests. Corrected replay still stops1419 at mutable global709a38c,
without claiming refresh returned or visible feedback.

## Compiled context controls and precise remaining gap

`python -m tools.research.menu_touch_native_context_probe` executes the compiled
MOD context module plus ORIGINAL lookup/model/popup/state methods over E0130
coupled data. Six negative controls return0 correctly: popup open, state3,
header focus, cached-row mismatch, epoch0, wrong thread. Popup/state fixtures use
the ORIGINAL setters in emulator copies; header/cache fixtures are explicit
negative inputs. Report `menu-touch-native-context-e0131.json`.

Positive main-menu control reaches the original inherited-parent traversal and
stops BEFORE reading uncaptured12a16c at PC64c6a06 (r0=12a160). The coupled
snapshot captured widget geometry but omitted this outer layer tree sentinel.
No null parent or successful return was invented; the report marks it incomplete.
Do not describe these as seven passing controls or a live active-menu proof.

`native_touch_geometry.c` is now extended to capture the source-derived bounded
parent-node chain (including outer sentinel), plus mutable refresh-global709a38c
in the same CPU freeze. Revised ARM build passes. This revised binary is NOT
uploaded or armed; the inert on-camera helper is the earlier completed version.
No further physical action has been requested in this step.

Next: finish native lifetime invalidation and instrumented consumer integration;
verify combined forwarding/register/cache/rollback contracts before installation.
The unified original queued mouse dispatcher6309074 is a candidate for one
press/move/release integration point; its prefix contains PC-relative code,
so copying its prologue verbatim is unsafe. Widget destructor6305568 has a similar
literal issue. Mode setter63054cc and menu-state setter15b90520 are additional
candidate invalidation sites, not armed or claimed complete coverage.

Limited row touch still requires no full popup activation. Physical selection
remains disabled; visible refresh and complete lifetime/overlay guards remain
unproven. Last full regression599 passed at E0130; new native build and six
compiled negative controls pass separately here.
