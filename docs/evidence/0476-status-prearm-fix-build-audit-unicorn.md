# E0476 — Status pre-arm fix implemented in the bridge; build + static audit + Unicorn verification PASS (no camera action)

Date: 2026-11-13. **Strictly offline**: no camera session, no USB, no module load.
Scope: implement the E0469 root-cause fix (pre-arm the EP0 OUT status TRB at class
data-stage completion), rebuild, static-audit, and verify in Unicorn, including single-arm
idempotency, `ep0state=3` ordering, status-completion dispatch to `0x334c`, and the
B10 NULL-deref regression. Run B26 is **not** started; explicit user GO still required.

## 1. Change (only `tools/native_camera/uvc_callback_bridge.c`)

New `a6400_uvc_status_prearm(ep, req)`, called from `a6400_uvc_ring_complete_thunk`
before the original completion callback (gcc inlines it into the thunk):

* gate: only for a class **IN** 3-stage request (`bRequestType IN`, `wLength != 0`) whose
  queued request pointer matches (`g_prearm_active` set in `class_cb`, `g_prearm_req`
  captured by `ring_queue_wrap`), pending cleared after one attempt;
* refusal guard: `req->status != 0` (setup-pending / error giveback) arms nothing;
* state guard: only when `dwc->ep0state == 2 && dwc->ep0_next_event == 3` and
  `dwc->eps[0]` looks like a kernel pointer;
* ordering: **writes `dwc->ep0state = 3` first**, then calls the kernel's
  `__dwc3_ep0_do_control_status(dwc, dwc->eps[0])` at VA `0x602b253c` (retained-vmlinux
  address; the kernel's own NRDY(STATUS) handler order at `0x3448..0x3458`);
* counters + bounded evidence: `PREARM st=%u nx=%u r=%u` (r=1 armed / 0 skipped),
  `PREARM skip st=%u nx=%u`, and the STOP `RAMRING` line gains
  `prearm=attempts/armed/skipped st=last_state nx=last_next`.
* Late `XferNotReady(STATUS)` is then ignored by the kernel (`next==1`), and
  `start_trans`'s BUSY guard prevents a double TRB; no descriptor/composite change.

## 2. Build (unmodified tooling through the E0455 WSL executor bridge, 21 bridged commands)

| item | value |
| --- | --- |
| module | `artifacts/native/uvc-transport-e0472-status-prearm/usbg_video_a6400_shared_candidate.ko` |
| size / sha256 | **83,644 B** / **`dcc2f64f944790dd1b8519b29ee6f6ce709a03129fb92d363fdafe14f16915cd`** |
| flags | `--shared-ptp-enumeration-candidate --composite-transport` (same as B25) |
| bridge source | 56,817 B, sha256 `b509b0e7ce1329f1c68373051f9296be271fe15149395d125f12502034ca3e56` |
| bridge object | sha256 `f4cca4613c276c6b2b515a260d8037727b632a1abbc323e7edadb0f79a8aba12` |
| undefined symbols | **56 / 56 verified** against retained kernel/module evidence |

## 3. Static audit

`tools/research/audit_uvc_ptp_module.py` (`--prepare-only` + direct-WSL gcc/ld +
`--linked-elf`, guard fixture compiled 1,072 B, linked ELF 81,432 B):
**`offline_module_audit_passed`**, mode `transport`, **count 117**, **`failures: []`**
(8 enumeration-only checks recorded as skipped, as before).
Manifest: `artifacts/analysis/uvc-transport-e0472-status-prearm-audit/manifest.json`.

## 4. Unicorn verification (executes the rebuilt bridge object)

Harness: `artifacts/analysis/e0472-status-prearm-unicorn/e0472-status-prearm-unicorn.py`
(report `e0472-status-prearm-unicorn.json`). The module `.text`/`.data`/`.bss` are relocated
(132 relocations applied, 0 skipped) and executed; undefined kernel symbols are stubs; the
kernel-side snippets (NRDY(STATUS) arm handler `0x3448..0x34b0`, XferComplete dispatch
`0x2cd4`/`0x334c`) are hand-assembled **model stubs** labelled from the E0469/E0366
disassembly. **All 8 checks PASS:**

| check | evidence |
| --- | --- |
| A order/arm | ep0state write `3` at seq 160 **before** native call at seq 166 with `r0=0x61000000` (dwc), `r1=0x61100000` (eps0); after: ep0state=3, next=1, attempts=1, armed=1, pending=0 |
| A single arm | second completion thunk call → no extra native call (1 total) |
| B thunk integration | real `a6400_uvc_ring_complete_thunk` arms once, same ordering |
| C late NRDY | after pre-arm (`next=1`) the NRDY path arms **0** times, state stays 3 |
| D NRDY control | without pre-arm (`next=3`) the NRDY path arms exactly once (model sanity) |
| E dispatch | ep0state=3 → **status path `0x334c`** marker, ep0state→1; ep0state=2 → DATA path marker (B10 hazard) |
| F standard request | no pending class request → 0 calls, 0 ep0state writes |
| G guard skip | state=1/next=1 → 0 calls, 0 writes, skipped+1 |
| H error giveback | `req->status=-22` → 0 calls, 0 writes, skipped+1 |

## 5. Tests

* New `tests/emulator/test_status_prearm.py` — **13 tests OK** (ordering model, only
  `(2,3)` arms, late-NRDY ignored, dispatch/B10 regression, thunk gating, error-status
  guard, and source-contract checks that the `ep0state=3` write precedes the `0x602b253c`
  call and that the class-IN gate/guards are present).
* Full suite `python -m unittest discover -s tests -q`: **Ran 1576 tests in 29.790 s — OK**
  (`artifacts/analysis/e0472-status-prearm-unicorn/full-suite.log`).

## 6. Boundaries / what remains unverified

* No live behavior is claimed: the only proof is static + Unicorn + suite. Whether the
  pre-arm actually removes the host's 5 s timeout needs **one** supervised Run B26.
* Residual risk: if the host's first Status OUT still arrives before the pre-arm (the
  window measured in B25 was only bounded to <16.388 ms by the 10 ms OBS sampling), the
  stall would persist and E0469 H2 (host/controller does not re-drive the NAKed status
  stage) would be confirmed; the B26 SD/ring evidence would then show `PREARM … r=1` and
  no status completion, which cleanly separates the two hypotheses.
* Evidence to read in B26: `PREARM st=2 nx=3 r=1` before the GET_CUR status completion,
  `RAMRING … prearm=1/1/0 st=2 nx=3`, and the ETL GET_CUR URB duration (expected ≪5 s if
  the fix works).
* No camera action, no module load, no flash/SD change in this round; Run B26 remains
  gated on the user's explicit GO.
