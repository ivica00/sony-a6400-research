# E0352 — Teardown root cause and clean soft-disconnect fix (offline, Unicorn-proven)

Date: 2026-11-11. **Offline only**: source analysis, disassembly and Unicorn. No camera, no
module load, no USB mode change. Follow-up to E0350 ("Device unknown" in MSC after each Track B
session, recoverable only by battery pull, receipts lost with `/tmp_bt`).

## Claim

1. **Root cause (ranked):**
   - **H1 — the transport build dropped the unconfigure-first order.** The E0350 artifact's
     `a6400_uvc_ptp_session_end` loads only `ops.quiesce` (`[s+0x28]`) and goes straight to
     `pullup(0)`; the e0288 build — the **only recorded clean physical composite teardown**
     (E0252) — loads `ops.unconfigure` (`[s+0x2c]`, original `0x602b90cc`) first. So E0350
     pulled D+ down with interfaces 0/1/2 still configured and the reference endpoint map
     (`ctx+0xB4` → 0x84) still live — exactly E0250's decoded hazard; E0213 shows the original
     interface stop is what releases wrappers/endpoints. Confidence medium-high.
   - **H2 — holds leave the EP0 descriptor hooks bound and the composite table installed.**
     Any `session_end` hold after the UDC stop leaves D+ down, the four EP0 `BL` hooks bound,
     the module pinned and the module's descriptor root installed; the bound dispatcher
     answers `GET_DESCRIPTOR` from `live->source` regardless of `gc+0x6c`
     (`uvc_ptp_native_backend.c:68-87`). That is the only mechanism found that explains
     **non-recoverability** (replug and camera-menu mode toggle both hit the same hooks; only
     a battery pull clears kernel memory). Confidence high for the mechanism.
   - **H3 — restoring an owner-replaced descriptor root** is a latent path: the lease refuses
     with `-116` (no dangling install) but holds in the same hooked state. Low as the E0350
     trigger.
   - **Dismissed:** the a6400 vs ZV-E10 `usbg_cmn` layout difference
     (`make_ep_list` writes `+0xA2/A4/A8` vs `+0xB2/B4/B8`; `usbg_cmn_new` allocates 0xB0 vs
     0xC0) does **not** affect this module — `usbg_video.ko` carries its own copies at
     `0x28dc/0x295c`, self-consistent with E0319's `+0xB2/B4/B8`
     (`artifacts/analysis/unicorn-teardown-e0352/usbg_cmn-abi-diff.json`).
2. **Fix implemented and Unicorn-proven:** a single ordered sequencer
   (`tools/native_camera/uvc_ptp_soft_disconnect.c`) now owns the whole end path:
   **1** unconfigure (original `0x602b90cc`) → **2** bridge quiesce (reference STOP) →
   **3** endpoint-map release gate (`ctx+0xB2/B4/B8`) → **4** UDC down (`pullup(0)` →
   `setup_disconnect` → `gcw_stop`) → **5** unbind EP0 hooks → **6** unregister/demote shadow
   drivers (check before clearing flags) → **7** descriptor restore (owner-replacement +
   shadow-record guards) → **8** demote → **9** explicit reconnect
   (`gcw_start` → EP0 arm → `pullup(1)`).
   Unicorn executes the real compiled sequencer with the real bridge/lease code: **12/12 cases
   passed**, clean trace
   `UNCONFIGURE STOP PULLUP0 SETUP_DISCONNECT GCW_STOP CHECK UNBIND_EP0 UNREGISTER(2) UNREGISTER(1) CHECK FREE_DESC_TABLE CHECK GCW_START EP0_ARM PULLUP1`,
   `phases=0x1ff`, `ep_id=0x84 count=1 list=0`, descriptor restored, drivers retired, reconnect
   observed.
3. **Rebuilt and re-audited artifacts (not deployed):**
   - transport: `artifacts/native/uvc-transport-e0352-teardown/…ko`, **74,276 B**,
     SHA-256 `9da57a3317e2074f8daeea0b48972660e145cd3d9cff4243c891f2e889c0d687`,
     audit `offline_module_audit_passed` (transport, 117 checks, 8 documented skips, 0 failures).
   - enumeration: `artifacts/native/uvc-enum-e0352-teardown/…ko`, **74,528 B**,
     SHA-256 `63e5b475aa0b0e95fa4c3cb8b3c6b782a7fbeee90cd6fc86f73922c0c910c3a2`,
     audit `offline_module_audit_passed` (enumeration, 118 checks, 0 skips, 0 failures).
   Guard contracts unchanged: 55 verified imports, fops relocations, vermagic, only the
   documented reference instructions `0x116c/0x13e8/0x13ea` patched.

Status: offline verified (source + Unicorn + build/audit + tests). **No enumeration-recovery
claim** — the sequence has never run on hardware.

## Method / evidence

- Traced the shipped end path by disassembling `uvc_ptp_session.o` from the E0350 artifact and
  the e0288 `uvc_ptp_session.o` for comparison; mapped every called kernel primitive to its
  kallsyms address from E0348 (`0x602b90cc` clear-configuration is a UDC no-op per E0250;
  `0x602b1d3c` `dwc3_gadget_pullup`; `0x602bd834/0x602bd7f8` `usb_gcw_stop/start`;
  `0x602b8f8c` original interface stop per E0213; `0x602b9464` `setup_disconnect`).
- Compared `usbg_cmn.ko` symbols between the a6400 firmware and the ZV-E10 reference
  (same sizes, five differing byte bodies) — see the dismissed item above.
- Unicorn fixture: `artifacts/analysis/unicorn-teardown-e0352/b4_soft_disconnect_verify.py`
  builds `fixture/soft_disconnect_fixture.c` with `arm-linux-gnueabi-gcc`, links it with the
  shipping object via `ld --no-undefined` (all 55 imports bound to recorders) and executes the
  compiled sequencer on Cortex-A9/ARM. Receipt:
  `b4-soft-disconnect-unicorn.json` (`status=passed`, 12/12, module sha `9da57a33…`).
- New focused test `tests/test_uvc_ptp_soft_disconnect.py` (10 tests) pins phase order,
  unconfigure-before-pullup, endpoint-map gate, descriptor guards, late-failure reconnect,
  the four `check_error` sites, `session_end` delegation and builder wiring.

## Fail-closed behaviour proven in Unicorn

| Case | Gate | Result |
| --- | --- | --- |
| residual endpoint map (`ctx+0xB4 != 0`) | phase 3 | `-16`, **no** pullup(0)/unbind/reconnect |
| bridge callback in flight | phase 2 | `-16` before the UDC is touched |
| foreign EP0 site word | phase 5 | `-116`, no descriptor free, module table kept, reconnect issued |
| native unregister failure | phase 6 | `-16`, no free, both shadow records kept, reconnect issued |
| quarantined lease | phase 7 | `-16`, no free |
| `free_desc_tbl` failure | phase 7 | `-5`, lease quarantined, reconnect issued |
| owner-replaced table | phase 7 | owner table kept (`DESC_OWNER_KEPT`), no free |

The session never becomes releasable on any failure, so the verified-stop attestation still
blocks `rmmod`; every late failure still reconnects the UDC.

## Confidence and limitations

- Offline only: H1/H2 remain hypotheses; nothing proves the camera returns to MSC.
- `pullup(0)`'s busy loop is unbounded (E0184); unconfigure-first removes the known reason it
  can spin, but a live stall remains possible.
- The `[a6400_td] done phases=… failed=…` trace lives in kernel memory and does not survive a
  power cycle; the `0x8010f022` status ioctl remains the live gate signal.
- `ctx+0xB2`/`0xB8` stay from the last START (only `ctx+0xB4` is released by the driver), by
  design; a later START rewrites them.

## Next experiment (bounded, RAM-only; needs explicit go-ahead)

Preconditions: fresh boot (uptime < ~120 s so the 256 KiB coherent window allocates);
hash-verified push/readback of `9da57a33…`; SD `O_SYNC` logging armed (E0351) and host USB ETW
capture armed before teardown; verified-stop policy unchanged (no `rmmod` without receipt);
battery-pull recovery documented.

1. **Run A — teardown without a host stream** (isolates H1): INIT until Windows shows
   `054C:0322` + MI_00/MI_01, do **not** open DirectShow, run the 45–60 s session out, stop with
   `IOCTL_UVC_STOP (0x0000e001)`. Expect `[a6400_td] done phases=1ff failed=9 error=0 ep=1
   list=00000000 desc=1 reconnect=1`, status `{IDLE,0,0,0}`, `rmmod` OK, MSC without replug.
2. **Run B — one `ffmpeg -f dshow` attempt then stop** (isolates H2): `failed_phase` 0/1/2 =
   interfaces never stopped (H1), 4 = EP0 hook restore, 5 = unregister, 6 = descriptor.
3. **Run C — mode switch to MSC with capture armed** (isolates H2's host half): if "unknown
   device" recurs, the ETW capture decides between stale EP0-answered composite descriptors
   (H2) and a descriptor-content cause.
4. Persist `[a6400_td]`/sd receipt before any recovery; battery-pull contingency; verify the
   42-module MSC baseline afterwards.

## Safety statement

No camera was accessed and no module was loaded in this work. All artifacts are offline
builds/audits; any future session remains RAM-only (`/tmp_bt` + gated SD log only, never
internal flash) with battery-pull recovery.
