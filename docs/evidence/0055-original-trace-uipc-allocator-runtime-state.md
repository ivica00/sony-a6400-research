# Evidence 0055: Original trace allocator reaches UIPC runtime state

## Result

The E0054 trace request is now followed through a separate bounded original-code experiment in `libosal_uipc.so`. It records **32 instruction events, including the terminal read**, and stops at **0x2898**, reading the unknown four-byte `uconf` descriptor at **0xef80**. No allocation result, failure, ioctl response or descriptor is supplied. This is an isolated call with constructed stack/register framing, not an extension of the main process or a completed trace exchange. E0054's 202-instruction initializer report and E0034's main/UI boundary remain unchanged.

Input: preserved `nflasha15_unpacked/lib/libosal_uipc.so`, SHA-256 **b6ded35add9582413b401cf4db78ec2c9a201b632e78c2731d6bbb379249b3eb**. Hash is checked against inventory before and after each run. The analysis uses small original function windows and exact ELF relocations; it does not repeat the large libObj import.

## Original control flow and arguments

Original Thumb `osal_valloc_msg_wait` entry0x3fed tests bit0x8000 of queue0x008f013a. This bit is clear, so original execution takes the tail branch at0x4004 through the Thumb-to-ARM veneer0x1980 and original PLT0x1984 into `u_osal_valloc_msg_wait` entry0x2871. The other local-queue branch, including its subsystem0x8f tests, is **not taken** by this request.

The isolated same-image R_ARM_JUMP_SLOT binding is checked against the original PLT and relocation. Original wrapper literals resolve a R_ARM_GLOB_DAT slot0xe2b0 for defined object `uconf` (36 bytes). Only its address is bound; neither source initial bytes nor mapped page padding become runtime configuration.

Original instructions construct the transport ABI:

- ioctl command register: **0x8000000a**.
- Outer two words at frame+16: queue **0x008f013a**, parameter pointer **frame+4**.
- Inner three words at frame+4: output pointer **0x08002fac**, requested size **42**, flag **0**.
- Original PC0x2898 must read `uconf[0]` before original ioctl call0x289a / PLT0x17f8.

All stack bytes read by the experiment must have been written by original instructions. Reads of writable library state are guarded even when the file contains bytes. Only bounded original code windows execute; non-stack writes, uninitialized stack reads, unknown instructions and unsupported code stop. The run is bounded to100 instruction events and100ms. The output slot receives no pointer.

## Producer and existing model limits

Retained static original `do_init` prefix0x210c..0x2180 shows an `open` import at0x211c, its return stored into `uconf[0]` at0x2128, followed by connection ioctl0x80000010 and shared mapping via mmap at0x2178. These are **static producer observations**, not executed open/connect/map results in this experiment. The initialized descriptor and pool cannot be selected from static initial values.

`GuestUipc.handle_valloc_msg_wait` already recognizes the same nested parameter layout. Its current implementation allocates aligned slices from a host-maintained pool cursor. ABI agreement alone does not establish original driver pool ownership, allocation state, waiting behavior or trace-recipient execution. This experiment does not call that model or promote its allocation result to original allocator evidence.

Next: connect original UIPC initialization and allocator state under the explicitly declared process environment, auditing pool/driver effects before accepting an allocation reply. Continue original trace handling afterward. E0051's kernel GRM callback thread/lock prerequisite remains separate.

## Reproduction and checks

```
python -m tools.research.trace_uipc_allocator --report-dir artifacts/execution/NEW_DIRECTORY
```

Reports `trace-uipc-allocator-verified` and `trace-uipc-allocator-repeat` are byte-identical, SHA-256 **3a35d037ab69809f7c340148890394cb3a915f30385fb5c0c41433c456c1aae8**. Early reports are retained separately; final reports additionally include the static initializer window and verified import names. No original input or process-backend interface was changed.

Full suite: **354 passing tests**, `artifacts/execution/trace-uipc-allocator-suite.txt`. Status image regenerated with unchanged capability counts and no UI claim.
