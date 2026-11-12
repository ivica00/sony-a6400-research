# E0386 — Run B16 DEPCMD CmdStatus/XferRscIdx and ring verdict: no rejected STARTTRANSFER observed; 5 s remains host-side

Date: 2026-11-12. Physical Run B16-roprobe with module **381e039c…** (90,012 B,
audit 117/8/0, exact-object Unicorn overall_pass=true) and daemon 99047575….
**Battery pull was required** after the host sequence (camera did not switch back);
camera rebooted, is healthy in MSC (42 modules, no `usbg_video`, `/tmp_bt` baseline).

## 1. What the patch changed / evidence captured

- `ev` readout fixed: `ev=68a124b0` with valid `lpos/cnt` (previous builds read
  `lpos=0 cnt=0` because `[dwc+0xcc]` was not double-dereferenced).
- `dep0/dep1 resource_index` (`dep+0x55/0x57`) and live `DEPCMD0/1`
  (`regs+0x700+0x10*idx+0xc`) logged at every GCRO point, with
  `CmdStatus [15:12]` and `XferRscIdx [22:16]`.
- `CLASS lr=<caller>` + raw `ep/a3/dwc/state/next/fl` on every class entry,
  including the `no-udc-ep` branch.

## 2. DEPCMD / CmdStatus / XferRscIdx (B16 cycles at 158/163 s)

All sampled arms show **`CmdStatus = 0`** — no rejected STARTTRANSFER:
```
158.242455 CLASS pre   dep0i=0 dep0r=0 depcmd0=00000006 cmdsts0=0 rsc0=0
                       dep1i=1 dep1r=0 depcmd1=00010006 cmdsts1=0 rsc1=1
158.244567 queue       dep0i=0 dep0r=0 depcmd0=00000006 cmdsts0=0 rsc0=0
                       dep1i=1 dep1r=1 depcmd1=00010006 cmdsts1=0 rsc1=1
158.248138 complete    dep0i=0 dep0r=0 depcmd0=00000006 cmdsts0=0 rsc0=0
                       dep1i=1 dep1r=0 depcmd1=00010006 cmdsts1=0 rsc1=1
163.243000 SET pre     dep0i=0 dep0r=0 depcmd0=00000006 cmdsts0=0 rsc0=0
                       dep1i=1 dep1r=0 depcmd1=00010006 cmdsts1=0 rsc1=1
163.245211 SET queue   dep0i=0 dep0r=0 depcmd0=00000006 cmdsts0=0 rsc0=0
                       dep1i=1 dep1r=1 depcmd1=00010006 cmdsts1=0 rsc1=1
163.248733 SET complete dep0i=0 dep0r=0 depcmd0=00000006 cmdsts0=0 rsc0=0
                       dep1i=1 dep1r=0 depcmd1=00010006 cmdsts1=0 rsc1=1
```
`depcmd0=0x00000006` = CmdStatus 0, XferRscIdx 0; `depcmd1=0x00010006` =
CmdStatus 0, XferRscIdx 1. The D1 missing-CmdStatus check exists in the kernel but was
**not exercised** in this run (D6): no hardware-rejected start transfer can explain the
5 s stall from these samples.

## 3. Event ring (`ev` fixed) and class-entry LR

```
158.242455 GET pre   ev=68a124b0 lpos=28c cnt=4
158.248138 GET comp  ev=68a124b0 lpos=294 cnt=c
163.243000 SET pre   ev=68a124b0 lpos=2a0 cnt=c
163.248733 SET comp  ev=68a124b0 lpos=2a8 cnt=8
```
This matches the corrected E0384 batch semantics: GET complete `lpos=0x294`,
`cnt=0xc`; SET pre `lpos=0x2a0`, `cnt=0xc`; SET completion consumes the next batch
(`lpos=0x2a8`, `cnt=8`). The `evw` word dump itself was not emitted (the probe kept
the `buf/len` validity guard; the current run's `ev` fields validated but `evw` was
absent), so the word-level ring content for 0x2a0/0x2a4/0x2a8/0x2ac in B16 is not in
this log; the B12 e0372 word dump remains the word-level reference.

```
158.241827 CLASS lr=5f5694b4 ep=68a1c9c0 a3=5f569498 dwc=689e5810 state=8d next=2 fl=8d
163.241965 CLASS lr=5f5694b4 ep=68a1c9c0 a3=5f569498 dwc=689e5810 state=89 next=2 fl=89
```
Both legitimate class entries have the same caller `lr=5f5694b4` with live
`ep=68a1c9c0` and `dwc=689e5810`; **no `no-udc-ep` shadow entries occurred in the
B16 cycles**. The four `no-udc-ep` lines at 141.742/146.744 in the retained SD log are
from the previous e0382 probe build (no `lr` field), not from B16; they cannot be used
for the B3 caller question.

## 4. Behaviour reproduced

- GET data completion `actual=26` at 158.247657; SET queue arms the bounce
  (`bpl=08a26000 sz=0x40 ctl=0x0c53 HWO=1`) at 163.245211; SET completion at
  163.248284 returns `actual=0` while the bounce TRB still reads
  `sz=0x40 ctl=0x0c53 HWO=1` and `fl` lost `ep0_bounced` (0x8b→0x89). This is the same
  stale/queued ep0 completion consumed by `complete_data` as the data completion
  (no HWO/ownership validation).
- The GET→SET spacing is again ~5 s (158.2417→163.2418), with the GET URB completing
  only at the host’s timeout/abort boundary; ffmpeg still failed with RenderStream.

## 5. Verdict

- **No device-side rejected `DEPCMD_STARTTRANSFER` was observed** (`CmdStatus=0` at all
  sampled points, `XferRscIdx` valid). D1’s missing check is real but unexercised;
  it cannot explain this run’s 5 s stall.
- The 5 s remains **host-side** (xHC control-TD timeout/abort), consistent with E0382;
  the SET `actual=0` remains the queued/stale ep0 completion consumed against the
  bounce TRB while HWO=1.
- No firmware state-machine fix is supported by B16. The remaining actionable
  observation is host-side/XHC or a word-level event trace; not another device patch.

## 6. Run limitations

- **Battery pull was needed**; `/tmp_bt` was cleared by the reboot and the daemon
  receipt shows `stop_verified=0`, `teardown_verified=0`. The SD `A6400K.LOG` and host
  ETL were preserved. Camera is healthy in MSC after reboot (42 modules, no
  `usbg_video`, `/tmp_bt` baseline).
- `evw` word dump absent in B16 (only `lpos/cnt`); B12 e0372 remains the word-level
  ring reference. The retained log contains previous-boot cycles (127/132/141/146)
  before the B16 cycles (158/163); only 158/163 belong to this probe.
