# E0201 — Original native entry bridge covers cached VFS targets offline

## Why this approach

E0176 proved replacing fops+0x20 misses a VFS call that already cached the original function pointer. This offline experiment instead changes **one aligned instruction at original gadgetcore ioctl entry0x602b8844** to branch to the guard wrapper. A cached pointer still points to that entry and reaches the new branch. This addresses the specific pre-entry cached-pointer gap, not calls already past the entry or safe SMP publication.

No camera access or shared-module change occurred. Latest physical state remains E0200, module unloaded/MSC.

## Bypass without recursion or approximated native decisions

New `tools/native_camera/uvc_ptp_native_ioctl_entry.S` reproduces original `mov ip,sp` and `push {r4,r5,r6,r7,fp,ip,lr,pc}`, repairs the saved PC word to original0x602b8850, restores ip's original-prologue value and resumes untouched native code at0x602b884c. The saved PC repair preserves the original APCS stack frame, not only functional return values. The guard's original target is this bypass, so it does not recursively re-enter the patched native entry.

The assembly is **not linked into the physical/shared candidate** yet. It is a target-specific offline component, not a generic relocated prologue. Original first two words are hash/word checked before tests.

## Executed controls

`tools/research/probe_uvc_ptp_native_entry.py` builds an ARM ELF containing the real MOD guard/mode gate, entry wrapper fixture and bypass. It executes original hash-verified VFS/native ioctl bodies and original atomic bit helpers. File/fops/gadget objects are explicit fixtures; native unknown-command and active-commit-busy paths execute actual retained instructions, not native return recorders.

**11 controls pass**:

- exact original/bypass 32-byte prologue frame equality including saved PC and ip;
- for unknown command and active commit, stop original VFS after loading the old target but before BLX, patch the entry in emulated memory, then verify that this cached pointer reaches wrapper and original body exactly once;
- preserve original -25/-16 result, guard count returns0 and all callee-saved registers match;
- HELD rejects before the native body;
- restore original first instruction and verify direct original execution without wrapper.

```
python -m tools.research.probe_uvc_ptp_native_entry --output-dir artifacts/analysis/uvc-ptp-native-entry-e0201
```

Manifest and ELF are in that directory. Emulator translation-cache removal is explicit and **not evidence of physical CPU cache synchronization**. No USB hardware operation is reached by these cases.

## Remaining installation/removal contract

Calls already past native entry before publication remain outside the new guard count. Restoration can also race a CPU already headed toward wrapper code. Need a concrete multi-core publication/drain/lifetime protocol before live entry writes; E0200's private barrier is not sufficient.

Retained export audit confirms on_each_cpu/smp_call_function/smp_call_function_single are normal exports, while stop_machine is GPL-only. No donor license change or GPL-only import is proposed. Original cache helper0x60119c80 emits ICIALLUIS (`mcr p15,0,r0,c7,c1,0`), but it has no explicit per-core context synchronization in that body. Native on_each_cpu forwards wait to the remote-call helper and invokes local callback with interrupts disabled; its completion/remote ordering still requires verification. Neither an I-cache flush alone nor the existence of these exports is claimed as caller retirement.

Next verify synchronous per-core instruction visibility and wrapper lifetime under entry replacement/removal, then integrate the bridge with guarded commissioning. No source sensor/UVC/PTP coexistence claim. Combined PC Remote+UVC/PTP test remains not ready; leave camera MSC.
