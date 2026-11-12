# E0386 — Correction round: “probe-induced NAK” retracted; vendor status path lacks SETUP_PENDING check; class re-entry undecidable; observation-only probe plan

Date: 2026-11-12. Offline (subagent E0386 correction). Supersedes E0385 §4–§6 and the
previous E0384 §0.4/§3 note. No camera, no module build/run.

## 1. Retracted: the initial status NAK is NOT probe-induced

`dwc3_ep0_complete_data 0x602b30a8..0x3348` never arms a status TRB; its only
`start_trans` calls are the ZLP data arms at `0x602b31d8/0x602b3314` (`dw3=0x0c53`).
`do_control_status 0x602b253c` has only two callers: `0x602b34b0` (NRDY STATUS) and
`0x602b27f0` (queue delayed_status path, requiring flags bit5 which `0x89/0x8b/0x8d` do
not have). Therefore the **first status token is NAKed with stock code too**; a faster
`req->complete` cannot prevent it. The prompt-arm conclusion stands: `0x0c43` is armed
at ~141.4246 s (B12) / ~140.6786 s (B14). Only the host’s ~5.01 s retry/abort latency
is abnormal.

## 2. Downgraded to UNDECIDABLE: the 141.742 s class re-entry

Static reachability says `core_cb_class` is called only via `setup_req 0x602b94a4` ←
gadget-driver setup op `0x602b8328` (referenced only from ops data `0x604e5030`) ←
dwc3 ep0 setup path (`0x602b2ec8/0x602b2f94`), which runs only for an ep0
`XFERCOMPLETE` with `ep0state==1` (`0x602b2cd0..0x2ce8`). But the B12 ring snapshots
show no consumed ep0 event at 141.742 s. New fact: two shadow class entries (+321 ms /
+323 ms after the primaries: 141.742337 after 141.421331; 146.744486 after 146.421503)
with no EP0 queue, no ring snapshot and probe `no-udc-ep`; B14 (different build) has
none. The deciding datum — the class-entry caller LR — is not logged, so it remains
undecidable.

## 3. Confirmed / new claims (`e0386-claims.json`)

- **C1 PROVEN:** vendor status path `0x602b334c` is 5 instructions; it never reads
  `trb->size` and has **no SETUP_PENDING check** (unlike mainline).
- **C2:** a SETUP landing in the stale armed OUT TRB is consumed as an ordinary status
  completion; `out_start` then arms a fresh SETUP TRB → reproduces `0x2a0+0x2a4` with
  no duplicate.
- **C3 UNDECIDABLE:** the residual (64 vs 56) is not in any log; B14 GCRO at
  145.683983 already reads the NEW SETUP TRB (`ctl=0x00000c22 sz=0 bpl=089fe000`), at
  145.686654 the bounce TRB (`0x0c53 sz=40 hwo=1`).
- **C4 PROVEN:** no ENDXFER / `dwc3_ep0_end_control_data` (no kallsyms symbol;
  `stop_active_transfer 0x602b03d8` is called only from `0x602b04a8/0x602b05d0/
  0x602b0f38/0x602b1130`, none ep0).
- **D1 PROVEN:** `send_gadget_ep_cmd 0x602b0220` ORs CMDACT `0x400` (`0x602b0348`),
  writes DEPCMD (`0x602b0370`), polls 500× (`0x602b0374`, `__const_udelay` `0x602b03c0`),
  timeout → −110 (`0x602b03b4`), success → 0 (`0x602b0398`), not the status.
- **D2:** `start_trans` negative → return negative, no side effects (`0x602b24f4`);
  0 → flags |=0x10, resource_index = dep+0x57 from DEPCMD[22:16], next=1
  (`0x602b24f8..0x602b2530`).
- **D3:** resource index reused only by NRDY DATA Update-Transfer
  (`0x602b33dc/0x602b33f4`), cleared by every XC (`0x602b2cc0`).
- **D4:** probe logs neither DEPCMD result nor resource_index/DEPCMD0; no warning in
  the window implies no timeout (`0x602b25a8..0x602b25b8` warns on non-zero).
- **E:** SET_CUR is 3-stage, wLength 26 (`rt=21 req=01 val=0100 idx=0002 len=001a`;
  state `0x89`, next=2; queue dir OUT len 26). `0x20c2` = NRDY subtype STATUS ep1
  (ep0-IN), dropped at `0x3450` because next was 1 (and would be 2 from the setup
  decode) — never 3; had it been 3 it would arm a ZLP status TRB on eps[1] (len 0,
  ctrl 0x40). Why the status token precedes the data NRDY is undecidable without a host
  trace of the same run (B12 ETL not decoded).

## 4. Observation-only probe plan (no req->complete hijack)

1. **Class wrapper for every class entry** (also when the guard fails): log
   `lr = __builtin_return_address(0)`, raw `ep`, `ep0state/next/flags`, ev_buf
   `lpos/count/flags`, `ctrl_req[0..7]` — settles the 141.742 re-entry question.
2. **One read-only address kprobe at `0x602b334c`** logging `ep0_trb.size` and
   `ctrl_req[0..7]` — settles C3; if the kernel has no kprobes, state that this cannot
   be answered.
3. **Post-arm snapshot additions:** dep0/dep1 resource_index (`dep+0x57`),
   `dwc->ep0_next_event`, and `regs+0x700+0xd` (DEPCMD0 CMDACT+status) — completes D4.
4. For E: per-event in-kernel log (event word + ep0state/next/flags + ep flags before
   dispatch) or decode the B12 host ETL.

No build or camera run for E0386. Full suite **1312 tests OK**; docs synced.


## 7. Round-2 handoff (offline maximum; no build/run)

A second offline round produced the exact patch/plan, but did not build or touch the camera.

- **B3 (the +321/+323 ms `no-udc-ep` caller):** the shadow class entries are present in **both**
  B12 and B14 logs (same camera boot; B14 retains B12 cycles). They occur only in the two stalled
  cycles (141.742/141.743, 146.745) and never in the healthy cycles (115?130 s, 140.67/145.68,
  618/623 s). The pointer guard is the wide `[0x5F000000,0x70000000)` window, so this is **not**
  ?ep out of range?; `a6400_uvc_ep0_snapshot` fails at `[ep+8]` (ops) or `[ep+0x48]` (ep->dwc),
  i.e. a stale/unbound ep object passed by the deferred caller. The exact caller remains
  **UNDECIDABLE without the class-entry LR**, which the new patch logs.
- **D1 strengthened to PROVEN (D5):** `dwc3_send_gadget_ep_cmd 0x602b0220` keeps only CMDACT
  (`0x602b0384 ands r5,r5,#0x400`) and returns 0 (`0x602b0398 mov r0,r5`); it cannot report
  `DEPCMD[15:12] CmdStatus`. A rejected STARTTRANSFER therefore yields return 0,
  `dep->flags|=0x10`, `resource_index=DEPCMD[22:16]` (plausibly 0), `next=1`, and no warning.
  Whether any observed arm was actually rejected is **UNDECIDABLE from the existing logs** (D6);
  absence of `warn_slowpath` only excludes the `-110` CMDACT timeout. The new probe's DEPCMD
  reads decide it.
- **Handoff artifacts:** `e0386-roprobe.patch.md` (exact hunks for
  `tools/native_camera/uvc_callback_bridge.c`: ev double-deref, dep0/dep1 resource_index +
  DEPCMD0/1 at `0x700+0x10*[dep+0x55]+0xc` with CmdStatus 15:12 / XferRscIdx 22:16, class-entry
  LR + raw ep incl. the no-udc-ep branch) and `e0386-roprobe-plan.md` (build layout, acceptance
  hashes/audits, bounded run-b16 steps, command-status/resource-index decision table).

Build and hardware run require explicit authorization; nothing was built or run in this round.
