# E0203 — Four-core code visibility physically verified

## Implementation and source contract

Added `uvc_ptp_code_sync.{c,h}`. It validates a bounded range, runtime cpu_cache[4] target0x60119de4 and selected native instruction words, plus nr_cpu_ids/online-mask bounds. It calls the original v7_coherent_kern_range through the normal exported cpu_cache table, then synchronous normal-exported on_each_cpu(wait1). Each compiled MOD callback issues DSB/ISB and records its actual CPU bit. Missing bits, CPU out of range or online-mask change reject. Caller must serialize/pin code through return.

Original __v7_proc_info points to cache initializer0x604b4a90; its index4 is0x60119de4. Original helper cleans D-cache lines to PoU before DSB, invalidates I-cache lines, invalidates branch predictor, DSB and ISB. This provides more than the old ICIALLUIS-only helper0x60119c80. All new imports (cpu_cache,cpu_online_mask,on_each_cpu) are verified normal exports, no GPL-only import or donor-license change.

Provider is currently wired **only to the private route dry-run leave operation**, while its real module pin is held. It is not yet wired to native entry publication or the older native backend descriptor-patch flush routine. That older routine must be replaced/checked before any real descriptor activation; current diagnostic does not invoke it.

## Offline validation

Candidate `artifacts/native/uvc-ptp-module-e0203/usbg_video_a6400_shared_candidate.ko`, **67496bytes**, SHA-256 **c225289cb062ab933c459441e777f09e36d380aab0874354f00e2f6f297af569**,55 verified imports. **98 compiled ARM module controls pass**. New cases cover missing-core HELD/pin retention and recovery, actual compiled callback accumulation for CPU0..3 and CPU32 rejection. Cache helper/on_each_cpu dispatch are recorders in these tests; physical behavior is below. All **605 tests pass in21.542s**.

## Physical validation

Using the existing exact E0200 helper, the new module performs private-token publish/restore under the verified stop scope. It invokes native coherent cache helper plus actual synchronous callbacks on all online CPUs before each private barrier release. Kernel logs show **two `seen=f expected=f result=0` receipts** (all four cores) for the publish/retire cycle.

Native stop/membership checks174/174,error0;174 attached/resumed in1340ms,TracerPid0. Close/rmmod0, node/module payload removed, module list byte-equal restored. Pre/post owner observations match PID149 FD85/174TIDs/errors0; debugger703 responsive. No real fops/text/descriptor hook write, activation or USB mode change. All writes/tmp_bt only.

Receipts: `artifacts/hardware/uvc-ptp-code-sync-e0203`, nested cpu, recovered kernel log and manifest. Owner receipts `uvc-ptp-owners-{pre,post}-code-sync-e0203`; validation `artifacts/uvc-ptp-owners-code-sync-e0203-validation.json`.

Initial optional log collection used unavailable camera command tail (status127), which did not affect the successful test/cleanup. Complete dmesg was subsequently captured to a unique RAM file and archived with digest; both four-core receipts recovered. Runner now uses native dmesg-to-RAM/readback instead of tail, preserving full log/truncation checks.

## Milestone boundary

Instruction visibility is now physically validated on a module-owned test word. It is **not old ioctl-caller retirement**, and per-core IPI completion does not prove no task is suspended inside or approaching wrapper code. Entry bridge E0201 is still offline/unlinked. Need native ingress/old-caller drain and safe removal lifetime, then the bounded actual-hook MSC lifecycle, then PC Remote combined enumeration. Those are the three remaining phases to the first enumeration test; sensor video plus simultaneous controls is additional validation. Camera remains MSC, combined test not ready.
